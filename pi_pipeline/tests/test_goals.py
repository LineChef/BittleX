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

KN = [Knob("a", "float", lo=1.0, hi=5.0, step=1.0, label="a at"), Knob("b", "choice", options=("x", "y", "z")),
      Knob("c", "float", lo=0.0, hi=1.0, step=0.1, control="ask"), Knob("f", "float", lo=0.0, hi=9.0, step=1.0, control="fixed")]
DIAG = {"bad": [("f", 1), ("a", -1)], "lost": [("b", "other")], "soft": [("c", -1)], "askfirst": [("c", -1), ("a", +1)]}
BASE = {"a": 3.0, "b": "x", "c": 0.5, "f": 4.0}


def oc(code, score, success=False):
    return Outcome(code, score, success, code)


def test_a_failure_starts_a_trial_of_the_first_free_knob_and_a_better_result_keeps_it():
    j = Judge(KN, DIAG)
    s = j.settings(BASE)
    d = j.update(1, oc("bad", 0.2), s)
    assert d[-1].action == "try" and d[-1].knob == "a" and d[-1].new == 2.0                 # the fixed knob is skipped
    s = j.settings(BASE)
    assert s["a"] == 2.0 and s["f"] == 4.0
    assert j.update(2, oc("hit", 0.9, True), s)[0].action == "wait"
    d = j.update(3, oc("hit", 0.8, True), s)
    assert d[0].action == "kept" and "works better" in d[0].note and 1 in d[0].evidence and 3 in d[0].evidence
    assert j.settings(BASE)["a"] == 2.0 and j.state["trial"] is None


def test_a_change_that_does_not_help_is_undone_and_not_tried_again_soon():
    j = Judge(KN, DIAG)
    s = j.settings(BASE)
    j.update(1, oc("bad", 0.4), s)
    s = j.settings(BASE)
    j.update(2, oc("bad", 0.1), s)
    d = j.update(3, oc("bad", 0.1), s)
    assert d[0].action == "undo" and j.settings(BASE)["a"] == 3.0
    assert d[-1].action == "none"                     # a = 2 was just undone, a = 3 - 1 is that same value: nothing else to try for "bad"
    assert "a=2.0" in j.state["rejected"]


def test_a_fall_during_a_trial_undoes_it_at_once():
    j = Judge(KN, DIAG)
    j.update(1, oc("bad", 0.2), j.settings(BASE))
    d = j.update(2, Outcome("fell", 0.0, False, "I fell"), j.settings(BASE))
    assert d[0].action == "undo" and "fell" in d[0].note and j.settings(BASE)["a"] == 3.0


def test_success_keeps_everything_and_an_uncounted_attempt_is_ignored():
    j = Judge(KN, DIAG)
    assert j.update(1, oc("hit", 0.9, True), j.settings(BASE))[0].action == "keep"
    assert j.update(2, Outcome("aborted", None, False, "stopped"), j.settings(BASE))[0].action == "not_counted" and j.state["count"] == 1


def test_an_ask_knob_is_never_changed_only_suggested_and_learned_values_never_override_ask_or_fixed():
    j = Judge(KN, DIAG)
    d = j.update(1, oc("soft", 0.3), j.settings(BASE))
    assert d[-1].action == "suggest" and j.settings(BASE)["c"] == 0.5 and j.state["suggestions"]["c"]["new"] == 0.4
    d = j.update(2, oc("askfirst", 0.3), j.settings(BASE))
    assert d[-1].action == "try" and d[-1].knob == "a" and "yours to change" in d[-1].note        # the suggestion rides along, the free knob is tried
    j.state["settings"].update(c=0.1, f=9.0)                                                         # even if the file were edited by hand
    s = j.settings(BASE)
    assert s["c"] == 0.5 and s["f"] == 4.0


def test_a_choice_knob_tries_an_untried_option_first():
    j = Judge(KN, DIAG)
    d = j.update(1, oc("lost", 0.0), j.settings(BASE))
    assert d[-1].knob == "b" and d[-1].new == "y"


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


def test_a_session_changes_the_next_attempt_writes_everything_and_saves_lessons(tmp_path):
    ap = FakeApproach([oc("bad", 0.2), oc("hit", 0.9, True), oc("hit", 0.8, True), oc("hit", 0.9, True)])
    s, mem = _session(tmp_path, ap)
    out = s.run()
    assert [r["a"] for r in ap.ran] == [3.0, 2.0, 2.0, 2.0]                                # the next attempt used what the first one taught
    assert out["attempts"] == 4 and out["successes"] == 3 and ap.opened == 1 and ap.closed == 1
    rows = Journal(str(tmp_path / "j.jsonl")).sessions("g")
    assert len(rows) == 1 and len(rows[0]["attempts"]) == 4 and rows[0]["end"]["why"] == "attempts"
    assert any(d["action"] == "kept" for d in rows[0]["decisions"])
    st = json.load(open(tmp_path / "s.json"))
    assert st["g"]["attachment=arm|floor=hardwood"]["settings"]["a"] == 2.0
    assert mem.facts and all(f[3] == "goal_lesson" and f[1] == 2 and not f[2] for f in mem.facts) and mem.facts[0][0].startswith("The test goal:")
    s2, _ = _session(tmp_path, FakeApproach([oc("hit", 0.9, True)]), attempts=1)               # the next session starts from what he learned
    s2.run()
    assert s2.approach.ran[0]["a"] == 2.0


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


def test_the_report_shows_sessions_changes_and_settings(tmp_path):
    ap = FakeApproach([oc("bad", 0.2), oc("hit", 0.9, True), oc("hit", 0.8, True)])
    s, _ = _session(tmp_path, ap, attempts=3)
    s.goal = Goal("ball_punt", "Punt the ball", "ball_punt", attempts=3, rest_between_s=0)        # the page names the knobs through the real approach
    s.run()
    from pi_pipeline.goals.report import goal_page, text_history
    page = goal_page("ball_punt", Journal(str(tmp_path / "j.jsonl")), State(str(tmp_path / "s.json")))
    assert "<svg" in page and "Every change and why" in page and "Sessions" in page and "prefers-color-scheme" in page
    assert "keeping it" in text_history("ball_punt", Journal(str(tmp_path / "j.jsonl")))


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
    assert not row["suggestions"] and "punch_lunge_s=0.1" in row["rejected"]


def test_the_voice_service_says_the_suggestion_when_it_starts(tmp_path):
    from pi_pipeline.tests.test_voice_loop import _loop
    _state_with_suggestion(tmp_path)
    lp, w, stt, conv, tts = _loop(["review"])
    assert lp._offer_goal_suggestions() == 1 and "suggestion" in tts.said[0] and w.calls == 0          # no wake word needed for the answer
