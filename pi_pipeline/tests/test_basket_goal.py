"""The basket goal's approach (goals/basket.py): scoring, the settings it applies, the diagnosis of a miss, and a session on a made-up world."""
import random

from pi_pipeline.behavior import basket_lineup as bl
from pi_pipeline.behavior import basket_run as br
from pi_pipeline.goals import approach, basket, spec
from pi_pipeline.goals.approach import AttemptContext, AttemptResult


def result(rec, ended):
    return AttemptResult(ended, 12.0, [], {"rec": rec})


def test_it_is_registered_with_a_goal_and_a_start_phrase():
    assert approach.make("basket").name == "basket"
    g = spec.BUILTIN["basket"]
    assert spec.goal_for_words("basket goal", spec.BUILTIN) is g and g.target_successes == 1 and g.needs_attachment == "arm"
    assert "basket" in spec.priority()


def test_a_make_is_the_only_success_and_a_retrieved_miss_earns_half():
    a = basket.BasketGoal()
    s = a.base_settings()
    o = a.score(result({"after": {"code": "not_seen"}}, "made"), s)
    assert o.success and o.score == 1.0 and o.stages == {"throw": 1.0}
    miss = {"after": {"code": "missed", "puck": [10.0, 0.0], "basket": [16.0, 0.0]}, "retrieval": {"outcome": "retrieved"}, "lineup": {"outcome": "aligned"}}
    o = a.score(result(miss, None), s)
    assert not o.success and o.score == 0.5 and o.code == "missed_short" and o.stages == {"throw": 0.0, "retrieve": 1.0, "lineup": 1.0}
    lost = dict(miss, retrieval={"outcome": "puck_not_found"}, lineup=None)
    o = a.score(result(lost, "puck_not_found"), s)
    assert o.score == 0.0 and o.code == "puck_not_found" and o.stages == {"throw": 0.0, "retrieve": 0.0}
    nolineup = dict(miss, lineup={"outcome": "could_not_align"})
    o = a.score(result(nolineup, "could_not_align"), s)
    assert o.score == 0.5 and o.code == "could_not_align" and o.stages["lineup"] == 0.0


def test_a_fall_a_dead_battery_and_a_missing_picture_are_handled_as_the_ball_goal_does():
    a, s = basket.BasketGoal(), basket.BasketGoal().base_settings()
    assert a.score(result({}, "fell"), s).code == "fell"
    for ended in ("battery", "no_picture", "throw_failed", "stopped"):
        assert a.score(result({}, ended), s).counted is False


def test_a_miss_is_called_short_long_left_or_right_from_where_the_puck_lay():
    f = lambda p, b: basket.miss_code({"puck": p, "basket": b})                          # noqa: E731
    assert f((10.0, 0.0), (16.0, 0.0)) == "missed_short" and f((22.0, 0.0), (16.0, 0.0)) == "missed_long"
    assert f((16.0, -12.0), (16.0, 0.0)) == "missed_left" and f((16.0, 12.0), (16.0, 0.0)) == "missed_right"
    assert f((16.0, 1.0), (16.0, 0.0)) == "missed" and basket.miss_code(None) == "missed"
    for code, knobs in basket.DIAGNOSIS.items():
        assert all(k in basket.KNOBS for k, _d in knobs), code


def test_the_attempt_settings_are_applied_and_put_back():
    before = (bl.TARGET_IN, bl.AIM_OFFSET_DEG, br.PICK_UNDERSHOOT_IN)
    with basket.applied({"standoff_in": 18.0, "aim_offset_deg": 2.0, "pick_undershoot_in": 1.0}):
        assert (bl.TARGET_IN, bl.AIM_OFFSET_DEG, br.PICK_UNDERSHOOT_IN) == (18.0, 2.0, 1.0)
    assert (bl.TARGET_IN, bl.AIM_OFFSET_DEG, br.PICK_UNDERSHOOT_IN) == before
    try:
        with basket.applied({"standoff_in": 14.0}):
            raise RuntimeError
    except RuntimeError:
        pass
    assert bl.TARGET_IN == before[0]


def test_an_attempt_runs_through_the_shared_attempt_function_with_the_settings_applied():
    seen = []

    class Env:
        def battery_ok(self):
            return True

        def throw(self, holding):
            seen.append((holding, bl.TARGET_IN))
            return {"ok": True}

        def after_throw(self):
            from types import SimpleNamespace
            return SimpleNamespace(claw_in=16.0, bearing_deg=0.0, width_px=36, height_px=28, x=120.0, y=110.0, touches_edge=False), None       # the basket in view, the puck not: confirmed from close up below

        class mover:                                                                                                       # noqa: N801
            @staticmethod
            def forward(v):
                return "ok"

        def quick_basket(self):
            from types import SimpleNamespace
            return SimpleNamespace(claw_in=9.8, bearing_deg=0.0, width_px=89, height_px=9, touches_edge=False)         # already at the confirm distance

        def confirm_look(self):
            from types import SimpleNamespace
            tub = SimpleNamespace(claw_in=9.8, bearing_deg=0.0, width_px=89, height_px=9, touches_edge=False)
            return tub, None, SimpleNamespace(x=120.0, y=116.0, count=30)                                              # a puck inside: a make

        def lie_down(self):
            pass
    a = basket.BasketGoal(env=Env())
    r = a.run_attempt({**a.base_settings(), "standoff_in": 18.0}, AttemptContext())
    assert r.ended == "made" and seen == [(False, 18.0)] and bl.TARGET_IN == 16.0
    assert a.score(r, a.base_settings()).success


