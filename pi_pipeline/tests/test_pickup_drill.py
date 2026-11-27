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


def test_a_trial_says_the_setup_waits_runs_the_shared_retrieval_and_lies_down_holding_the_puck(monkeypatch):
    calls = []

    class Env:
        def lie_down(self):
            calls.append("lie")

    def fake_retrieve(env, say=print, on_step=None, first=None, announce=None):
        calls.append("retrieve")
        return {"outcome": "retrieved", "steps": []}
    monkeypatch.setattr(br, "retrieve", fake_retrieve)
    monkeypatch.setattr(pickup, "PLACE_WAIT_S", 0.0)
    said, spoken = [], []
    a = pickup.PickupDrill(env=Env())
    r = a.run_attempt(a.base_settings(), AttemptContext(stop=lambda: False, say=said.append, announce=spoken.append))
    assert r.ended == "retrieved" and calls == ["lie", "retrieve", "lie"]
    assert spoken[0] == "Put the puck 8 inches ahead of the claw, centred." and "Take it out" in spoken[-1]
    r2 = a.run_attempt(a.base_settings(), AttemptContext(stop=lambda: True, say=said.append))
    assert r2.ended == "stopped"                                                                      # a stop is read before the setup is said
