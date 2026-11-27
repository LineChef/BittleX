"""The pick-up drill (goals/pickup.py): setups spoken in plain terms, scoring from the retrieval's outcome, and a trial that runs the basket goal's own retrieval."""
from pi_pipeline.behavior import basket_run as br
from pi_pipeline.goals import approach, pickup, spec
from pi_pipeline.goals.approach import AttemptContext, AttemptResult


def test_the_drill_is_registered_and_started_by_its_words():
    assert approach.make("pickup").name == "pickup"
    g = spec.BUILTIN["pickup"]
    assert spec.goal_for_words("pick up drill", spec.BUILTIN) is g and g.target_successes is None


def test_a_setup_is_said_as_distance_ahead_and_side():
    assert pickup.spot_words((8.0, 0.0)) == "8 inches ahead of the claw, centred"
    assert pickup.spot_words((10.0, -15.0)) == "10 inches ahead of the claw, to the left"
    assert pickup.spot_words((10.0, 15.0)) == "10 inches ahead of the claw, to the right"


def test_scoring_follows_the_retrieval_and_a_failed_pickup_does_not_end_the_drill():
    a = pickup.PickupDrill()
    s = a.base_settings()
    assert set(s) == {"pick_undershoot_in", "blind_step_in"}
    rec = {"setup": {"ahead_in": 8.0, "bearing_deg": 0.0}, "retrieval": {"steps": [1, 2]}}

    def res(ended):
        return AttemptResult(ended, 30.0, [], {"rec": rec})
    o = a.score(res("retrieved"), s)
    assert o.success and o.score == 1.0 and o.stages == {"retrieve": 1.0}
    for ended in ("pick_failed", "could_not_reach_puck", "puck_not_found"):
        o = a.score(res(ended), s)
        assert not o.success and o.score == 0.0 and o.stages == {"retrieve": 0.0} and ended not in a.ends_session
    assert a.score(res("stopped"), s).score is None and a.score(res("fell"), s).code == "fell"


class Mover:
    def __init__(self, calls):
        self.calls = calls

    def back(self, inches):
        self.calls.append(f"back {inches:g}")
        return "ok"

    def pivot(self, deg):
        self.calls.append(f"pivot {deg:g}")
        return "ok"


class Env:
    def __init__(self, calls, drop_state="ok"):
        self.calls, self.mover, self.drop_state = calls, Mover(calls), drop_state

    def lie_down(self):
        self.calls.append("lie")

    def ready_to_move(self):
        self.calls.append("ready")

    def claw_to(self, lift):
        self.calls.append(f"claw {lift:g}")
        return "ok"

    def tilt_now(self):
        return (1.5, -2.0)

    def drop(self):
        self.calls.append("drop")
        return self.drop_state


def test_the_first_trial_asks_for_the_puck_then_each_pickup_ends_with_a_drop_a_back_up_and_a_turn_and_the_next_trial_goes_straight_on(monkeypatch):
    calls = []
    outcomes = iter(["retrieved", "retrieved", "puck_not_found", "retrieved"])

    def fake_retrieve(env, say=print, on_step=None, first=None, announce=None):
        calls.append("retrieve")
        return {"outcome": next(outcomes), "steps": []}
    monkeypatch.setattr(br, "retrieve", fake_retrieve)
    monkeypatch.setattr(pickup, "PLACE_WAIT_S", 0.0)
    said, spoken = [], []
    a = pickup.PickupDrill(env=Env(calls))
    ctx = AttemptContext(stop=lambda: False, say=said.append, announce=spoken.append)
    r = a.run_attempt(a.base_settings(), ctx)
    assert r.ended == "retrieved" and calls == ["lie", "retrieve", "drop", "ready", "claw 45", "back 6", "claw 0"]            # turn 0: no pivot; the claw clear of the floor for the back-up (the puck lies under it) then down
    assert spoken == ["Put the puck 8 inches ahead of the claw, centred."]
    tilts = a._recs[-1]["tilts"] if a._recs else None
    assert tilts and [t[0] for t in tilts][:3] == ["after the drop (attention pose)", "after the stand-up", "claw at 45"] and tilts[0][1:3] == [1.5, -2.0] and "_t0" not in a._recs[-1]
    calls.clear()
    r = a.run_attempt(a.base_settings(), ctx)                                                     # no one touches the puck: straight on
    assert r.ended == "retrieved" and calls == ["retrieve", "drop", "ready", "claw 45", "back 9", "pivot 15", "claw 0"] and len(spoken) == 1
    calls.clear()
    r = a.run_attempt(a.base_settings(), ctx)                                                     # he could not find it: lies down, and the next trial asks again
    assert r.ended == "puck_not_found" and calls == ["retrieve", "lie"]
    calls.clear()
    a.run_attempt(a.base_settings(), ctx)
    assert calls[:2] == ["lie", "retrieve"] and spoken[-1].startswith("Put the puck")
    r2 = a.run_attempt(a.base_settings(), AttemptContext(stop=lambda: True, say=said.append))
    assert r2.ended == "stopped"


def test_a_fall_in_the_drop_ends_the_trial_as_a_fall(monkeypatch):
    calls = []
    monkeypatch.setattr(br, "retrieve", lambda *a, **k: {"outcome": "retrieved", "steps": []})
    monkeypatch.setattr(pickup, "PLACE_WAIT_S", 0.0)
    a = pickup.PickupDrill(env=Env(calls, drop_state="fell"))
    r = a.run_attempt(a.base_settings(), AttemptContext(stop=lambda: False, say=lambda s: None))
    assert r.ended == "fell" and "back 6" not in calls