def test_a_session_on_a_made_up_world_finds_the_standoff_that_makes_the_shot():
    """The judge, the journal and the session loop with the basket approach on a world where the shot is made from 15 inches and lands long from nearer, short from farther."""
    import tempfile
    from pi_pipeline.goals.journal import Journal, State
    from pi_pipeline.goals.runner import GoalSession
    rng = random.Random(3)

    class World(basket.BasketGoal):
        def open(self): pass
        def close(self): pass
        def battery_ok(self, min_pct): return True, "ok"

        def run_attempt(self, settings, ctx):
            d = settings["standoff_in"]
            made = abs(d - 15.0) <= 0.6 and rng.random() < 0.9
            rec = {"after": {"code": "not_seen" if made else "missed", "puck": [d + 6.0 if d < 15 else d - 6.0, 0.0], "basket": [d, 0.0]},
                   "retrieval": None if made else {"outcome": "retrieved"}, "lineup": None if made else {"outcome": "aligned"}}
            return AttemptResult("made" if made else "ready", 5.0, [], {"rec": rec})
    g = spec.Goal("basket", "t", "basket", attempts=40, minutes=500.0, min_pack_pct=0, rest_between_s=0.0)
    with tempfile.TemporaryDirectory() as d:
        st = State()
        final = None
        for _ in range(1):
            sess = GoalSession(g, World(), journal=Journal(d + "/j.jsonl"), state=st, say=lambda s: None, conditions={"attachment": "arm", "floor": "x", "hw": "t"}, sleep=lambda s: None, save_memory=False, overrides={}, rng=rng)
            res = sess.run()
            final = sess.judge.state
    assert res is not None and abs(sess.judge.best("standoff_in", 16.0) - 15.0) <= 1.0, sess.judge.state.get("values", {}).get("standoff_in")


def test_every_attempt_is_logged_with_the_look_timing(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(br, "LOG_DIR", str(tmp_path))
    said = []
    a = basket.BasketGoal()
    rec = {"attempt": 1, "after": {"pictures": {"look_left": {"t_s": (3.1, 4.0)}, "centre": {"t_s": (9.0, 9.9)}}}}
    a._log_attempt(rec, "made", AttemptContext(say=said.append))
    assert said and "look_left 3.1 to 4.0" in said[0] and "centre 9.0 to 9.9" in said[0]
    logs = list(tmp_path.glob("*_basket_goal.json"))
    assert len(logs) == 1 and json.loads(logs[0].read_text())["attempts"][0]["attempt"] == 1


def test_the_limits_the_owner_set():
    assert (br.MAX_RETRIEVAL_STEPS, br.MAX_SCANS, br.PICK_TRIES, bl.MAX_CORRECTIONS, bl.SCAN_MAX_DEG) == (20, 30, 6, 60, 864.0)                                                              # the line-up: 60 corrections and a 54 degree scan step for 16 steps (two full circles really; the owner raised them 2026-11-25, the attempt was cut off before the shot was lined up)
    g = spec.BUILTIN["basket"]
    assert (g.attempts, g.minutes) == (10, 20.0)


def test_the_environment_the_throw_script_changes_is_put_back(monkeypatch):
    import os
    monkeypatch.delenv("G2_GYRO_BALANCE", raising=False)
    monkeypatch.setenv("G2_STAND_GYRO", "1")
    with basket.env_restored():
        os.environ["G2_GYRO_BALANCE"], os.environ["G2_STAND_GYRO"] = "0", "0"
    assert "G2_GYRO_BALANCE" not in os.environ and os.environ["G2_STAND_GYRO"] == "1"


def test_the_basket_session_ends_after_any_attempt_that_leaves_no_puck_to_throw():
    ends = set(basket.BasketGoal.ends_session)
    assert {"puck_not_found", "could_not_reach_puck", "pick_failed", "circled_twice", "tub_lost", "camera_stalled", "no_basket", "made"} <= ends     # 2026-11-24: "could not get the puck back" went on to attempt 2, a pick-up of nothing and a throw at nothing
    assert "fell" not in ends and None not in ends and "ready" not in ends                                                          # a made-ready line-up goes on; a fall is the runner's own stop
