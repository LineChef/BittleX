"""Goals (docs/planned/goals-plan.md): knobs, the judge, the ball-punt scorer, the claw look and search moves, a whole session against fakes, the voice start and the report.
No hardware, no network, no API call."""
import json

import pytest

from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.goals import ball_punt, spec
from pi_pipeline.goals.approach import AttemptResult, Outcome
from pi_pipeline.goals.journal import Journal, State, lessons_from
from pi_pipeline.goals.judge import Judge
from pi_pipeline.goals.runner import GoalSession
from pi_pipeline.goals.spec import Goal, Knob
from pi_pipeline.tests.test_ball_chase import FakeCamera, disc, picture


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_GOALS", str(tmp_path / "goals.json"))
    monkeypatch.setenv("G2_GOAL_JOURNAL", str(tmp_path / "journal.jsonl"))
    monkeypatch.setenv("G2_GOAL_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("G2_PUNT_SETTINGS", str(tmp_path / "punt_settings.json"))
    monkeypatch.setenv("G2_GOAL_OVERRIDES", str(tmp_path / "overrides.json"))
    names = [n for n in dir(bc) if n.isupper()]
    keep = {n: getattr(bc, n) for n in names}
    yield
    for n, v in keep.items():
        setattr(bc, n, v)


# ------------------------------------------------------------------------------------------------- knobs

def test_a_knob_checks_its_bounds_and_steps_inside_them():
    k = Knob("d", "float", lo=1.0, hi=4.0, step=0.5, unit="in", label="punching from")
    assert k.check(2) == 2.0 and k.stepped(2.0, -1) == 1.5 and k.stepped(1.0, -1) is None and k.stepped(4.0, +1) is None
    with pytest.raises(ValueError):
        k.check(9)
    with pytest.raises(ValueError):
        k.check(True)
    c = Knob("g", "choice", options=("a", "b"))
    assert c.check("a") == "a" and c.stepped("a", 1) is None
    with pytest.raises(ValueError):
        c.check("z")
    assert k.show(1.5) == "1.5 in" and k.says() == "punching from"


def test_a_goal_applies_the_users_controls_and_free_is_the_default():
    g = Goal("x", "X", "ball_punt", controls={"punt_max_in": "fixed", "nope": "free", "lost_looks": "banana"})
    knobs = {k.name: k for k in g.knobs(ball_punt.BallPunt().knobs())}
    assert knobs["punt_max_in"].control == "fixed" and knobs["lost_looks"].control == "free" and knobs["punch_lunge_s"].control == "ask"
    assert "walk_gait" not in knobs and knobs["search_order"].control == "free" and knobs["align_tries"].control == "free"     # the walk is never switched (user, 2026-10-31)
    for fixed in ("search_walk", "max_seconds", "back_up_budget_s", "claw_pan_sign", "punch_hold_s", "back_up_s", "stuck_punts", "search_step_deg"):
        assert knobs[fixed].control == "fixed", fixed


def test_goals_file_overrides_the_builtin_and_survives_a_bad_file(tmp_path):
    p = tmp_path / "g.json"
    spec.save_goal(spec.replace(spec.BUILTIN["ball_punt"], attempts=4), str(p))
    goals, problems = spec.load(str(p))
    assert goals["ball_punt"].attempts == 4 and goals["ball_punt"].start_words and not problems
    p.write_text("{not json")
    goals, problems = spec.load(str(p))
    assert goals["ball_punt"].attempts == 10 and problems


# ------------------------------------------------------------------------------------------------- the judge

import random  # noqa: E402

KN = [Knob("a", "float", lo=1.0, hi=5.0, step=1.0, label="a at"), Knob("b", "choice", options=("x", "y", "z")),
      Knob("c", "float", lo=0.0, hi=1.0, step=0.1, control="ask"), Knob("f", "float", lo=0.0, hi=9.0, step=1.0, control="fixed")]
DIAG = {"bad": [("f", 1), ("a", -1)], "lost": [("b", "other")], "soft": [("c", -1)], "askfirst": [("c", -1), ("a", +1)]}
BASE = {"a": 3.0, "b": "x", "c": 0.5, "f": 4.0}


def oc(code, score, success=False, stages=None):
    return Outcome(code, score, success, code, stages=stages)


def J(state=None, **kw):
    return Judge(KN, DIAG, state, rng=random.Random(0), **kw)


def test_every_attempt_counts_for_the_value_in_use_and_failures_vote_a_direction():
    j = J()
    s = j.begin_session(BASE)
    j.update(1, oc("bad", 0.2), s)
    r = j.record("a", 3.0)
    assert r["n"] == 1 and r["hits"] == 0 and r["down"] == 1 and j.state["focus"] == "a"            # the fixed knob f is skipped
    nxt = j.settings(BASE)["a"]
    assert nxt in (2.0, 3.0)                                                                          # only the current value or the neighbour the misses point to
    assert j.settings(BASE)["f"] == 4.0 and j.settings(BASE)["c"] == 0.5


def test_he_keeps_the_best_supported_value_not_the_last_one_tried():
    j = J()
    j.begin_session(BASE)
    for n, (a, ok) in enumerate([(3.0, False), (3.0, False), (2.0, True), (2.0, True), (2.0, False), (3.0, False)], 1):
        j.update(n, oc("hit" if ok else "bad", 0.9 if ok else 0.2, ok), dict(BASE, a=a))
    assert j.best("a", 3.0) == 2.0                                                                    # 2 of 3 at 2.0 beats 0 of 3 at 3.0
    kept = j.finish(BASE, 6)
    assert kept and kept[0].action == "kept" and kept[0].new == 2.0 and "2 of 3 good" in kept[0].note and "0 of 3" in kept[0].note
    assert j.begin_session(BASE)["a"] == 2.0                                                          # the next session starts from it


def test_a_knob_is_judged_only_by_its_own_stage():
    j = Judge(KN, DIAG, rng=random.Random(0), stage_of={"a": "punch", "b": "search"})
    j.begin_session(BASE)
    j.update(1, oc("lost", 0.0, stages={"search": 0.0}), BASE)                                       # never found: no punch, so nothing about a
    assert j.record("a", 3.0) is None and j.record("b", "x")["n"] == 1
    j.update(2, oc("hit", 0.9, True, stages={"search": 0.9, "punch": 0.9}), BASE)
    assert j.record("a", 3.0)["hits"] == 1


def test_a_fall_while_trying_a_value_bans_it_and_goes_back_to_the_best():
    j = J()
    j.begin_session(BASE)
    for n in (1, 2):
        j.update(n, oc("hit", 0.9, True), BASE)                                                        # a = 3 has a record
    j.update(3, oc("bad", 0.2), BASE)
    j.state["focus"] = "a"
    d = j.update(4, Outcome("fell", 0.0, False, "I fell"), dict(BASE, a=2.0))
    assert d[0].action == "undo" and j.settings(BASE)["a"] == 3.0 and j._banned("a", 2.0)


def test_a_fall_before_the_knobs_stage_bans_nothing():
    j = Judge(KN, DIAG, rng=random.Random(0), stage_of={"a": "punch", "b": "search"})
    j.begin_session(BASE)
    for n in (1, 2):
        j.update(n, oc("hit", 0.9, True, stages={"search": 0.9, "punch": 0.9}), BASE)
    j.state["focus"] = "a"
    fell = Outcome("fell", 0.0, False, "I fell")
    fell.stages = {"search": 0.5}                                                                       # fell while searching: the punch never came
    d = j.update(3, fell, dict(BASE, a=2.0))
    assert not any(x.action == "undo" for x in d) and not j._banned("a", 2.0)


def test_an_ask_knob_is_only_suggested_and_pins_limits_and_undos_hold():
    j = J()
    j.begin_session(BASE)
    d = j.update(1, oc("soft", 0.3), BASE)
    assert any(x.action == "suggest" for x in d) and j.settings(BASE)["c"] == 0.5 and j.state["suggestions"]["c"]["new"] == 0.4
    j = J(overrides={"pins": {"a": 4.0}})
    j.begin_session(BASE)
    for n in range(1, 6):
        j.update(n, oc("bad", 0.2), j.settings(BASE))
    assert j.settings(BASE)["a"] == 4.0 and j.state["focus"] != "a"                                   # pinned: never explored
    j = J(overrides={"limits": {"a": [3.0, 5.0]}})
    j.begin_session(BASE)
    for n in range(1, 12):
        j.update(n, oc("bad", 0.2), j.settings(BASE))
        assert j.settings(BASE)["a"] >= 3.0                                                           # his misses say lower, the limit says no
    j = J(overrides={"banned": {"a": {"2.0": None}}})
    j.begin_session(BASE)
    for n in range(1, 12):
        j.update(n, oc("bad", 0.2), j.settings(BASE))
        assert j.settings(BASE)["a"] != 2.0


def test_a_choice_knob_samples_among_its_options():
    j = J()
    j.begin_session(BASE)
    seen = set()
    for n in range(1, 12):
        s = j.settings(BASE)
        seen.add(s["b"])
        j.update(n, oc("lost", 0.0), s)
    assert seen >= {"x", "y"}


def test_an_uncounted_attempt_is_ignored():
    j = J()
    j.begin_session(BASE)
    assert j.update(1, Outcome("aborted", None, False, "stopped"), BASE)[0].action == "not_counted" and j.state["count"] == 0


# the permanent check: a made-up world with a known best (hit chance peaks at punching from 3 in), 10% misread misses, starting at 4 in
BEST_IN = 3.0
PK = [Knob("punt_max_in", "float", lo=1.0, hi=10.0, step=0.25)]
PDIAG = {"missed": [("punt_max_in", -1)], "never_punted": [("punt_max_in", +1)]}


def _world_run(attempts, rng, peak=0.8, fall=0.15, wrong=0.1):
    j = Judge(PK, PDIAG, rng=rng, stage_of={"punt_max_in": "punch"})
    base = {"punt_max_in": 4.0}
    j.begin_session(base)
    for n in range(1, attempts + 1):
        a = j.settings(base)["punt_max_in"]
        if rng.random() < max(0.05, peak - fall * abs(a - BEST_IN) / 0.25):
            j.update(n, Outcome("hit", 0.9, True, "hit", stages={"punch": 0.9}), {"punt_max_in": a})
        else:
            code = "missed" if a > BEST_IN else ("never_punted" if a < BEST_IN else rng.choice(["missed", "never_punted"]))
            if rng.random() < wrong:
                code = "never_punted" if code == "missed" else "missed"
            j.update(n, Outcome(code, 0.2, False, code, stages={"punch": 0.2} if code == "missed" else {}), {"punt_max_in": a})
    return j.best("punt_max_in", 4.0)


def test_the_judge_finds_the_best_value_in_a_made_up_world():
    rng = random.Random(7)
    finals = [_world_run(30, rng) for _ in range(400)]
    near = sum(abs(f - BEST_IN) <= 0.26 for f in finals) / len(finals)
    far = sum(abs(f - BEST_IN) >= 0.74 for f in finals) / len(finals)
    assert near >= 0.85 and far <= 0.08, (near, far)


# ------------------------------------------------------------------------------------------------- the ball-punt scorer

def _res(ended, trace, seconds=20.0, **extra):
    return AttemptResult(ended, seconds, trace, extra)


S = {"max_seconds": 75.0}


def test_a_punt_that_sends_the_ball_far_is_a_hit_and_a_faster_one_scores_higher():
    tr = [{"kind": "look", "ball": {"distance_in": 12, "bearing_deg": 0}, "t": 1}, {"kind": "act", "act": "punt", "at": (3.0, 0.0)},
          {"kind": "after_punt", "ball": {"distance_in": 20.0, "bearing_deg": 0.0}}]
    o = ball_punt.BallPunt().score(_res("punted", tr, 20.0), S)
    slow = ball_punt.BallPunt().score(_res("punted", tr, 70.0), S)
    assert o.code == "hit" and o.success and o.numbers["moved_in"] == 17.0 and o.score > slow.score > 0.5


def test_a_punt_that_leaves_the_ball_is_a_miss_and_one_at_the_claw_says_so():
    tr = [{"kind": "act", "act": "punt", "at": (4.4, 2.0)}, {"kind": "after_punt", "ball": {"distance_in": 5.0, "bearing_deg": 3.0}}]
    o = ball_punt.BallPunt().score(_res("punted", tr), S)
    assert o.code == "missed" and not o.success and o.score == 0.2
    tr = [{"kind": "act", "act": "punt", "at": (None, None)}, {"kind": "after_punt", "ball": {"distance_in": 3.0, "bearing_deg": 0.0}}]
    assert ball_punt.BallPunt().score(_res("punted", tr), S).code == "missed_vanished"
    tr = [{"kind": "act", "act": "punt", "at": (3.0, 0.0)}, {"kind": "after_punt", "ball": None}]
    assert ball_punt.BallPunt().score(_res("punted", tr), S).code == "hit_unseen"


def test_a_ball_farther_away_after_the_punt_or_gone_is_a_punt():
    tr = [{"kind": "act", "act": "punt", "at": (2.5, 0.0)}, {"kind": "after_punt", "ball": {"distance_in": 5.0, "bearing_deg": 0.0}}]
    o = ball_punt.BallPunt().score(_res("punted", tr), S)
    assert o.code == "hit" and o.success                               # 2.5 in farther: no longer at the claw (user, 2026-11-01)
    tr = [{"kind": "act", "act": "punt", "at": (2.5, 0.0)}, {"kind": "after_punt", "ball": {"distance_in": 3.0, "bearing_deg": 2.0}}]
    assert not ball_punt.BallPunt().score(_res("punted", tr), S).success      # still at the claw: a miss


def test_no_punt_is_scored_by_how_far_he_got():
    bp = ball_punt.BallPunt()
    assert bp.score(_res("time", [{"kind": "look", "ball": None}]), S).code == "never_found"
    far = [{"kind": "look", "ball": {"distance_in": 30, "bearing_deg": 0}}]
    assert bp.score(_res("time", far), S).code == "never_reached"
    close = [{"kind": "look", "ball": {"distance_in": 6, "bearing_deg": 20}}]
    assert bp.score(_res("time", close), S).code == "never_punted"
    pushed = [{"kind": "look", "ball": {"distance_in": 10, "bearing_deg": 0}}, {"kind": "act", "act": "walk"}, {"kind": "look", "ball": {"distance_in": 18, "bearing_deg": 0}}]
    assert bp.score(_res("time", pushed), S).code == "pushed_away"
    assert bp.score(_res("fell", []), S).code == "fell" and bp.score(_res("stopped", []), S).score is None
    over = [{"kind": "look", "ball": {"distance_in": 4, "bearing_deg": 15}}, {"kind": "act", "act": "align"}, {"kind": "look", "ball": {"distance_in": 4, "bearing_deg": -12}},
            {"kind": "act", "act": "align"}, {"kind": "look", "ball": {"distance_in": 4, "bearing_deg": 10}}]
    assert bp.score(_res("time", over), S).code == "align_overshoot"
    stuck = [{"kind": "look", "ball": {"distance_in": 4, "bearing_deg": 15}}, {"kind": "act", "act": "align"}, {"kind": "look", "ball": {"distance_in": 4, "bearing_deg": 15.5}},
             {"kind": "act", "act": "align"}, {"kind": "look", "ball": {"distance_in": 4, "bearing_deg": 15}}]
    assert bp.score(_res("time", stuck), S).code == "align_no_move"
    off = [{"kind": "act", "act": "punt", "at": (3.0, 10.0)}, {"kind": "after_punt", "ball": {"distance_in": 3.5, "bearing_deg": 9.0}}]
    assert bp.score(_res("punted", off), dict(S, punt_align_deg=12.0)).code == "missed_off_line"
    claw = [{"kind": "look", "ball": None}, {"kind": "claw_seen", "distance_in": 25.0}]
    assert bp.score(_res("time", claw), S).numbers["found_by"] == "claw look"


def test_every_diagnosis_knob_exists_and_every_free_knob_is_named_by_some_outcome():
    knobs = {k.name: k for k in ball_punt.BallPunt().knobs()}
    named = set()
    for code, items in ball_punt.DIAGNOSIS.items():
        for name, _d in items:
            assert name in knobs, (code, name)
            named.add(name)
    unused = [n for n, k in knobs.items() if k.control == "free" and n not in named]
    assert not unused, f"free but no outcome changes them (make them fixed or add a diagnosis): {unused}"


# ------------------------------------------------------------------------------------------------- search moves and the claw look

def reading(d, b):
    from pi_pipeline.vision.ball_finder import BallReading
    return BallReading(120, 110, 400, 20, 20, 20.0, float(d), float(b), False)


def test_the_search_orders_match_the_settings_names():
    from pi_pipeline.behavior import punt_settings as ps
    assert set(bc.SEARCH_ORDERS) == set(ps.SEARCH_ORDER_NAMES)


def test_the_default_search_starts_with_a_claw_look_then_turns_between_claw_looks():
    p = bc.ChasePlanner()                                                       # the ball not seen yet this attempt
    kinds = [p.decide(None).kind for _ in range(2 + 5)]
    assert kinds[:2] == ["look", "look"] and kinds[2:] == ["claw_look", "search_turn", "claw_look", "search_turn", "claw_look"]
    assert p.claw_side == 1


def test_once_the_ball_was_seen_only_straight_pictures_never_a_claw_look():
    p = bc.ChasePlanner()
    p.decide(reading(20, 30))                                                   # seen once (user, 2026-11-01: from then on straight pictures only)
    kinds = [p.decide(None).kind for _ in range(2 + 5)]
    assert "claw_look" not in kinds and kinds[:3] == ["look", "look", "search_turn"]


def test_back_up_moves_stop_at_the_attempt_budget():
    bc.SEARCH_ORDER, bc.BACK_UP_S, bc.BACK_BUDGET_S = "back_and_turn", 2.0, 4.0
    p = bc.ChasePlanner(claw_ok=False)
    p.decide(reading(20, 30))
    kinds = [p.decide(None).kind for _ in range(2 + 6)][2:]
    assert kinds.count("search_back") == 2 and kinds[:4] == ["search_back", "search_turn", "search_back", "search_turn"] and p.back_s == 4.0
    bc.BACK_BUDGET_S = 0.0
    q = bc.ChasePlanner(claw_ok=False)
    q.decide(reading(20, 30))
    assert "search_back" not in [q.decide(None).kind for _ in range(8)]


def test_a_vanished_ball_can_be_backed_away_from_instead_of_punted():
    bc.WHEN_VANISHED = "back_up"
    p = bc.ChasePlanner()
    p.decide(reading(5, 0))
    a = p.decide(None)
    assert a.kind == "back" and a.seconds == bc.VANISH_BACK_S


def test_walks_and_turns_are_timed_from_the_measured_pace(tmp_path):
    from pi_pipeline.behavior.chase_pace import PaceBook
    book = PaceBook("k", str(tmp_path / "pace.json"))
    slow = bc.ChasePlanner(pace=book).decide(reading(10, 0)).seconds
    for _ in range(3):
        book.record_walk(reading(14, 0), reading(6, 0), 2.0)            # 8 in over 1 s of moving: 8 in a second
    fast = bc.ChasePlanner(pace=book).decide(reading(10, 0)).seconds
    assert fast < slow and book.walk_in_s() > 6
    assert book.record_walk(reading(10, 0), reading(12, 0), 2.0) is None           # pushed (farther after the walk): not a pace
    for _ in range(2):
        book.record_turn(reading(12, 20), reading(12, 8), 20.0, 1.0)              # a right pulse swung the ball 12 deg left: 12 deg/s
    assert book.turn_deg_s(1, True) > 8 and book.turn_deg_s(-1, True) == 4.0        # per side: left is still the default
    assert json.load(open(tmp_path / "pace.json"))["k"]["walk_in_s"]["n"] == 3      # kept on disk


def test_close_and_off_line_he_lines_up_with_small_turns_then_punches_or_backs_up():
    bc.PUNT_ALIGN_DEG, bc.ALIGN_TRIES = 6.0, 2
    p = bc.ChasePlanner()
    a = p.decide(reading(3.5, 15))
    assert a.kind == "align" and a.degrees == 15 and bc.ALIGN_PULSE_MIN_S <= a.seconds <= bc.ALIGN_PULSE_MAX_S
    assert p.decide(reading(3.5, -9)).kind == "align"
    assert p.decide(reading(3.5, 8)).kind == "punt"                                  # two tries used: punch anyway (the default)
    bc.WHEN_MISALIGNED = "back_up"
    q = bc.ChasePlanner()
    q.decide(reading(3.5, 15)); q.decide(reading(3.5, 15))
    assert q.decide(reading(3.5, 15)).kind == "back"
    assert bc.ChasePlanner().decide(reading(3.5, 4)).kind == "punt"                  # lined up: no turn


class ClawRobot:
    def __init__(self):
        self.moves = []
    def _do(self, what):
        self.moves.append(what)
        return "ok"
    def walk(self, s): return self._do(("walk", round(s, 1)))
    def turn(self, d, s): return self._do(("turn", round(d)))
    def back(self, s): return self._do(("back", round(s, 1)))
    def punt(self): return self._do(("punt",))
    def claw_pose(self, pan, lift): return self._do(("claw", round(pan), round(lift)))
    def battery_ok(self): return True


def test_a_claw_look_takes_two_pictures_and_turns_g2_toward_the_ball_by_the_cameras_real_turn():
    bc.CLAW_PAN_DEG, bc.CLAW_LIFT_DEG, bc.CLAW_PAN_SIGN, bc.LOST_LOOKS = 35.0, 15.0, "right", 1
    none = picture()
    ahead_in_picture = picture([disc(120, 110, 12)])                     # straight ahead in the camera's picture, which is pointed about 39 deg left (pan -35)
    cam = FakeCamera([none, none, ahead_in_picture, ahead_in_picture, ahead_in_picture])
    robot, trace = ClawRobot(), []
    bc.run_chase(robot, cam, lambda: False, max_steps=3, sleep=lambda s: None, say=lambda m: None, trace=trace)
    claws = [m for m in robot.moves if m[0] == "claw"]
    assert claws[:5] == [("claw", 0, 15), ("claw", 35, 15), ("claw", -35, 15), ("claw", 0, 15), ("claw", 0, 0)]       # raised first, two pictures, centre still raised, then lowered
    turns = [m for m in robot.moves if m[0] == "turn"]
    assert turns and turns[-1][1] < -20                                                  # it turned left, toward the ball
    assert any(e.get("kind") == "claw_seen" for e in trace)


def test_the_pan_sign_is_read_from_how_the_ball_moved_in_the_picture():
    from pi_pipeline.behavior.claw_look import pan_sign_from
    assert pan_sign_from(0.0, -18.0) == "right" and pan_sign_from(1.0, 19.0) == "left" and pan_sign_from(0.0, 2.0) is None


def test_the_serial_robot_moves_only_the_arm_for_a_claw_look_within_its_limits():
    sent = []

    class Link:
        def send(self, c, **kw): sent.append(c)
        def poll_imu(self): return []
    r = bc.SerialRobot(Link(), sleep=lambda s: None)
    assert r.claw_pose(90, 70) == "ok"
    moves = [c for c in sent if c.startswith("i")]
    assert moves[-1] == "i0 45 1 40" and all(c.split()[0] == "i0" and len(c.split()) == 4 for c in moves)    # pan clamped to 45, lift to 40, no leg joints
    assert len(moves) >= int(45 / bc.CLAW_DEG_S * bc.CLAW_STEPS_PER_S)                                       # at most CLAW_DEG_S


# ------------------------------------------------------------------------------------------------- a whole session

class FakeApproach:
    name = "fake"
    diagnosis = {"bad": [("a", -1)]}
    stage_of = {}

    def __init__(self, outcomes, battery=None):
        self.outcomes, self.battery, self.ran, self.opened, self.closed = list(outcomes), battery or [], [], 0, 0
    def knobs(self): return [Knob("a", "float", lo=1.0, hi=5.0, step=1.0, label="a at")]
    def base_settings(self): return {"a": 3.0}
    def conditions(self): return {}
    def open(self): self.opened += 1
    def close(self): self.closed += 1
    def battery_ok(self, min_pct):
        ok = self.battery.pop(0) if self.battery else True
        return ok, "battery ok" if ok else "battery 20%"
    def run_attempt(self, settings, ctx):
        self.ran.append(dict(settings))
        return AttemptResult("done", 1.0, [])
    def score(self, result, settings):
        return self.outcomes.pop(0)


class Mem:
    def __init__(self): self.facts = []
    def add_fact(self, text, importance=3, core=False, source="told"):
        self.facts.append((text, importance, core, source)); return True


def _session(tmp_path, approach, attempts=4, **kw):
    g = Goal("g", "The test goal", "fake", attempts=attempts, rest_between_s=0)
    mem = Mem()
    s = GoalSession(g, approach, journal=Journal(str(tmp_path / "j.jsonl")), state=State(str(tmp_path / "s.json")), say=lambda m: None, conditions={"attachment": "arm", "floor": "hardwood"},
                    sleep=lambda s: None, memory_store=mem, **kw)
    return s, mem


def test_a_session_learns_writes_everything_and_saves_lessons(tmp_path):
    ap = FakeApproach([oc("bad", 0.2)] * 3 + [oc("hit", 0.9, True)] * 5)
    real_score = ap.score
    ap.score = lambda result, settings: (oc("hit", 0.9, True) if settings["a"] <= 2.0 else oc("bad", 0.2)) if ap.outcomes and ap.outcomes.pop(0) else real_score(result, settings)
    s, mem = _session(tmp_path, ap, attempts=8, rng=random.Random(3))
    out = s.run()
    used = [r["a"] for r in ap.ran]
    assert used[0] == 3.0 and 2.0 in used                                                       # misses at 3 sent him to try 2
    assert out["attempts"] == 8 and ap.opened == 1 and ap.closed == 1
    rows = Journal(str(tmp_path / "j.jsonl")).sessions("g")
    assert len(rows) == 1 and len(rows[0]["attempts"]) == 8 and rows[0]["end"]["why"] == "attempts"
    assert any(d["action"] == "kept" and d["new"] == 2.0 for d in rows[0]["decisions"])
    st = json.load(open(tmp_path / "s.json"))
    assert st["g"]["attachment=arm|floor=hardwood"]["values"]["a"]["2.0"]["hits"] >= 2
    assert mem.facts and all(f[3] == "goal_lesson" and f[1] == 2 and not f[2] for f in mem.facts) and mem.facts[0][0].startswith("The test goal:")
    s2, _ = _session(tmp_path, FakeApproach([oc("hit", 0.9, True)]), attempts=1)               # the next session starts from his best value
    s2.run()
    assert s2.approach.ran[0]["a"] == 2.0


def test_the_users_overrides_reach_the_session(tmp_path, monkeypatch):
    from pi_pipeline.goals import overrides as ovr
    ovr.set_pin("g", "a", 5.0, "floor=hardwood")
    ap = FakeApproach([oc("bad", 0.2)] * 3)
    s, _ = _session(tmp_path, ap, attempts=3)
    s.run()
    assert [r["a"] for r in ap.ran] == [5.0, 5.0, 5.0]
    assert ovr.for_conditions("g", "attachment=arm|floor=tile")["pins"] == {}                   # another floor: not pinned


def test_a_fall_or_a_low_battery_ends_the_session(tmp_path):
    ap = FakeApproach([oc("bad", 0.2), Outcome("fell", 0.0, False, "I fell"), oc("hit", 1, True)])
    s, _ = _session(tmp_path, ap)
    assert s.run()["why"] == "fell" and len(ap.ran) == 2 and ap.closed == 1
    ap = FakeApproach([oc("hit", 1, True)] * 4, battery=[True, False])
    s, _ = _session(tmp_path, ap)
    assert s.run()["why"] == "battery" and len(ap.ran) == 1


def test_a_session_stops_on_the_flag_and_at_its_target(tmp_path):
    ap = FakeApproach([oc("hit", 1, True)] * 4)
    s, _ = _session(tmp_path, ap, stop=lambda: True)
    assert s.run()["why"] == "stopped" and not ap.ran
    ap = FakeApproach([oc("hit", 1, True)] * 4)
    g = Goal("g", "T", "fake", attempts=4, target_successes=2, rest_between_s=0)
    out = GoalSession(g, ap, journal=Journal(str(tmp_path / "j2.jsonl")), state=State(str(tmp_path / "s2.json")), say=lambda m: None, conditions={}, sleep=lambda s: None, save_memory=False).run()
    assert out["why"] == "target" and len(ap.ran) == 2


def test_the_ball_punt_approach_runs_one_attempt_on_fakes():
    bc.LOST_LOOKS = 1
    cam = FakeCamera([picture([disc(122, 110, 50)]), picture([disc(122, 60, 6)])])           # close and straight ahead, then (after the punt) far away
    bp = ball_punt.BallPunt(robot=ClawRobot(), camera=cam)
    import pi_pipeline.behavior.ball_chase as chase_mod
    chase_mod.time  # noqa: B018
    settings = dict(bp.base_settings(), max_seconds=30.0)
    from pi_pipeline.goals.approach import AttemptContext
    res = bp.run_attempt(settings, AttemptContext(say=lambda m: None))
    o = bp.score(res, settings)
    assert res.ended == "punted" and o.code == "hit" and o.success


def test_lessons_are_the_kept_then_undone_changes():
    ds = [{"action": "try", "note": "t"}, {"action": "undo", "note": "u"}, {"action": "kept", "note": "k"}]
    assert lessons_from(ds, "Punt") == ["Punt: k", "Punt: u"]


# ------------------------------------------------------------------------------------------------- voice start, hand-over, report

def test_the_goal_phrases_start_a_goal_and_punt_still_punts():
    from pi_pipeline.voice.commands import goal_for_text, match_local_command as mlc
    for p in ("ball goal", "punt goal", "start the ball goal", "ball goal please", "goal attempt"):
        assert mlc(p) == "goal", p
        assert goal_for_text(p).id == "ball_punt"
    assert mlc("punt") == "punt" and mlc("what is the goal of football and why do people love it") != "goal"


def test_the_voice_loop_names_the_goal_and_asks_for_the_hand_over(monkeypatch):
    from pi_pipeline.tests.test_voice_loop import _loop, _run
    monkeypatch.setattr("pi_pipeline.attachments.current", lambda: "arm")
    events = []
    lp, w, stt, conv, tts = _loop(["ball goal"], on_event=lambda **kw: events.append(kw))
    _run(lp, 1)
    assert tts.said[0].startswith("Starting the goal") and any(e.get("arm_goal") == "ball_punt" for e in events)


def test_the_goal_unit_stops_voice_runs_the_session_and_always_rests_then_restarts_voice():
    from pi_pipeline import goal_launch
    c = goal_launch.command("ball_punt", python="/py", workdir="/w", user="pi")
    joined = " ".join(c)
    assert "--unit=g2-goal" in joined and "ExecStartPre=+/bin/systemctl stop g2-voice" in joined and "krest" in joined and "start g2-voice" in joined
    assert c[-4:] == ["-m", "pi_pipeline.goals", "run", "ball_punt"]
    assert goal_launch.launch("ball_punt", platform="darwin") is False
    calls = []

    class R:
        def __init__(self, rc): self.returncode = rc
    assert goal_launch.launch("ball_punt", platform="linux", run=lambda cmd, **kw: calls.append(cmd) or R(0)) is False      # something already running
    calls.clear()
    assert goal_launch.launch("ball_punt", platform="linux", run=lambda cmd, **kw: calls.append(cmd) or R(3)) is True and calls[-1][:2] == ["sudo", "-n"]


class PuntLikeApproach(FakeApproach):
    """A fake with the real punch-distance setting, so the report can name it through the real approach: hits only from 3.5 in or closer."""
    diagnosis = {"missed": [("punt_max_in", -1)]}

    def knobs(self): return [Knob("punt_max_in", "float", lo=1.0, hi=10.0, step=0.25, label="punching from", unit="in")]
    def base_settings(self): return {"punt_max_in": 4.0}
    def score(self, result, settings):
        ok = settings["punt_max_in"] <= 3.5
        return Outcome("hit" if ok else "missed", 0.9 if ok else 0.2, ok, "hit" if ok else "missed")


def test_the_report_shows_the_record_what_he_kept_and_your_overrides(tmp_path):
    from pi_pipeline.goals import overrides as ovr
    from pi_pipeline.goals.report import goal_page, text_history
    g = Goal("ball_punt", "Punt the ball", "ball_punt", attempts=10, rest_between_s=0)
    GoalSession(g, PuntLikeApproach([]), journal=Journal(str(tmp_path / "j.jsonl")), state=State(str(tmp_path / "s.json")), say=lambda m: None,
                conditions={"attachment": "arm", "floor": "hardwood"}, sleep=lambda s: None, save_memory=False, rng=random.Random(1)).run()
    ovr.set_limit("ball_punt", "punt_max_in", 2.5, 4.5)
    Journal(str(tmp_path / "j.jsonl")).write("override", goal="ball_punt", action="limit", knob="punt_max_in", scope="all", detail="limited punt_max_in to 2.5 to 4.5 (all)")
    page = goal_page("ball_punt", Journal(str(tmp_path / "j.jsonl")), State(str(tmp_path / "s.json")))
    assert "<svg" in page and "Sessions" in page and "prefers-color-scheme" in page
    assert "The record behind each setting" in page and "of" in page and "What he kept" in page and "works best so far" in page
    assert "Your overrides" in page and "limited punt_max_in to 2.5 to 4.5" in page
    assert "Next:" in text_history("ball_punt", Journal(str(tmp_path / "j.jsonl"))) or "Same again" in text_history("ball_punt", Journal(str(tmp_path / "j.jsonl")))


def test_the_new_punt_settings_are_checked_like_the_others(tmp_path):
    import sys

    from pi_pipeline.behavior import punt_settings as ps
    me = sys.modules[bc.__name__]
    p = tmp_path / "ps.json"
    p.write_text(json.dumps({"search_order": "back_turn", "align_tries": 5, "claw_look_lift_deg": 20, "when_vanished": "fly", "claw_pan_sign": "left"}))
    eff, problems = ps.effective(me, str(p))
    assert bc.SEARCH_ORDER == "back_turn" and bc.ALIGN_TRIES == 5 and bc.CLAW_LIFT_DEG == 20 and bc.CLAW_PAN_SIGN == "left"
    assert len(problems) == 1 and "when_vanished" in problems[0] and bc.WHEN_VANISHED == "punt"
    assert ps.set_value(me, "search_order", "claw_scan", str(p)) and json.load(open(p))["search_order"] == "claw_scan"
    with pytest.raises(ValueError):
        ps.set_value(me, "when_misaligned", "hop", str(p))


# ------------------------------------------------------------------------------------------------- spoken suggestions

def _state_with_suggestion(tmp_path, knob="punch_lunge_s", new=0.1, old=0.12):
    st = State(str(tmp_path / "state.json"))
    st.for_goal("ball_punt", "attachment=arm|floor=hardwood").update(count=5, suggestions={knob: {"new": new, "old": old, "because": "I punched from 3 in but the ball only went 4 in", "evidence": [5], "status": "new"}})
    st.save()
    return st


def test_an_answer_is_confirm_cancel_or_review_and_silence_is_review():
    from pi_pipeline.goals.suggestions import parse_answer
    assert parse_answer("confirm") == "confirm" and parse_answer("yes please") == "confirm" and parse_answer("G2 confirm") == "confirm"
    assert parse_answer("cancel") == "cancel" and parse_answer("okay cancel it") == "cancel" and parse_answer("no") == "cancel"
    assert parse_answer("review") == "later" and parse_answer("review it later") == "later" and parse_answer("") == "later" and parse_answer("hmm what") == "later"


def test_a_confirmed_suggestion_goes_into_the_users_settings(tmp_path):
    from pi_pipeline.goals import suggestions
    st = _state_with_suggestion(tmp_path)
    said = []
    n = suggestions.offer(said.append, lambda t: "confirm", state=st, journal=Journal(str(tmp_path / "j.jsonl")))
    assert n == 1 and "a lunge time of 0.1 s instead of 0.12 s" in said[0] and "confirm, cancel, or review" in said[0] and said[1].startswith("Done")
    assert json.load(open(tmp_path / "punt_settings.json"))["punch_lunge_s"] == 0.1
    assert not State(str(tmp_path / "state.json")).data["ball_punt"]["attachment=arm|floor=hardwood"]["suggestions"]
    assert any(r["kind"] == "suggestion" and r["answer"] == "confirm" for r in Journal(str(tmp_path / "j.jsonl")).read())


def test_silence_keeps_it_for_review_and_it_is_not_asked_again_and_cancel_is_not_suggested_again(tmp_path):
    from pi_pipeline.goals import suggestions
    st = _state_with_suggestion(tmp_path)
    said = []
    suggestions.offer(said.append, lambda t: "", state=st, journal=Journal(str(tmp_path / "j.jsonl")))
    assert "report" in said[-1] and not (tmp_path / "punt_settings.json").exists()
    assert suggestions.offer(said.append, lambda t: "confirm", state=State(str(tmp_path / "state.json"))) == 0         # review: not said again
    assert suggestions.pending(State(str(tmp_path / "state.json")), statuses=("later",))
    st = _state_with_suggestion(tmp_path)
    suggestions.offer(lambda m: None, lambda t: "cancel", state=st, journal=Journal(str(tmp_path / "j.jsonl")))
    row = State(str(tmp_path / "state.json")).data["ball_punt"]["attachment=arm|floor=hardwood"]
    assert not row["suggestions"] and "0.1" in row["banned"]["punch_lunge_s"]


def test_the_voice_service_says_the_suggestion_when_it_starts(tmp_path):
    from pi_pipeline.tests.test_voice_loop import _loop
    _state_with_suggestion(tmp_path)
    lp, w, stt, conv, tts = _loop(["review"])
    assert lp._offer_goal_suggestions() == 1 and "suggestion" in tts.said[0] and w.calls == 0          # no wake word needed for the answer


# ------------------------------------------------------------------------------------------------- the user's overrides from g2goal

def test_pin_limit_undo_and_forget_from_the_command_line(tmp_path, capsys):
    from pi_pipeline.goals import overrides as ovr
    from pi_pipeline.goals.__main__ import main
    cond = "attachment=arm|floor=hardwood"
    st = State(str(tmp_path / "state.json"))
    st.for_goal("ball_punt", cond).update(count=6, values={"punt_max_in": {"3.5": {"v": 3.5, "n": 4, "hits": 4, "sum": 3.6, "down": 0, "up": 0, "last": 6},
                                                                          "4.0": {"v": 4.0, "n": 2, "hits": 0, "sum": 0.4, "down": 2, "up": 0, "last": 2},
                                                                          "3.25": {"v": 3.25, "n": 2, "hits": 1, "sum": 1.1, "down": 0, "up": 0, "last": 4}}})
    st.save()
    main(["pin", "ball_punt", "lost_looks", "4", "--floor", "tile"])
    assert ovr.for_conditions("ball_punt", "attachment=arm|floor=tile")["pins"] == {"lost_looks": 4} and ovr.for_conditions("ball_punt", cond)["pins"] == {}
    main(["unpin", "ball_punt", "lost_looks", "--floor", "tile"])
    assert ovr.for_conditions("ball_punt", "attachment=arm|floor=tile")["pins"] == {}
    main(["limit", "ball_punt", "punt_max_in", "4.5", "2.5"])
    assert ovr.for_conditions("ball_punt", cond)["limits"]["punt_max_in"] == [2.5, 4.5]
    main(["undo", "ball_punt", "punt_max_in"])
    out = capsys.readouterr().out
    assert "3.5 in banned" in out and "next best 3.25 in" in out and "3.5" in ovr.for_conditions("ball_punt", cond)["banned"]["punt_max_in"]
    main(["forget", "ball_punt", "punt_max_in"])
    assert "punt_max_in" not in State(str(tmp_path / "state.json")).data["ball_punt"][cond]["values"]
    main(["overrides", "ball_punt"])
    assert "limited punt_max_in" in capsys.readouterr().out
    kinds = [r["action"] for r in Journal(str(tmp_path / "journal.jsonl")).read() if r["kind"] == "override"]
    assert kinds == ["pin", "unpin", "limit", "undo", "forget"]
    with pytest.raises(SystemExit):
        main(["pin", "ball_punt", "nope", "1"])                                                    # an unknown setting is refused
    with pytest.raises(SystemExit):
        main(["pin", "ball_punt", "punt_max_in", "99"])                                           # out of its range: refused, nothing changed
    with pytest.raises(SystemExit):
        main(["limit", "ball_punt", "search_order", "1", "2"])                                    # a choice setting has no range


# ------------------------------------------------------------------------------------------------- learning upgrades (2026-10-31)

def _shift_world(a, best, rng):
    if rng.random() < max(0.05, 0.8 - 0.15 * abs(a - best) / 0.25):
        return Outcome("hit", 0.9, True, "hit", stages={"punch": 0.9})
    code = "missed" if a > best else ("never_punted" if a < best else rng.choice(["missed", "never_punted"]))
    if rng.random() < 0.1:
        code = "never_punted" if code == "missed" else "missed"
    return Outcome(code, 0.2, False, code, stages={"punch": 0.2} if code == "missed" else {})


def test_after_a_hardware_change_fresh_records_follow_the_new_best_in_a_made_up_world():
    """The best moves from 3 to 3.75 in with the hardware (ARM2's parts, say). New records, starting from the old best values, follow it; old records would hold him."""
    rng = random.Random(11)
    near_new = 0
    for _ in range(300):
        j = Judge(PK, PDIAG, rng=rng, stage_of={"punt_max_in": "punch"})
        base = {"punt_max_in": 4.0}
        j.begin_session(base)
        for n in range(1, 31):
            a = j.settings(base)["punt_max_in"]
            j.update(n, _shift_world(a, 3.0, rng), {"punt_max_in": a})
        old_best = j.best("punt_max_in", 4.0)
        k = Judge(PK, PDIAG, rng=rng, stage_of={"punt_max_in": "punch"})            # the new hardware epoch: no records
        k.begin_session(base, prior={"punt_max_in": old_best}, prior_from="hw=old")
        assert k.settings(base)["punt_max_in"] == old_best and k.started_from == "hw=old"
        for n in range(1, 31):
            a = k.settings(base)["punt_max_in"]
            k.update(n, _shift_world(a, 3.75, rng), {"punt_max_in": a})
        near_new += abs(k.best("punt_max_in", old_best) - 3.75) <= 0.26
    assert near_new / 300 >= 0.55, near_new / 300


def test_a_new_floor_or_hardware_starts_from_his_best_elsewhere(tmp_path):
    st = State(str(tmp_path / "s.json"))
    st.for_goal("g", "attachment=arm|floor=hardwood|hw=hw-old").update(count=8, updated=100.0, values={"a": {"2.0": {"v": 2.0, "n": 5, "hits": 4, "sum": 3.8, "down": 0, "up": 0, "last": 8, "recent": [1, 1]},
                                                                                                  "3.0": {"v": 3.0, "n": 3, "hits": 0, "sum": 0.6, "down": 3, "up": 0, "last": 3, "recent": [0]}}})
    st.save()
    ap = FakeApproach([oc("hit", 0.9, True)])
    g = Goal("g", "T", "fake", attempts=1, rest_between_s=0)
    s = GoalSession(g, ap, journal=Journal(str(tmp_path / "j.jsonl")), state=State(str(tmp_path / "s.json")), say=lambda m: None,
                    conditions={"attachment": "arm", "floor": "hardwood", "hw": "hw-new"}, sleep=lambda s: None, save_memory=False)
    s.run()
    assert ap.ran[0]["a"] == 2.0                                                           # his best under the old hardware, not your 3.0
    start = Journal(str(tmp_path / "j.jsonl")).sessions("g")[0]["start"]
    assert start["started_from"] == "attachment=arm|floor=hardwood|hw=hw-old"
    new = State(str(tmp_path / "s.json")).data["g"]["attachment=arm|floor=hardwood|hw=hw-new"]
    assert new["values"]["a"]["2.0"]["n"] == 1                                            # fresh records: the old ones did not come along


def test_a_settled_setting_is_left_alone_and_the_focus_moves_on():
    j = J()
    j.begin_session(BASE)
    recs = {"2.0": (4, 4), "3.0": (6, 6), "4.0": (4, 0)}
    for key, (n, h) in recs.items():
        j.state["values"].setdefault("a", {})[key] = {"v": float(key), "n": n, "hits": h, "sum": h * 0.9, "down": 0, "up": 0, "last": 1, "recent": [1] * min(h, 6)}
    j.state["values"]["a"]["2.0"]["hits"] = 1
    j.state["current"]["a"] = 3.0
    d = j.update(20, oc("bad", 0.2), dict(BASE, a=3.0))                                   # "bad" points at a, but a has settled at 3.0
    assert "a" in j.state["settled"] and any(x.action == "kept" and "settled" in x.note for x in d) and j.state["focus"] != "a"
    assert j.settings(BASE)["a"] == 3.0
    for n in range(21, 25):                                                                # its best starts failing: no longer settled
        j.update(n, oc("bad", 0.2), dict(BASE, a=3.0))
    assert "a" not in j.state["settled"]


def test_a_plain_punt_adds_to_the_records_without_changing_anything(tmp_path):
    from pi_pipeline.goals.observe import plain_punt
    st = State(str(tmp_path / "s.json"))
    tr = [{"kind": "look", "ball": {"distance_in": 12, "bearing_deg": 0}, "t": 1}, {"kind": "act", "act": "punt", "at": (3.0, 0.0)},
          {"kind": "after_punt", "ball": {"distance_in": 20.0, "bearing_deg": 0.0}}]
    settings = dict(ball_punt.BallPunt().base_settings())
    cond = {"attachment": "arm", "floor": "hardwood", "hw": "hw-x"}
    said = plain_punt(tr, "punted", 20.0, settings, 77, state=st, journal=Journal(str(tmp_path / "j.jsonl")), conditions=cond)
    assert said and "went 17 in" in said
    rec = State(str(tmp_path / "s.json")).data["ball_punt"]["attachment=arm|floor=hardwood|hw=hw-x"]
    assert rec["count"] == 1 and rec["values"]["punt_max_in"]["4.0"]["hits"] == 1 and not rec.get("current", {}).get("punt_max_in", 4.0) != 4.0
    rows = Journal(str(tmp_path / "j.jsonl")).sessions("ball_punt")
    assert rows[0]["start"]["mode"] == "plain punt" and rows[0]["attempts"][0]["pack_pct"] == 77
    assert plain_punt([], "punted", 1.0, {}, state=None, journal=None, conditions=cond, goal_id="nope") is None      # never raises


def test_a_wrong_verdict_takes_the_attempt_out_and_right_puts_it_back(tmp_path, capsys):
    from pi_pipeline.goals.__main__ import main
    from pi_pipeline.goals.observe import plain_punt
    cond = {"attachment": "arm", "floor": "hardwood", "hw": "hw-x"}
    tr = [{"kind": "act", "act": "punt", "at": (3.0, 0.0)}, {"kind": "after_punt", "ball": None}]
    settings = dict(ball_punt.BallPunt().base_settings())
    plain_punt(tr, "punted", 20.0, settings, state=State(str(tmp_path / "state.json")), journal=Journal(str(tmp_path / "journal.jsonl")), conditions=cond)
    key = "attachment=arm|floor=hardwood|hw=hw-x"
    assert State(str(tmp_path / "state.json")).data["ball_punt"][key]["values"]["punt_max_in"]["4.0"]["hits"] == 1     # "went out of sight" counted as a hit
    main(["verdict", "ball_punt", "1", "wrong", "--note", "it was under the claw"])
    assert "taken out" in capsys.readouterr().out
    rec = State(str(tmp_path / "state.json")).data["ball_punt"][key]
    assert rec["values"]["punt_max_in"]["4.0"]["n"] == 0 and rec["count"] == 0
    main(["verdict", "ball_punt", "1", "wrong"])                                                # twice: nothing more is taken out
    assert State(str(tmp_path / "state.json")).data["ball_punt"][key]["values"]["punt_max_in"]["4.0"]["n"] == 0
    main(["verdict", "ball_punt", "1", "right"])
    assert State(str(tmp_path / "state.json")).data["ball_punt"][key]["values"]["punt_max_in"]["4.0"]["n"] == 1
    from pi_pipeline.goals.report import goal_page
    page = goal_page("ball_punt", Journal(str(tmp_path / "journal.jsonl")), State(str(tmp_path / "state.json")))
    assert "your verdicts" in page and "1 right, 0 wrong" in page and "Plain punt" in page


def test_the_pace_book_starts_new_hardware_from_the_nearest_measured_values(tmp_path):
    from pi_pipeline.behavior.chase_pace import MIN_SAMPLES, PaceBook
    p = str(tmp_path / "pace.json")
    old = PaceBook("attachment=arm|floor=hardwood|hw=a", p)
    for _ in range(5):
        old.record_walk(reading(14, 0), reading(6, 0), 2.0)
    new = PaceBook("attachment=arm|floor=hardwood|hw=b", p, fallback=["attachment=arm|floor=hardwood|hw=a"])
    assert abs(new.walk_in_s() - old.walk_in_s()) < 1e-6 and new.data["walk_in_s"]["n"] == MIN_SAMPLES and new.data["walk_in_s"]["from"].endswith("hw=a")
    new.record_walk(reading(14, 0), reading(12, 0), 2.0)                                   # its own samples take over
    assert new.walk_in_s() < old.walk_in_s()


def test_the_conditions_include_the_hardware_epoch():
    from pi_pipeline.goals.journal import current_conditions, prior_conditions
    c = current_conditions()
    assert set(c) >= {"attachment", "floor", "hw"}
    gs = {"attachment=arm|floor=tile|hw=h2": {"count": 3, "updated": 5}, "attachment=arm|floor=hardwood|hw=h1": {"count": 3, "updated": 1},
          "attachment=arm|floor=hardwood|hw=h0": {"count": 3, "updated": 9}, "attachment=none|floor=hardwood|hw=h2": {"count": 9}}
    order = prior_conditions(gs, {"attachment": "arm", "floor": "hardwood", "hw": "h2"})
    assert order == ["attachment=arm|floor=hardwood|hw=h0", "attachment=arm|floor=hardwood|hw=h1", "attachment=arm|floor=tile|hw=h2"]


# ------------------------------------------------------------------------------------------------- the walls standing goal, priority, practise (2026-10-31)

def test_wall_encounters_are_scored_from_the_events():
    from pi_pipeline.goals.walls import score_encounters
    ev = [{"t": 0.0, "kind": "steer", "nearest_in": 20.0}, {"t": 30.0, "kind": "steer", "nearest_in": 15.0}, {"t": 33.0, "kind": "hit"}, {"t": 34.0, "kind": "hit"},
          {"t": 60.0, "kind": "hit"}]
    codes = [o.code for o in score_encounters(ev)]
    assert codes == ["turned_early", "turned_but_hit", "bumped"]                             # 20 in was more careful than needed; the two touches 1 s apart are one bump
    assert score_encounters([{"t": 0.0, "kind": "steer", "nearest_in": 9.0}])[0].code == "turned_away"
    ch = [{"t": 0.0, "kind": "steer", "nearest_in": 10.0, "source": "chase"}, {"t": 20.0, "kind": "hit", "source": "chase"}, {"t": 40.0, "kind": "left_ball", "source": "chase"}]
    out = score_encounters(ch)
    assert [o.code for o in out] == ["chase_turned_away", "chase_bumped", "chase_left_ball"] and all(set(o.stages) == {"chase"} for o in out)
    assert not score_encounters(ch)[2].success and score_encounters(ch)[2].score < 0.5         # leaving a ball is a miss that votes for going closer


def test_the_exploration_tally_keeps_timed_wall_events_for_the_walls_goal():
    from pi_pipeline.goals.walls import events_from_diag
    from pi_pipeline.reflection.recap import SessionTally
    t = [0.0]
    tally = SessionTally(clock=lambda: t[0])
    tally.note("wall.steer", "wall ahead (14 in, 2 groups): turn left"); t[0] = 2.0
    tally.note("contact", "imu"); t[0] = 3.0
    tally.note("survey.start", "")
    ev = events_from_diag(tally.events)
    assert ev == [{"t": 0.0, "kind": "steer", "nearest_in": 14.0, "source": "explore"}, {"t": 2.0, "kind": "hit", "source": "explore"}] and tally.counts()["survey.start"] == 1


def test_the_walls_goal_learns_from_encounters_and_puts_its_values_into_the_code(tmp_path):
    from pi_pipeline import explore_session
    from pi_pipeline.behavior.driver import BehaviorDriver
    from pi_pipeline.goals import standing
    keep = (BehaviorDriver.WALL_STOP_IN, BehaviorDriver.WALL_TURN_RAD, BehaviorDriver.LEG_MARGIN_IN, explore_session.NEAR_LOOK_IN)
    try:
        cond = {"attachment": "arm", "floor": "hardwood", "hw": "h", "wallcal": "none"}
        used = standing.apply("walls", conditions=cond)
        assert used and used["wall_stop_in"] == keep[0] and abs(used["wall_turn_deg"] - math.degrees(keep[1])) < 0.2
        ev = [{"t": float(i * 20), "kind": "hit"} for i in range(4)]                         # four bumps, no turn away
        assert standing.learn("walls", ev, "exploration", used=used, conditions=cond) == 4
        rec = State().data["walls"]["attachment=arm|floor=hardwood|hw=h|wallcal=none"]
        assert rec["count"] == 4 and rec["focus"] == "wall_turn_in"                                # bumps point first at turning away sooner
        rows = Journal().sessions("walls")
        assert rows[0]["start"]["mode"] == "exploration" and len(rows[0]["attempts"]) == 4
        assert standing.learn("walls", [], "exploration", conditions=cond) == 0
    finally:
        BehaviorDriver.WALL_STOP_IN, BehaviorDriver.WALL_TURN_RAD, BehaviorDriver.LEG_MARGIN_IN, explore_session.NEAR_LOOK_IN = keep


import math  # noqa: E402


def test_while_chasing_walls_come_first(monkeypatch):
    monkeypatch.setattr(bc, "WALL_THREE_POINT", False)                                     # the plain wall turn is what this checks
    bc.CHASE_WALL_IN = 10.0
    p = bc.ChasePlanner()
    a = p.decide(reading(20, 0), bc.WallSeen(40.0, "left"))
    assert a.kind == "walk"
    a = p.decide(reading(20, 0), bc.WallSeen(8.0, "left"))                                  # he is within 10 in of a wall: turn away
    assert a.kind == "wall_turn" and a.degrees < 0
    q = bc.ChasePlanner()
    assert q.decide(reading(10, 0), bc.WallSeen(14.0, "right", 14.0)).kind == "look"         # the ball is 4 in from the wall behind it: look again first
    assert q.decide(reading(10, 0), bc.WallSeen(14.0, "right", 14.0)).kind == "give_up"     # ... then leave it
    side = bc.ChasePlanner()
    for _ in range(3):
        assert side.decide(reading(20, 0), bc.WallSeen(14.0, "right", None)).kind == "walk"  # a side wall at 14 in is not "behind the ball": walk on (the walk is capped by the loop)


def test_a_walk_is_cut_short_before_a_wall_and_a_ball_by_the_wall_ends_the_attempt_uncounted():
    bc.CHASE_WALL_IN, bc.LOST_LOOKS = 10.0, 1
    robot, trace = ClawRobot(), []
    cam = FakeCamera([picture([disc(120, 90, 6)])])                                          # the ball far ahead (about 27 in)
    bc.run_chase(robot, cam, lambda: False, max_steps=1, sleep=lambda s: None, say=lambda m: None, trace=trace,
                 wall_check=lambda jpeg, ball: bc.WallSeen(13.0, "left"))
    walks = [m for m in robot.moves if m[0] == "walk"]
    assert walks and walks[0][1] <= 1.0 + 3.0 / 4.2 + 0.05                                      # only 3 in of room before the 10 in limit
    robot, trace = ClawRobot(), []
    out = bc.run_chase(robot, FakeCamera([picture([disc(120, 110, 12)])]), lambda: False, max_steps=5, sleep=lambda s: None, say=lambda m: None, trace=trace,
                       wall_check=lambda jpeg, ball: bc.WallSeen(ball.distance_in + 3.0, "left", ball.distance_in + 3.0))
    assert out == "ball_by_wall" and not any(m[0] == "walk" for m in robot.moves)
    o = ball_punt.BallPunt().score(_res("ball_by_wall", trace), S)
    assert o.code == "ball_by_wall" and o.score is None                                       # not counted against the punt


def test_the_chase_wall_check_needs_walls_first_and_any_calibration(tmp_path, monkeypatch):
    from pi_pipeline.goals import walls
    monkeypatch.setattr(walls, "calibration_info", lambda: (None, None))
    assert walls.make_wall_check() is None
    monkeypatch.setattr(walls, "calibration_info", lambda: (object(), "2026-10-20 10:00:00"))
    monkeypatch.setattr(walls, "calibration_current", lambda when: False)
    assert callable(walls.make_wall_check())                                                  # an old calibration still works: he learns against the reading as it is
    spec.set_priority(["ball_punt", "walls"])
    assert walls.make_wall_check() is None                                                    # the punt ranked first: no wall limit in the chase


def test_a_calibration_counts_only_when_made_after_the_latest_hardware_change(monkeypatch):
    from pi_pipeline.goals import walls
    monkeypatch.setattr("pi_pipeline.telemetry.epochs.epoch_at", lambda when=None, path=None: {"id": "hw-x", "start": "2026-10-24T22:10"})
    assert walls.calibration_current("2026-10-25 09:00:00") and not walls.calibration_current("2026-10-20 09:00:00") and not walls.calibration_current(None)


def test_the_wall_reading_leaves_out_the_balls_own_columns(monkeypatch):
    from pi_pipeline.goals import walls
    from pi_pipeline.vision import wall_distance as wd
    monkeypatch.setattr(wd, "estimate", lambda img, cal: wd.WallEstimate(20.0, [None, None, 20.0, None, 80.0], False, "left", "x"))
    monkeypatch.setattr("pi_pipeline.vision.embedder.to_image", lambda j: j)
    ball = reading(8, 0)                                                                       # centred, 20 px wide: the middle column group
    seen = walls.wall_seen(b"jpeg", ball, object())
    assert seen.nearest_in == round(80.0 / wd.IN_TO_CM, 1) and seen.turn == "left"               # the 20 cm "wall" was the ball itself


def test_the_priority_order_defaults_to_walls_first_and_can_be_set():
    assert spec.priority()[:2] == ["walls", "ball_punt"] and spec.ranks_above("walls", "ball_punt")
    assert spec.set_priority(["ball_punt", "walls"])[:2] == ["ball_punt", "walls"] and not spec.ranks_above("walls", "ball_punt")
    assert spec.BUILTIN["walls"].kind == "standing" and spec.BUILTIN["ball_punt"].needs_attachment == "arm"


def test_practise_weighs_priority_need_and_what_is_possible_now(tmp_path):
    from pi_pipeline.goals.practice import choose, named_goal, score_goals
    j, st = Journal(str(tmp_path / "pj.jsonl")), State(str(tmp_path / "ps.json"))
    ch = score_goals(attachment="arm", ball_visible=True, journal=j, state=st)
    assert [c.goal.id for c in ch] == ["walls", "ball_punt"]                                 # nothing done yet: equal need, walls ranked first
    assert "haven't practised it here yet" in ch[0].sentence and "can see the ball" in ch[1].sentence
    assert [c.goal.id for c in score_goals(attachment="none", journal=j, state=st)] == ["walls"]     # the punt needs the arm
    g, said = choose("practise the ball", attachment="arm", ball_visible=False, journal=j, state=st)
    assert g.id == "ball_punt" and "find the ball first" in said
    g, said = choose("practise the ball", attachment="none", journal=j, state=st)
    assert g is None and "needs the arm" in said
    assert named_goal("practise walls").id == "walls" and named_goal("practise") is None


def test_practise_by_voice_starts_the_goal_or_a_walls_roam(monkeypatch):
    from pi_pipeline.tests.test_voice_loop import _loop, _run
    from pi_pipeline.voice.commands import match_local_command as mlc
    assert mlc("practise") == "practice" and mlc("practice the walls") == "practice" and mlc("lets practice") == "practice" and mlc("practise now") == "practice"
    assert mlc("practice makes perfect") != "practice" and mlc("practise the piano tonight") != "practice"           # a sentence, not a command
    assert mlc("punt") == "punt" and mlc("ball goal") == "goal"
    monkeypatch.setattr("pi_pipeline.attachments.current", lambda: "arm")
    events = []
    lp, w, stt, conv, tts = _loop(["practise walls"], on_event=lambda **kw: events.append(kw))
    _run(lp, 1)
    assert tts.said[0].startswith("I'll practise turning away from walls") and any(e.get("arm_explore") and e.get("roam_s") == 300.0 for e in events)
    events.clear()
    lp, w, stt, conv, tts = _loop(["practise the punt"], on_event=lambda **kw: events.append(kw))
    _run(lp, 1)
    assert any(e.get("arm_goal") == "ball_punt" for e in events)


def test_a_bump_while_chasing_stops_the_walk_and_is_recorded_for_the_walls_goal(monkeypatch):
    from pi_pipeline.gait import policy_walker
    from pi_pipeline.goals.walls import events_from_trace

    class BumpWalker:
        def __init__(self, link, **kw):
            self._on_contact = kw.get("on_contact"); self._on_fall = kw.get("on_fall"); self.n = 0; self.stopped = False
        @property
        def busy(self):
            self.n += 1
            if self.n == 2 and self._on_contact:
                self._on_contact({"kind": "contact"})
            return not self.stopped and self.n < 50
        def walk(self, seconds): self.n = 0; self.stopped = False
        def stop(self, rest=True): self.stopped = True
    monkeypatch.setattr(policy_walker, "PolicyWalker", BumpWalker)

    class Link:
        def send(self, c, **kw): pass
        def poll_imu(self): return []
    r = bc.SerialRobot(Link(), sleep=lambda s: None, clock=iter(np.arange(0, 100, 0.1)).__next__)
    assert r.walk(2.0) == "ok" and r.bumped and r._walker.stopped
    bc.LOST_LOOKS = 1
    trace = []

    class Bot(ClawRobot):
        bumped = False
        def walk(self, s):
            self.bumped = True
            return super().walk(s)
    bc.run_chase(Bot(), FakeCamera([picture([disc(120, 90, 6)])]), lambda: False, max_steps=1, sleep=lambda s: None, say=lambda m: None, trace=trace)
    assert [e["kind"] for e in events_from_trace(trace)] == ["hit"]


import numpy as np  # noqa: E402


def test_the_chase_wall_distance_settles_between_bumps_and_left_balls_in_a_made_up_world():
    """A made-up world: closer than 7 in to a wall he often bumps (the turn needs room); farther than 7 in he more and more often leaves balls that were reachable.
    Bumps push chase_wall_in out, left balls pull it in: it must settle near 7, from either side."""
    from pi_pipeline.goals import walls
    knobs = [Knob("chase_wall_in", "float", lo=4.0, hi=24.0, step=1.0)]
    finals = []
    rng = random.Random(3)
    for start in (4.0, 14.0):
        for _ in range(150):
            j = Judge(knobs, walls.DIAGNOSIS, rng=rng, stage_of=walls.STAGE_OF)
            base = {"chase_wall_in": start}
            j.begin_session(base)
            for n in range(1, 41):
                v = j.settings(base)["chase_wall_in"]
                r = rng.random()
                if v < 7.0 and r < 0.15 * (7.0 - v) + 0.1:
                    ev = [{"t": 0.0, "kind": "hit", "source": "chase"}]
                elif v > 7.0 and r < 0.1 * (v - 7.0) + 0.05:
                    ev = [{"t": 0.0, "kind": "left_ball", "source": "chase"}]
                else:
                    ev = [{"t": 0.0, "kind": "steer", "nearest_in": v, "source": "chase"}]
                o = walls.score_encounters(ev)[0]
                j.update(n, o, {"chase_wall_in": v})
            finals.append(j.best("chase_wall_in", start))
    near = sum(abs(f - 7.0) <= 1.01 for f in finals) / len(finals)
    assert near >= 0.7, near


def test_after_a_new_wall_calibration_the_settings_carry_over_to_the_same_real_distance():
    from pi_pipeline.goals.walls import translate
    from pi_pipeline.vision.wall_distance import IN_TO_CM
    old = [[0.30, 100.0], [0.60, 50.0], [0.90, 20.0]]
    new = [[0.30, 120.0], [0.60, 60.0], [0.90, 24.0]]                                          # the new calibration reads 20% farther for the same picture rows
    out = translate({"chase_wall_in": 50.0 / IN_TO_CM, "wall_turn_in": 20.0 / IN_TO_CM, "wall_turn_deg": 50.0}, old, new)
    assert abs(out["chase_wall_in"] - 60.0 / IN_TO_CM) < 0.15 and abs(out["wall_turn_in"] - 24.0 / IN_TO_CM) < 0.15 and out["wall_turn_deg"] == 50.0
    assert translate({"chase_wall_in": 8.0}, old, old) == {"chase_wall_in": 8.0} and translate({"chase_wall_in": 8.0}, None, new) == {"chase_wall_in": 8.0}


def test_a_new_calibration_starts_fresh_records_from_his_old_settings_carried_over(monkeypatch):
    from pi_pipeline import explore_session
    from pi_pipeline.behavior.driver import BehaviorDriver
    from pi_pipeline.goals import standing, walls
    from pi_pipeline.vision import wall_distance
    keep = (BehaviorDriver.WALL_STOP_IN, BehaviorDriver.WALL_TURN_RAD, BehaviorDriver.LEG_MARGIN_IN, explore_session.NEAR_LOOK_IN, wall_distance.TURN_IN, bc.CHASE_WALL_IN)
    try:
        old_pts, new_pts = [[0.3, 100.0], [0.6, 50.0], [0.9, 20.0]], [[0.3, 120.0], [0.6, 60.0], [0.9, 24.0]]
        cond_old = {"attachment": "arm", "floor": "hardwood", "hw": "h", "wallcal": "2026-10-25T10:00:00"}
        cond_new = dict(cond_old, wallcal="2026-11-02T10:00:00")
        monkeypatch.setattr(walls, "calibration_info", lambda: (wall_distance.Calibration([tuple(p) for p in old_pts]), "2026-10-25 10:00:00"))
        standing.apply("walls", conditions=cond_old)
        s0 = State()                                                                           # under the old calibration he learned to keep 12 in while chasing
        rec_old = s0.for_goal("walls", "attachment=arm|floor=hardwood|hw=h|wallcal=2026-10-25T10:00:00")
        rec_old["values"]["chase_wall_in"] = {"12.0": {"v": 12.0, "n": 6, "hits": 6, "sum": 6.0, "down": 0, "up": 0, "last": 6, "recent": [1] * 6}}
        rec_old["count"] = 6
        s0.save()
        monkeypatch.setattr(walls, "calibration_info", lambda: (wall_distance.Calibration([tuple(p) for p in new_pts]), "2026-11-02 10:00:00"))
        used = standing.apply("walls", conditions=cond_new)
        rec = State().data["walls"]["attachment=arm|floor=hardwood|hw=h|wallcal=2026-11-02T10:00:00"]
        assert abs(used["chase_wall_in"] - 14.4) < 0.3 and rec["started_from"].endswith("wallcal=2026-10-25T10:00:00")   # the same picture row, in the new inches
        assert not any(r["n"] for r in rec["values"].get("chase_wall_in", {}).values())                                   # fresh records
        assert rec["wallcal_points"] == new_pts
    finally:
        (BehaviorDriver.WALL_STOP_IN, BehaviorDriver.WALL_TURN_RAD, BehaviorDriver.LEG_MARGIN_IN, explore_session.NEAR_LOOK_IN, wall_distance.TURN_IN, bc.CHASE_WALL_IN) = keep


def test_every_free_walls_knob_is_named_by_some_outcome():
    from pi_pipeline.goals import walls
    knobs = {k.name: k for k in walls.Walls().knobs()}
    named = {n for items in walls.DIAGNOSIS.values() for n, _d in items}
    assert all(n in knobs for n in named)
    assert not [n for n, k in knobs.items() if k.control == "free" and n not in named]
    assert knobs["chase_wall_in"].lo == 4.0 and knobs["chase_wall_in"].control == "free"


# ------------------------------------------------------------------------------------------------- bug sweep (2026-10-31)

def test_two_open_states_do_not_erase_each_others_learning(tmp_path):
    p = str(tmp_path / "st.json")
    a, b = State(p), State(p)                       # a goal session's state, and the walls goal saving from inside an attempt
    a.for_goal("ball_punt", "c")["count"] = 3
    b.for_goal("walls", "c")["count"] = 7
    b.save()
    a.save()                                        # the session saves after the walls goal did: the walls record must survive
    data = json.load(open(p))
    assert data["ball_punt"]["c"]["count"] == 3 and data["walls"]["c"]["count"] == 7
    assert a.data["walls"]["c"]["count"] == 7       # and the session now sees it
    a.reset("ball_punt")
    assert "ball_punt" not in json.load(open(p)) and "walls" in json.load(open(p))


def test_attempt_numbers_are_never_reused_after_a_verdict(tmp_path, capsys):
    from pi_pipeline.goals.__main__ import main
    from pi_pipeline.goals.observe import plain_punt
    cond = {"attachment": "arm", "floor": "hardwood", "hw": "hw-x"}
    tr = [{"kind": "act", "act": "punt", "at": (3.0, 0.0)}, {"kind": "after_punt", "ball": None}]
    settings = dict(ball_punt.BallPunt().base_settings())
    for _ in range(2):
        plain_punt(tr, "punted", 20.0, settings, state=State(str(tmp_path / "state.json")), journal=Journal(str(tmp_path / "journal.jsonl")), conditions=cond)
    main(["verdict", "ball_punt", "2", "wrong"])
    plain_punt(tr, "punted", 20.0, settings, state=State(str(tmp_path / "state.json")), journal=Journal(str(tmp_path / "journal.jsonl")), conditions=cond)
    nums = [r["number"] for r in Journal(str(tmp_path / "journal.jsonl")).read() if r["kind"] == "attempt"]
    assert nums == [1, 2, 3]


def test_a_start_from_his_best_elsewhere_survives_a_short_first_session():
    j = J()
    j.begin_session(BASE, prior={"a": 2.0}, prior_from="elsewhere")
    j.update(1, oc("hit", 0.9, True), j.settings(BASE))                    # one attempt: no value has 2 yet
    j.finish(BASE, 1)
    assert j.begin_session(BASE)["a"] == 2.0                                # not back to your 3.0


def test_walls_that_keep_turning_him_away_from_the_ball_end_the_attempt_uncounted(monkeypatch):
    monkeypatch.setattr(bc, "WALL_THREE_POINT", False)
    bc.CHASE_WALL_IN = 10.0
    p = bc.ChasePlanner()
    kinds = [p.decide(reading(20, 0), bc.WallSeen(8.0, "left", None)).kind for _ in range(bc.WALL_TURNS_GIVE_UP)]
    assert kinds == ["wall_turn"] * (bc.WALL_TURNS_GIVE_UP - 1) + ["give_up"]


def test_after_a_bump_he_backs_off_and_the_walk_gives_no_pace_sample(tmp_path):
    from pi_pipeline.behavior.chase_pace import PaceBook
    bc.LOST_LOOKS = 1

    class Bot(ClawRobot):
        bumped = False
        def walk(self, s):
            self.bumped = True
            return super().walk(s)
    book = PaceBook("k", str(tmp_path / "p.json"))
    robot, trace = Bot(), []
    bc.run_chase(robot, FakeCamera([picture([disc(120, 90, 6)]), picture([disc(120, 110, 25)])]), lambda: False, max_steps=2, sleep=lambda s: None, say=lambda m: None, trace=trace, pace=book)
    assert [m[0] for m in robot.moves][:2] == ["walk", "back"] and not book.log


def test_no_picture_after_the_punt_is_not_counted_as_a_hit():
    tr = [{"kind": "act", "act": "punt", "at": (3.0, 0.0)}, {"kind": "after_punt", "ball": None, "picture": False}]
    o = ball_punt.BallPunt().score(_res("punted", tr), S)
    assert o.code == "punt_unseen_camera" and o.score is None


def test_a_ball_found_by_a_claw_look_scores_the_search_and_an_after_punt_look_is_not_a_search():
    bc.LOST_LOOKS, bc.CLAW_PAN_SIGN = 1, "right"
    none, far = picture(), picture([disc(120, 110, 12)])
    robot, trace = ClawRobot(), []
    bc.run_chase(robot, FakeCamera([none, far]), lambda: False, max_steps=2, sleep=lambda s: None, say=lambda m: None, trace=trace)
    seen = [e for e in trace if e.get("kind") == "claw_seen"]
    assert seen and "t" in seen[0]
    res = _res("time", trace, 30.0)
    o = ball_punt.BallPunt().score(res, S)
    assert o.numbers["found_by"] == "claw look" and o.stages["search"] > 0.5                    # found by the claw look, early: a good search
    tr = [{"kind": "look", "ball": {"distance_in": 12, "bearing_deg": 0}, "t": 1}, {"kind": "act", "act": "punt", "at": (3.0, 0.0)},
          {"kind": "claw_seen", "distance_in": 20.0, "after_punt": True, "t": 9}, {"kind": "after_punt", "ball": {"distance_in": 20.0, "bearing_deg": 30.0}, "picture": True}]
    assert ball_punt.BallPunt().score(_res("punted", tr), S).numbers["found_by"] == "straight look"


def test_the_wall_reading_says_what_lies_right_beside_the_ball(monkeypatch):
    from pi_pipeline.goals import walls
    from pi_pipeline.vision import wall_distance as wd
    monkeypatch.setattr(wd, "estimate", lambda img, cal: wd.WallEstimate(20.0, [90.0, 30.0, 20.0, None, 60.0], False, "left", "x"))
    monkeypatch.setattr("pi_pipeline.vision.embedder.to_image", lambda j: j)
    seen = walls.wall_seen(b"jpeg", reading(8, 0), object())                                    # the ball in the middle column group
    assert seen.near_ball_in == round(30.0 / wd.IN_TO_CM, 1) and seen.nearest_in == round(30.0 / wd.IN_TO_CM, 1)


def test_your_wall_values_stay_yours_after_he_applies_learned_ones():
    from pi_pipeline import explore_session
    from pi_pipeline.behavior import wall_settings as ws
    from pi_pipeline.behavior.driver import BehaviorDriver
    keep = (BehaviorDriver.WALL_STOP_IN, explore_session.NEAR_LOOK_IN)
    try:
        before = ws.defaults()
        ws.apply({"wall_stop_in": 26.0, "near_look_in": 45.0})
        assert BehaviorDriver.WALL_STOP_IN == 26.0 and ws.defaults() == before                 # the next exploration's "your values" are still the code's
    finally:
        BehaviorDriver.WALL_STOP_IN, explore_session.NEAR_LOOK_IN = keep


def test_a_goal_that_needs_the_arm_does_not_start_without_it(tmp_path, monkeypatch):
    from pi_pipeline.tests.test_voice_loop import _loop, _run
    monkeypatch.setattr("pi_pipeline.attachments.current", lambda: "head")
    events = []
    lp, w, stt, conv, tts = _loop(["ball goal"], on_event=lambda **kw: events.append(kw))
    _run(lp, 1)
    assert tts.said[0] == "I need the arm for that goal." and not any(e.get("arm_goal") for e in events)
    ap = FakeApproach([oc("hit", 1, True)])
    g = Goal("g", "T", "fake", attempts=1, rest_between_s=0, needs_attachment="arm")
    out = GoalSession(g, ap, journal=Journal(str(tmp_path / "j.jsonl")), state=State(str(tmp_path / "s.json")), say=lambda m: None, conditions={"attachment": "head"}, sleep=lambda s: None, save_memory=False).run()
    assert out["why"] == "needs the arm" and not ap.ran and ap.opened == 0


def test_the_claw_picture_test_takes_straight_then_plus_then_minus_and_saves_them(tmp_path):
    from pi_pipeline.behavior.claw_look import take_pictures
    robot, said = ClawRobot(), []
    robot.swing_deg = lambda: 2.5
    cam = FakeCamera([b"one", b"two", b"three"])
    res = take_pictures(robot, cam, str(tmp_path / "pics"), pan=35.0, lift=15.0, say=said.append, sleep=lambda s: None)
    assert [r[0] for r in res] == ["straight", "pan_plus", "pan_minus"] and [m for m in robot.moves if m[0] == "claw"] == [("claw", 0, 15), ("claw", 35, 15), ("claw", -35, 15), ("claw", 0, 0)]
    assert (tmp_path / "pics" / "pan_plus.jpg").read_bytes() == b"two" and "tilted 2.5 deg" in said[0]

    class Falls(ClawRobot):
        def claw_pose(self, pan, lift):
            super().claw_pose(pan, lift)
            return "fell" if pan else "ok"
    f = Falls()
    assert [r[0] for r in take_pictures(f, FakeCamera([b"a", b"b"]), str(tmp_path / "p2"), pan=35.0, lift=15.0, say=lambda m: None, sleep=lambda s: None)] == ["straight", "pan_plus"]
    assert f.moves[-1] == ("claw", 35, 15)                                                     # stopped at the fall: nothing more was sent


def test_the_hold_test_reports_when_the_body_moves_away_from_where_he_stood():
    from pi_pipeline.behavior.claw_look import hold_test
    t = [0.0]

    def line(pitch_deg, roll_deg=0.0):                                                       # the firmware's fixed-width line: MCU:<ax><ay><az><yaw><pitch><roll>
        return f"MCU:{0.0:6.2f}{0.0:6.2f}{1.0:6.2f}{0.0:7.1f}{pitch_deg:7.1f}{roll_deg:7.1f}"

    class Link:
        def __init__(self, sag_at): self.sag_at, self.sent = sag_at, []
        def send(self, c, **k): self.sent.append(c); return "Voltage: 8.40 V"
        def drain(self, s): pass
        def poll_imu(self): return [line(1.0 if t[0] < self.sag_at else 22.0)]

    def clock(): return t[0]
    def sleep(s): t[0] += s
    said = []
    r = hold_test(Link(10.0), seconds=15.0, say=said.append, sleep=sleep, clock=clock)
    assert r["sag_at_s"] is not None and 9.5 <= r["sag_at_s"] <= 11.0 and r["min_volts"] == 8.4 and any("gave way" in m for m in said)
    class Talk(Link):
        def pop_other(self): return ["calib"] if t[0] >= self.sag_at else []
    t[0] = 0.0
    said = []
    r = hold_test(Talk(10.0), seconds=12.0, say=said.append, sleep=sleep, clock=clock)
    assert r["board_lines"] and r["board_lines"][0][1] == "calib" and any("board printed 'calib'" in m for m in said)         # what the firmware printed when it moved him
    t[0] = 0.0
    lk = Link(1e9)
    hold_test(lk, seconds=13.0, say=lambda m: None, sleep=sleep, clock=clock, redrive_s=4.0)
    assert sum(c.startswith("i8") for c in lk.sent) == 3                                           # plan step 4: the stand angles re-sent every 4 s (at 4, 8, 12 s)
    t[0] = 0.0
    r = hold_test(Link(99.0), seconds=6.0, say=lambda m: None, sleep=sleep, clock=clock)
    assert r["sag_at_s"] is None and r["max_dev_deg"] < 2


def test_the_exposure_is_checked_once_before_the_whole_claw_move():
    from pi_pipeline.behavior.claw_look import take_pictures

    class Cam(FakeCamera):
        def __init__(self, frames):
            super().__init__(frames); self.events = []
        def refresh_exposure(self): self.events.append("meter")
        def look(self):
            self.events.append("look")
            return super().look()
    cam = Cam([b"a", b"b", b"c"])
    take_pictures(ClawRobot(), cam, "/private/tmp/claude-502/-Users-markjohnson-Desktop-OneFolder-projects-bittleX/e357d825-4fe7-48cb-a2f9-37a04ee8c29e/scratchpad/exposure_t", pan=35.0, lift=15.0, say=lambda m: None, sleep=lambda s: None)
    assert cam.events == ["meter", "look", "look", "look"]                                    # once, then the three pictures
    import shutil
    shutil.rmtree("/private/tmp/claude-502/-Users-markjohnson-Desktop-OneFolder-projects-bittleX/e357d825-4fe7-48cb-a2f9-37a04ee8c29e/scratchpad/exposure_t", ignore_errors=True)
    bc.LOST_LOOKS, bc.CLAW_PAN_SIGN = 1, "right"
    cam2 = Cam([picture(), picture([disc(120, 110, 12)])])
    bc.claw_scan(ClawRobot(), cam2, bc.ChasePlanner(), sleep=lambda s: None, say=lambda m: None)
    assert cam2.events == ["meter", "look", "look"]                                            # one meter, then two looks (the ball was in the second)


# ---------------------------------------------------------------------------------------------- curation (user, 2026-11-01)

class _FakeStore:
    def __init__(self, facts):
        self.facts = [dict(f) for f in facts]
        self.added = []

    def list_facts(self):
        return list(self.facts)

    def delete_fact(self, i):
        self.facts = [f for f in self.facts if f["id"] != i]
        return True

    def add_fact(self, text, importance=2, core=False, source="told"):
        self.added.append((text, source))
        return True


def _curation_setup(tmp_path, monkeypatch, when="2026-10-31 20:00:00"):
    import time as _t

    from pi_pipeline.goals.observe import plain_punt
    for k, v in (("G2_GOAL_JOURNAL", "journal.jsonl"), ("G2_GOAL_STATE", "state.json"), ("G2_TURN_LOG", "turns.jsonl")):
        monkeypatch.setenv(k, str(tmp_path / v))
    cond = {"attachment": "arm", "floor": "hardwood", "hw": "hw-x"}
    tr = [{"kind": "act", "act": "punt", "at": (3.0, 0.0)}, {"kind": "after_punt", "ball": None}]
    settings = dict(ball_punt.BallPunt().base_settings())
    stamp = _t.mktime(_t.strptime(when, "%Y-%m-%d %H:%M:%S"))
    plain_punt(tr, "punted", 20.0, settings, state=State(str(tmp_path / "state.json")), journal=Journal(str(tmp_path / "journal.jsonl"), clock=lambda: stamp), conditions=cond)
    if when < "2026-11-01 01:20:00":                                                         # made before the epoch 2 start: the writer stamps today's epoch, so take the stamp off
        rows = [json.loads(x) for x in (tmp_path / "journal.jsonl").read_text().splitlines()]
        for r in rows:
            r.pop("scoring_epoch", None)
        (tmp_path / "journal.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return cond, settings, stamp


def test_an_attempt_from_an_older_scoring_epoch_is_retired_once_and_a_new_one_is_not(tmp_path, monkeypatch):
    from pi_pipeline.goals import curate as cu
    _curation_setup(tmp_path, monkeypatch)                                                  # made the night before the epoch 2 start
    key = "attachment=arm|floor=hardwood|hw=hw-x"
    assert State(str(tmp_path / "state.json")).data["ball_punt"][key]["count"] == 1
    assert cu.curate(dry=True, store=_FakeStore([])) and State(str(tmp_path / "state.json")).data["ball_punt"][key]["count"] == 1      # a dry run changes nothing
    said = cu.curate(store=_FakeStore([]))
    assert any("retired ball_punt attempt #1" in x for x in said)
    assert State(str(tmp_path / "state.json")).data["ball_punt"][key]["count"] == 0
    assert not any("retired" in x for x in cu.curate(store=_FakeStore([])))                 # once only
    assert cu.attempt_epoch({"goal": "ball_punt", "time": "2026-11-01 02:00:00"}) == 2 and cu.attempt_epoch({"goal": "ball_punt", "time": "2026-11-01 02:00:00", "scoring_epoch": 1}) == 1


def test_an_attempt_you_marked_right_is_never_retired(tmp_path, monkeypatch):
    from pi_pipeline.goals import curate as cu
    from pi_pipeline.goals.__main__ import main
    _curation_setup(tmp_path, monkeypatch)
    main(["verdict", "ball_punt", "1", "right"])
    assert not any("retired" in x for x in cu.curate(store=_FakeStore([])))


def test_a_lesson_whose_attempts_were_retired_is_deleted_and_can_be_restored(tmp_path, monkeypatch):
    from pi_pipeline.goals import curate as cu
    _curation_setup(tmp_path, monkeypatch)
    j = Journal(str(tmp_path / "journal.jsonl"))
    sess = j.read()[0]["session"]
    note = "Searching by back_claw_scan works best so far: 1 of 2 good"
    j.write("decision", session=sess, goal="ball_punt", index=1, action="kept", note=note, knob="search_order", old="claw_scan", new="back_claw_scan", evidence=[])
    store = _FakeStore([{"id": 7, "fact": f"Punt the ball: {note}", "source": "goal_lesson", "importance": 2}, {"id": 1, "fact": "The household pet has a name", "source": "told", "importance": 3}])
    said = cu.curate(store=store)
    assert any("lesson #7 deleted" in x for x in said) and [f["id"] for f in store.facts] == [1]                    # the told fact stays
    assert cu.restore(store) and store.added == [(f"Punt the ball: {note}", "goal_lesson")]


def test_a_session_wide_lesson_is_judged_by_every_counted_attempt_of_its_session(tmp_path, monkeypatch):
    from pi_pipeline.goals import curate as cu
    _curation_setup(tmp_path, monkeypatch)
    j = Journal(str(tmp_path / "journal.jsonl"))
    sess = j.read()[0]["session"]
    j.write("decision", session=sess, goal="ball_punt", index=None, action="kept", note="Searching by claw works best so far", knob="search_order", old="a", new="b", evidence=[])
    store = _FakeStore([{"id": 9, "fact": "Punt the ball: Searching by claw works best so far", "source": "goal_lesson", "importance": 2}])
    assert any("lesson #9 deleted" in x for x in cu.curate(store=store)) and store.facts == []


def test_a_lesson_the_newer_attempts_disagree_with_is_flagged_not_deleted(tmp_path, monkeypatch):
    from pi_pipeline.goals import curate as cu
    _curation_setup(tmp_path, monkeypatch, when="2026-11-01 02:00:00")                       # a current-epoch attempt behind the lesson
    j = Journal(str(tmp_path / "journal.jsonl"), clock=lambda: 1_793_000_000)
    sess = j.read()[0]["session"]
    j.write("decision", session=sess, goal="ball_punt", index=1, action="kept", note="Lining up within 12 deg works: 2 of 2 good", knob="punt_align_deg", old=12.0, new=12.0, evidence=[])
    j2 = Journal(str(tmp_path / "journal.jsonl"), clock=lambda: 1_793_000_050)                  # after the lesson
    for k in range(2, 6):
        j2.write("attempt", session=sess, goal="ball_punt", index=k, number=k, scoring_epoch=2, ended="punted", seconds=1.0, settings={"punt_align_deg": 12.0},
                outcome={"code": "missed", "score": 0.2, "success": False, "text": ""}, numbers={}, extra={}, trace=[])
    store = _FakeStore([{"id": 3, "fact": "Punt the ball: Lining up within 12 deg works: 2 of 2 good", "source": "goal_lesson", "importance": 2}])
    said = cu.curate(store=store, now=1_793_000_100)
    assert any("lesson #3 flagged: later attempts disagree" in x for x in said) and len(store.facts) == 1


def test_old_turn_log_lines_and_mac_history_copies_are_rotated(tmp_path, monkeypatch):
    import time
    import json as _j

    from pi_pipeline.goals import curate as cu
    monkeypatch.setenv("G2_GOAL_JOURNAL", str(tmp_path / "journal.jsonl"))
    monkeypatch.setenv("G2_TURN_LOG", str(tmp_path / "turns.jsonl"))
    (tmp_path / "turns.jsonl").write_text(_j.dumps({"time": "2026-01-01 10:00:00"}) + "\n" + _j.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
    assert cu.rotate_turn_log(False) == 1 and len((tmp_path / "turns.jsonl").read_text().splitlines()) == 1
    for d in ("20260101", "20260104", "20261030"):                                             # a Thursday, a Sunday, a recent one
        (tmp_path / "mac" / "history" / d).mkdir(parents=True)
    cu.prune_mac_history(str(tmp_path / "mac"), now=time.mktime(time.strptime("20261101", "%Y%m%d")))
    assert sorted(p.name for p in (tmp_path / "mac" / "history").iterdir()) == ["20260104", "20261030"]


def test_the_test_run_never_touches_the_real_home_or_memory_files():
    import os
    real = os.path.realpath("/Users") if os.path.exists("/Users") else "/home"
    assert os.path.realpath(os.path.expanduser("~")).startswith(os.path.realpath(__import__("tempfile").gettempdir())) or not os.path.expanduser("~").startswith(real)
    for key in ("G2_MEMORY_DB", "G2_EXPERIENCES", "G2_MEMORY_CALL_LOG"):
        assert os.path.realpath(os.environ[key]).startswith(os.path.realpath(__import__("tempfile").gettempdir()))


# ---------------------------------------------------------------------------------------------- memory log (user, 2026-11-01)

def _fake_proc(tmp_path, avail_kb=200_000, oom=0):
    p = tmp_path / "proc"
    (p / "123").mkdir(parents=True, exist_ok=True)
    (p / "124").mkdir(exist_ok=True)
    (p / "meminfo").write_text(f"MemTotal:  480000 kB\nMemAvailable: {avail_kb} kB\nSwapTotal: 100000 kB\nSwapFree: 90000 kB\n")
    (p / "vmstat").write_text(f"nr_free 1\noom_kill {oom}\n")
    (p / "loadavg").write_text("1.5 1.0 0.5 1/100 99\n")
    (p / "123" / "statm").write_text("100000 30000 0 0 0 0 0\n")           # 30000 pages
    (p / "123" / "cmdline").write_text("python\0-m\0pi_pipeline.voice\0")
    (p / "123" / "comm").write_text("python\n")
    (p / "124" / "statm").write_text("100 50 0 0 0 0 0\n")
    (p / "124" / "cmdline").write_text("sshd\0")
    (p / "124" / "comm").write_text("sshd\n")
    return str(p)


def test_the_memory_log_reads_meminfo_and_sums_g2s_processes(tmp_path):
    from pi_pipeline.diag import memlog
    s = memlog.sample(_fake_proc(tmp_path))
    assert s["avail_mb"] == 195.3 and s["swap_used_mb"] == 9.8 and s["oom_kills"] == 0 and s["load1"] == 1.5
    assert s["g2_rss_mb"] > 100 and s["top"][0][0].startswith("g2:") and memlog.sample(str(tmp_path / "nothing")) == {}      # no /proc (the Mac): nothing


def test_a_low_reading_is_logged_and_emitted_once_a_minute_and_marks_split_the_summary(tmp_path):
    from pi_pipeline.diag import memlog
    events, t = [], [1_800_000_000.0]
    log = memlog.MemLog(str(tmp_path / "m.jsonl"), emit=lambda *a, **k: events.append((a, k)), sampler=lambda: memlog.sample(_fake_proc(tmp_path, avail_kb=50_000)), clock=lambda: t[0])
    log.write("note", label="goal attempt 1")
    log.sample_once()
    t[0] += 10
    log.sample_once()                                                                    # 10 s later: sampled again, not warned again
    assert sum(1 for r in memlog.read_rows(None, str(tmp_path / "m.jsonl")) if r["kind"] == "low") == 1 and len(events) == 1 and events[0][0][2] == "memory.low"
    out = memlog.summarize(memlog.read_rows(None, str(tmp_path / "m.jsonl")))
    assert "overall: 2 samples" in out and "lowest available 49 MB" in out and "1 low-memory warning" in out and "goal attempt 1" in out


def test_the_memory_log_is_trimmed_past_its_size_and_off_means_off(tmp_path, monkeypatch):
    from pi_pipeline.diag import memlog
    monkeypatch.setattr(memlog, "MAX_BYTES", 2000)
    p = str(tmp_path / "m.jsonl")
    for i in range(100):
        memlog._append(p, {"t": f"2026-11-01 00:00:{i % 60:02d}", "kind": "sample", "avail_mb": 100.0 + i})
    assert 0 < len(open(p).read().splitlines()) < 100 and open(p).read().splitlines()[-1].endswith("199.0}")
    assert memlog.start("x") is None                                                      # G2_MEMLOG=off in the test run


# ---------------------------------------------------------------------------------------------- tasks leave nothing behind (user, 2026-11-01)

def test_a_task_puts_back_every_setting_it_changed_even_when_it_fails():
    from pi_pipeline.behavior import ball_chase as chase
    from pi_pipeline.behavior import punt_settings as ps
    from pi_pipeline.util import task_scope as ts
    before = ts.capture()
    with pytest.raises(RuntimeError):
        with ts.task_scope("test task"):
            ps.apply(chase, {"punt_max_in": 9.0, "search_order": "turn", "claw_pan_sign": "left"})
            assert chase.PUNT_MAX_IN == 9.0
            raise RuntimeError("the task failed")
    assert ts.capture() == before and chase.PUNT_MAX_IN != 9.0


def test_a_change_to_a_setting_the_task_did_not_declare_is_restored_logged_and_fails_the_test(monkeypatch):
    from pi_pipeline.behavior import ball_chase as chase
    from pi_pipeline.util import task_scope as ts
    old = chase.CLAW_PAN_SHARE
    old_cap = chase.SEARCH_MOVE_MAX_S
    with pytest.raises(AssertionError, match="SEARCH_MOVE_MAX_S"):
        with ts.task_scope("sloppy task"):
            chase.SEARCH_MOVE_MAX_S = 99.0                               # not in the settings table: undeclared
    assert chase.SEARCH_MOVE_MAX_S == old_cap and chase.CLAW_PAN_SHARE == old
    monkeypatch.delenv("G2_TASK_SCOPE_STRICT")
    with ts.task_scope("sloppy task, lenient") as scope:
        chase.SEARCH_MOVE_MAX_S = 98.0
    assert chase.SEARCH_MOVE_MAX_S == old_cap and any("SEARCH_MOVE_MAX_S" in x for x in scope.leaks)


def test_a_setting_left_changed_outside_any_task_is_found_and_put_back_when_the_next_task_starts(monkeypatch):
    from pi_pipeline.behavior import ball_chase as chase
    from pi_pipeline.util import task_scope as ts
    with ts.task_scope("first"):
        pass                                                              # the baseline is read
    monkeypatch.setattr(chase, "PUNT_MAX_IN", 7.5)
    monkeypatch.delenv("G2_TASK_SCOPE_STRICT")
    with ts.task_scope("second") as scope:
        assert chase.PUNT_MAX_IN != 7.5
    assert any("PUNT_MAX_IN" in x for x in scope.leaks)


def test_the_same_task_run_twice_in_one_process_starts_the_same_both_times_and_clears_its_stop_files(tmp_path, monkeypatch):
    import os
    from pi_pipeline.behavior import punt_settings as ps
    from pi_pipeline.util import task_scope as ts
    from pi_pipeline.behavior import ball_chase as chase
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = []
    for _ in range(2):
        ap = FakeApproach([oc("bad", 0.2)] * 2)
        orig = ap.run_attempt
        def _attempt(settings, ctx, _o=orig):
            seen.append(ts.capture())                                     # what the attempt starts with
            ps.apply(chase, {"punt_max_in": 8.0, "nudge_max_in": 9.0})
            return _o(settings, ctx)
        ap.run_attempt = _attempt
        s, _mem = _session(tmp_path, ap, attempts=2)
        os.makedirs(tmp_path / ".local/share/g2", exist_ok=True)
        (tmp_path / ".local/share/g2/goal_stop").write_text("")
        s.run()
        assert not (tmp_path / ".local/share/g2/goal_stop").exists()
    assert seen[0] == seen[2]                                         # the first attempt of each run starts the same (inside a run the attempts apply their own values)


# ---------------------------------------------------------------------------------------------- the claw look from a sit (user, 2026-11-01)

class SitRobot(ClawRobot):
    def sit_down(self): return self._do(("sit",))
    def stand_from_sit(self): return self._do(("stand_from_sit",))


def test_the_claw_look_sits_swings_left_then_right_returns_to_centre_and_stands_up_with_the_back_legs():
    bc.CLAW_PAN_DEG, bc.CLAW_LIFT_DEG, bc.CLAW_PAN_SIGN, bc.CLAW_FROM_SIT = 35.0, 15.0, "left", True       # a positive pan points the camera left on G2
    robot, trace = SitRobot(), []
    state, found = bc.claw_scan(robot, FakeCamera([picture(), picture()]), bc.ChasePlanner(), sleep=lambda s: None, say=lambda m: None, trace=trace)
    assert [m[0] for m in robot.moves] == ["sit", "claw", "claw", "claw", "claw", "claw", "stand_from_sit"]
    assert robot.moves[1:6] == [("claw", 0, 15), ("claw", 35, 15), ("claw", -35, 15), ("claw", 0, 15), ("claw", 0, 0)] and state == "ok" and found is None     # raised clear of the legs, left, right, centre, lowered (user, 2026-11-02)


def test_a_ball_seen_in_the_first_picture_still_gets_both_pictures_and_only_its_direction_is_used(monkeypatch):
    bc.CLAW_PAN_DEG, bc.CLAW_LIFT_DEG, bc.CLAW_PAN_SIGN, bc.CLAW_FROM_SIT, bc.LOST_LOOKS = 35.0, 15.0, "left", True, 1
    ahead = picture([disc(120, 110, 12)])
    robot = SitRobot()
    bc.run_chase(robot, FakeCamera([picture(), ahead, picture(), picture()]), lambda: False, max_steps=2, sleep=lambda s: None, say=lambda m: None, trace=[])
    assert [m[0] for m in robot.moves][:7] == ["sit", "claw", "claw", "claw", "claw", "claw", "stand_from_sit"]
    turns = [m for m in robot.moves if m[0] == "turn"]
    assert turns and turns[0][1] < -20                                   # seen in the left picture: he turns left toward it, and looks again standing instead of walking on a sit-height distance


def test_the_stand_up_from_a_sit_lifts_the_back_legs_slowly_first(monkeypatch):
    from pi_pipeline.gait import standup
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    sent = []
    assert standup.stand_from_sit(sent.append, lambda s: None, "ksit") and len(sent) >= 30
    assert not standup.stand_from_sit(sent.append, lambda s: None, "krest")                    # only from a sit
    first, mid = sent[10], sent[len(sent) // 3]
    nums = lambda c: dict(zip(*[iter(int(x) for x in c[1:].split())] * 2))                      # noqa: E731
    rear = [k for k in nums(sent[-1]) if k in (12, 13, 14, 15, 8, 9, 10, 11)]
    assert rear and nums(mid) != nums(first)


def test_the_claw_look_uses_the_more_central_sighting_and_ignores_an_unchanged_second_frame():
    bc.CLAW_PAN_DEG, bc.CLAW_LIFT_DEG, bc.CLAW_PAN_SIGN, bc.CLAW_FROM_SIT = 35.0, 15.0, "left", True
    near_edge, central = picture([disc(215, 110, 14)]), picture([disc(130, 110, 14)])
    said = []
    _st, found = bc.claw_scan(SitRobot(), FakeCamera([near_edge, central]), bc.ChasePlanner(), sleep=lambda s: None, say=said.append)
    assert found is not None and abs(found.bearing_deg - 40.0) < 6                      # the central one (second picture, pan -35: the camera turned right 35 deg, the ball a few deg right of its centre)
    _st, found = bc.claw_scan(SitRobot(), FakeCamera([near_edge, near_edge]), bc.ChasePlanner(), sleep=lambda s: None, say=said.append)
    assert any("old frame" in m for m in said) and found is not None                      # the same sighting twice although the arm moved: the first is used


def test_a_ball_only_the_dim_pass_found_needs_a_second_picture():
    from pi_pipeline.vision.ball_finder import BallReading
    dim = BallReading(100.0, 120.0, 400, 22, 22, 22.0, 15.0, 5.0, False, via="dim")
    sure = BallReading(100.0, 120.0, 400, 22, 22, 22.0, 15.0, 5.0, False)
    assert bc.confirm_ball(FakeCamera([picture()]), sure, sleep=lambda s: None) is sure     # a normal reading is taken as it is
    assert bc.confirm_ball(FakeCamera([picture()]), dim, sleep=lambda s: None) is None       # the second picture shows nothing: a false ball
    again = picture([disc(125, 120, 12)])                                                     # the second picture shows it near the same direction (the dim pass may still be the one finding it)
    assert bc.confirm_ball(FakeCamera([again]), dim, sleep=lambda s: None) is not None


def test_a_look_drops_the_old_frame_the_module_answers_with():
    class Cam:
        def __init__(self):
            self.dropped = self.taken = 0

        def discard_one(self):
            self.dropped += 1

        def snapshot(self):
            self.taken += 1
            return type("S", (), {"jpeg": b"x"})()
    cam = Cam()
    assert bc._SnapshotCamera(cam).look() == b"x" and (cam.dropped, cam.taken) == (1, 1)


def test_the_pose_check_says_when_the_board_gave_no_pose(monkeypatch):
    monkeypatch.setattr(bc.time, "sleep", lambda s: None)

    class Ser:
        in_waiting = 0

        def reset_input_buffer(self): pass
        def write(self, b): pass
        def read(self, n): return b""

    class Link:
        _ser = Ser()
        sent = []

        def send(self, *a, **k): self.sent.append(a)
    lk = Link()
    assert bc._stand_if_lying(lk) is False and lk.sent                       # unreadable: he is stood up to be safe, and the caller learns the board said nothing


def test_a_wall_reading_that_would_hide_the_ball_or_never_changes_is_not_believed():
    from pi_pipeline.vision.ball_finder import BallReading
    ball = BallReading(100.0, 120.0, 400, 22, 22, 22.0, 36.0, -20.0, False)
    wall = bc.WallSeen(8.0, "left")
    got, why = bc.vet_wall(wall, ball, {})
    assert got.nearest_in is None and "hide the ball" in why                       # the wall is nearer than a ball seen almost straight on
    side_ball = BallReading(100.0, 120.0, 400, 22, 22, 22.0, 11.0, 45.0, False)
    assert bc.vet_wall(wall, side_ball, {})[0].nearest_in is None                     # the 2026-11-01 fall: a ball at +45 deg, 11 in, and a "wall" at 8 in
    near_ball = BallReading(100.0, 120.0, 400, 22, 22, 22.0, 6.0, -20.0, False)
    got, why = bc.vet_wall(wall, near_ball, {})
    assert got.nearest_in == 8.0 and not why                                       # the ball is nearer than the wall: the wall is believed
    st = {}
    for _ in range(2):
        got, why = bc.vet_wall(wall, None, st)
        assert got.nearest_in == 8.0
    got, why = bc.vet_wall(wall, None, st)
    assert got.nearest_in is None and "3 looks" in why                             # 8 in three looks in a row: not believed
    got, why = bc.vet_wall(bc.WallSeen(20.0, "left"), None, st)
    assert got.nearest_in == 20.0 and st["stuck"] == 0


def test_the_camera_wait_gives_up_and_the_claw_sit_stands_first():
    assert bc._wait_for_camera("/dev/none", 0.0, sleep=lambda s: None, exists=lambda p: False) is False
    assert bc._wait_for_camera("/dev/x", 5.0, sleep=lambda s: None, exists=lambda p: True, can_open=lambda p: True) is True
    sent = []

    class Lk:
        def send(self, c, **k): sent.append(c)
    r = bc.SerialRobot(Lk(), sleep=lambda s: None)
    r.sit_down()
    assert sent.index("kbalance") < sent.index(bc.CLAW_LOOK_POSE) and bc.CLAW_LOOK_POSE == "kcalib"      # stand first, then the attention pose


def test_a_ball_gone_after_a_small_step_means_he_pushed_it_so_he_looks_around():
    pl = bc.ChasePlanner()
    pl.decide(bc.BallReading(100.0, 120.0, 400, 22, 22, 22.0, 5.0, 0.0, False))        # a ball 5 in ahead: a small step
    pl.prev_kind = "walk"
    a = pl.decide(None)
    assert a.kind == "claw_look" and "pushed" in a.why
    assert pl.decide(None).kind != "punt"                                                  # the next empty picture goes on to the search
    pl2 = bc.ChasePlanner()
    pl2.decide(bc.BallReading(100.0, 120.0, 400, 22, 22, 22.0, 5.0, 0.0, False))
    pl2.prev_kind = "align"
    assert pl2.decide(None).kind in ("punt", "back")                                       # after a turn it is at the claw: the old rule
    pl3 = bc.ChasePlanner()
    pl3.claw_ok = False
    pl3.decide(bc.BallReading(100.0, 120.0, 400, 22, 22, 22.0, 5.0, 0.0, False))
    pl3.prev_kind = "walk"
    assert pl3.decide(None).kind == "look"


def test_the_three_point_turn_can_be_switched_off_and_backs_then_goes_forward(monkeypatch):
    monkeypatch.setattr(bc, "WALL_THREE_POINT", False)
    pl = bc.ChasePlanner()
    assert pl._wall_turn(bc.WallSeen(8.0, "left"), "x").kind == "wall_turn"                    # off: a plain turn
    monkeypatch.setattr(bc, "WALL_THREE_POINT", True)
    a = pl._wall_turn(bc.WallSeen(8.0, "left"), "x")
    assert a.kind == "three_point" and a.degrees < 0 and a.seconds == bc.THREE_POINT_BACK_S and pl.back_s == bc.THREE_POINT_BACK_S
    pl.back_s = bc.BACK_BUDGET_S
    assert pl._wall_turn(bc.WallSeen(8.0, "left"), "x").kind == "wall_turn"                    # no room left to back up: a plain turn
    monkeypatch.setattr(bc, "SEARCH_THREE_POINT", True)
    pl2 = bc.ChasePlanner()
    pl2.claw_ok = False
    kinds = [pl2.decide(None).kind for _ in range(6)]
    assert "three_point" in kinds
    sent = []

    class Lk:
        def send(self, c, **k): sent.append(c)
    bc.SerialRobot(Lk(), sleep=lambda s: None, clock=iter(range(0, 10000)).__next__).three_point_turn(-30.0, 1.0, 1.0)
    assert [c for c in sent if c.startswith("k") and c != "kbalance"] == ["kbkR", "kwkL"]


def test_the_three_point_hardware_test_reports_the_heading_changes():
    from pi_pipeline.behavior import three_point as tp
    heads = iter([10.0, -40.0, -95.0])
    out = tp.run_test(type("R", (), {"_skill": lambda self, t, s: "ok"})(), object(), "left", 1.0, 1.0, say=lambda m: None, yaw=lambda lk: next(heads))
    assert out["back"] == -50.0 and out["forward"] == -55.0 and out["total"] == -105.0


def test_an_align_turn_that_overshoots_backs_up_and_lines_up_again():
    from pi_pipeline.vision.ball_finder import BallReading
    pl = bc.ChasePlanner()
    first = pl.decide(BallReading(100.0, 120.0, 400, 22, 22, 22.0, 5.0, -23.0, False))
    assert first.kind == "align"
    pl.prev_kind = "align"
    over = pl.decide(BallReading(100.0, 120.0, 400, 22, 22, 22.0, 2.5, 32.0, False))        # the ball swung to the other side
    assert over.kind == "back" and "overshot" in over.why and pl.align_turns == 0
    pl.prev_kind = "back"
    again = pl.decide(BallReading(100.0, 120.0, 400, 22, 22, 22.0, 5.0, 14.0, False))
    assert again.kind == "align"                                                                # after the back-up he lines up again


def test_with_the_ball_within_12_in_a_wall_never_turns_him_away():
    from pi_pipeline.vision.ball_finder import BallReading
    pl = bc.ChasePlanner()
    a = pl.decide(BallReading(100.0, 120.0, 400, 22, 22, 22.0, 11.0, 30.0, False), bc.WallSeen(10.0, "left"))
    assert a.kind not in ("wall_turn", "three_point")                                        # a ball 11 in away: lining up goes on
    far = bc.ChasePlanner().decide(BallReading(100.0, 120.0, 400, 22, 22, 22.0, 20.0, 0.0, False), bc.WallSeen(10.0, "left"))
    assert far.kind in ("wall_turn", "three_point")                                          # a ball 20 in away beyond a wall 10 in ahead: walls first, as before
