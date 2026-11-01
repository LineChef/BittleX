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
    p = bc.ChasePlanner()
    p.decide(reading(20, 30))
    kinds = [p.decide(None).kind for _ in range(2 + 5)]
    assert kinds[:2] == ["look", "look"] and kinds[2:] == ["claw_look", "search_turn", "claw_look", "search_turn", "claw_look"]
    assert p.claw_side == 1


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


def test_a_claw_look_that_finds_the_ball_turns_g2_toward_it_with_the_pan_added():
    bc.CLAW_PAN_DEG, bc.CLAW_LIFT_DEG, bc.CLAW_PAN_SIGN, bc.LOST_LOOKS = 35.0, 15.0, "right", 1
    none = picture()
    ahead_in_picture = picture([disc(120, 110, 12)])                     # straight ahead in the camera's picture, which is pointed 35 deg right
    cam = FakeCamera([picture([disc(200, 110, 14)]), none, ahead_in_picture, ahead_in_picture])
    robot, trace = ClawRobot(), []
    bc.run_chase(robot, cam, lambda: False, max_steps=4, sleep=lambda s: None, say=lambda m: None, trace=trace)
    claws = [m for m in robot.moves if m[0] == "claw"]
    assert claws[0] == ("claw", 35, 15) and claws[-1] == ("claw", 0, 0)                 # the side it was last seen first, the arm home after
    turns = [m for m in robot.moves if m[0] == "turn"]
    assert turns and turns[-1][1] > 20                                                   # it turned right, toward 35 deg
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


def test_the_voice_loop_names_the_goal_and_asks_for_the_hand_over():
    from pi_pipeline.tests.test_voice_loop import _loop, _run
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
    assert codes == ["turned_away", "turned_but_hit", "bumped"]                              # the two touches 1 s apart are one bump


def test_the_exploration_tally_keeps_timed_wall_events_for_the_walls_goal():
    from pi_pipeline.goals.walls import events_from_diag
    from pi_pipeline.reflection.recap import SessionTally
    t = [0.0]
    tally = SessionTally(clock=lambda: t[0])
    tally.note("wall.steer", "wall ahead (14 in, 2 groups): turn left"); t[0] = 2.0
    tally.note("contact", "imu"); t[0] = 3.0
    tally.note("survey.start", "")
    ev = events_from_diag(tally.events)
    assert ev == [{"t": 0.0, "kind": "steer", "nearest_in": 14.0}, {"t": 2.0, "kind": "hit"}] and tally.counts()["survey.start"] == 1


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
        assert rec["count"] == 4 and rec["focus"] in ("near_look_in", "wall_stop_in", "leg_margin_in")
        rows = Journal().sessions("walls")
        assert rows[0]["start"]["mode"] == "exploration" and len(rows[0]["attempts"]) == 4
        assert standing.learn("walls", [], "exploration", conditions=cond) == 0
    finally:
        BehaviorDriver.WALL_STOP_IN, BehaviorDriver.WALL_TURN_RAD, BehaviorDriver.LEG_MARGIN_IN, explore_session.NEAR_LOOK_IN = keep


import math  # noqa: E402


def test_while_chasing_walls_come_first():
    bc.CHASE_WALL_IN = 10.0
    p = bc.ChasePlanner()
    a = p.decide(reading(20, 0), bc.WallSeen(40.0, "left"))
    assert a.kind == "walk"
    a = p.decide(reading(20, 0), bc.WallSeen(8.0, "left"))                                  # he is within 10 in of a wall: turn away
    assert a.kind == "wall_turn" and a.degrees < 0
    q = bc.ChasePlanner()
    assert q.decide(reading(10, 0), bc.WallSeen(14.0, "right")).kind == "look"               # the ball is 4 in from the wall: look again first
    assert q.decide(reading(10, 0), bc.WallSeen(14.0, "right")).kind == "give_up"           # ... then leave it


def test_a_walk_is_cut_short_before_a_wall_and_a_ball_by_the_wall_ends_the_attempt_uncounted():
    bc.CHASE_WALL_IN, bc.LOST_LOOKS = 10.0, 1
    robot, trace = ClawRobot(), []
    cam = FakeCamera([picture([disc(120, 90, 6)])])                                          # the ball far ahead (about 27 in)
    bc.run_chase(robot, cam, lambda: False, max_steps=1, sleep=lambda s: None, say=lambda m: None, trace=trace,
                 wall_check=lambda jpeg, ball: bc.WallSeen(13.0, "left"))
    walks = [m for m in robot.moves if m[0] == "walk"]
    assert walks and walks[0][1] <= 1.0 + 3.0 / 4.2 + 0.05                                      # only 3 in of room before the 10 in limit
    robot, trace = ClawRobot(), []
    out = bc.run_chase(robot, FakeCamera([picture([disc(120, 110, 25)])]), lambda: False, max_steps=5, sleep=lambda s: None, say=lambda m: None, trace=trace,
                       wall_check=lambda jpeg, ball: bc.WallSeen(ball.distance_in + 3.0, "left"))
    assert out == "ball_by_wall" and not any(m[0] == "walk" for m in robot.moves)
    o = ball_punt.BallPunt().score(_res("ball_by_wall", trace), S)
    assert o.code == "ball_by_wall" and o.score is None                                       # not counted against the punt


def test_the_chase_wall_check_needs_walls_first_and_a_calibration_from_this_hardware(tmp_path, monkeypatch):
    from pi_pipeline.goals import walls
    monkeypatch.setattr(walls, "calibration_info", lambda: (None, None))
    assert walls.make_wall_check() is None
    monkeypatch.setattr(walls, "calibration_info", lambda: (object(), "2026-10-20 10:00:00"))
    monkeypatch.setattr(walls, "calibration_current", lambda when: False)
    assert walls.make_wall_check() is None                                                    # older than the latest hardware change
    monkeypatch.setattr(walls, "calibration_current", lambda when: True)
    assert callable(walls.make_wall_check())
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
    assert tts.said[0].startswith("I'll practise turn away from walls") and any(e.get("arm_explore") and e.get("roam_s") == 300.0 for e in events)
    events.clear()
    lp, w, stt, conv, tts = _loop(["practise the punt"], on_event=lambda **kw: events.append(kw))
    _run(lp, 1)
    assert any(e.get("arm_goal") == "ball_punt" for e in events)
