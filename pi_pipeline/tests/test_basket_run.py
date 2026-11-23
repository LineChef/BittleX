"""The full basket sequence (behavior/basket_run.py) on a simulated floor: the retrieval decisions, the classification after a throw, and the attempts loop with a fake robot, camera and throw."""
from pi_pipeline.behavior import basket_lineup as bl
from pi_pipeline.behavior import basket_run as br
from pi_pipeline.goals import basket_outcome as bo


class P:                                  # a puck reading
    def __init__(self, d, b, w=14, h=14):
        self.claw_in, self.bearing_deg, self.x, self.y, self.width_px, self.height_px, self.area, self.touches_edge = d, b, 120.0 + 2.4 * b, 150.0, w, h, w * h, False


class B(P):                               # a basket reading
    def __init__(self, d, b, x=120.0, y=110.0):
        super().__init__(d, b, 36, 28)
        self.x, self.y = x, y


def act(puck, basket=None, st=None):
    return br.next_retrieval_action(puck, basket, st or br.RState())


def test_the_retrieval_decisions():
    assert act(None).kind == "scan"
    st = br.RState()
    kinds = [br.next_retrieval_action(None, None, st).kind for _ in range(16)]
    assert kinds[:14] == ["scan"] * 14 and kinds[14] == "give_up"                                  # 14 x 27 degrees covers a full circle
    assert act(P(20.0, 40.0)).kind == "pivot" and act(P(20.0, -40.0)).value < 0
    a = act(P(20.0, 10.0))
    assert a.kind == "nudge" and a.value == 10.0
    a = act(P(20.0, 2.0))
    assert a.kind == "forward" and a.value == br.APPROACH_STEP_MAX_IN                                 # a long way: the step cap
    a = act(P(11.0, 2.0))
    assert a.kind == "forward" and abs(a.value - (11.0 - br.PICK_STAND_IN)) < 1e-9
    a = act(P(6.5, 1.0))
    assert a.kind == "pick" and abs(a.value - (6.5 - br.PICK_UNDERSHOOT_IN)) < 1e-9                   # the last walk stops short of the finder's distance
    assert act(P(0.2, 0.0)).value == 0.0
    assert act(P(20.0, 0.0), B(7.0, 0.0)).value == 0.0 and act(P(20.0, 0.0), B(7.0, 0.0)).why == "too_near_the_basket"     # never walks on toward a basket inside the buffer
    st = br.RState(steps=br.MAX_RETRIEVAL_STEPS)
    assert act(P(20.0, 0.0), None, st).why == "could_not_reach_puck"


def test_the_throw_is_classified_from_the_look_afterwards():
    basket = B(16.0, 0.0)
    assert br.classify_after(basket, None)[0] == bo.NOT_SEEN                                         # nothing seen: a make or a lost puck
    assert br.classify_after(basket, P(18.0, 20.0))[0] == bo.MISSED                                  # on the floor outside the basket
    inside = P(16.0, 0.0, 6, 6)
    inside.x, inside.y = basket.x, basket.y
    assert br.classify_after(basket, inside)[0] == bo.MADE
    assert br.classify_after(None, P(10.0, 5.0))[0] == bo.MISSED                                     # a puck on the floor and no basket in view is still a miss
    assert br.classify_after(None, None)[0] == bo.NO_BASKET


class World:
    """One puck on the floor and one basket, seen from G2 (distances from the claw tip, bearings to the right)."""

    def __init__(self, puck=None, basket=(16.0, 0.0)):
        self.puck, self.basket = puck, basket
        self.moves = []

    def mover_call(self, kind, v):
        self.moves.append((kind, round(v, 1)))
        if kind == "forward" and self.puck:
            self.puck = (max(0.0, self.puck[0] - v), self.puck[1])
            self.basket = (self.basket[0] + v * 0.0, self.basket[1])
        if kind in ("pivot", "nudge", "scan") and self.puck:
            self.puck = (self.puck[0], self.puck[1] - v)
        if kind == "back":
            self.basket = (self.basket[0] + v, self.basket[1])
        return "ok"


class Mover:
    def __init__(self, w):
        self.w = w
        for k in ("scan", "pivot", "nudge", "forward", "back"):
            setattr(self, k, (lambda kind: lambda v: self.w.mover_call(kind, v))(k))


class Env:
    def __init__(self, throws, puck_after=None, pick_works=True, fell_in_look=False, battery=True, basket_start=(16.0, 0.0)):
        self.w = World(None, basket_start)
        self.mover = Mover(self.w)
        self.throws, self.puck_after, self.pick_works, self.fell_in_look, self.battery, self.thrown = list(throws), list(puck_after or []), pick_works, fell_in_look, battery, []
        self.picks = 0

    def battery_ok(self):
        return self.battery

    def throw(self, holding):
        self.thrown.append(holding)
        t = self.throws.pop(0)
        self.w.puck = self.puck_after.pop(0) if t.get("ok") and self.puck_after else None
        return t

    def look(self):
        from pi_pipeline.behavior.basket_run import Fell
        if self.fell_in_look:
            raise Fell()
        basket = B(*self.w.basket) if self.w.basket else None
        puck = P(*self.w.puck) if self.w.puck else None
        return basket, puck

    def quick_basket(self):
        return B(*self.w.basket) if self.w.basket else None

    def pick(self):
        self.picks += 1
        if self.pick_works:
            self.w.puck = None
        return "ok"


def ok(**k):
    return {"ok": True, **k}


def test_a_throw_that_is_not_seen_afterwards_stops_for_the_owners_reset():
    env = Env([ok()], puck_after=[None])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "made_or_lost" and len(r["attempts"]) == 1 and env.thrown == [False]


def test_a_miss_is_searched_picked_up_lined_up_and_thrown_again_without_a_pick_up():
    env = Env([ok(), ok()], puck_after=[(24.0, 25.0), None])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "made_or_lost" and len(r["attempts"]) == 2
    assert env.thrown == [False, True]                                                           # the second throw is from a puck already held
    a1 = r["attempts"][0]
    assert a1["after"]["code"] == bo.MISSED and a1["retrieval"]["outcome"] == "retrieved" and a1["lineup"]["outcome"] == "aligned"
    kinds = [m[0] for m in env.w.moves]
    assert "pivot" in kinds and "forward" in kinds and env.picks == 1
    assert abs(env.w.basket[0] - bl.TARGET_IN) <= bl.DIST_TOL_IN                                 # ends lined up at the shot distance


def test_the_stops():
    assert br.run_sequence(Env([ok()], battery=False), say=lambda s: None)["outcome"] == "battery"
    assert br.run_sequence(Env([{"ok": True, "fell": True}]), say=lambda s: None)["outcome"] == "fell"
    assert br.run_sequence(Env([{"ok": False}]), say=lambda s: None)["outcome"] == "throw_failed"
    assert br.run_sequence(Env([ok()], fell_in_look=True), say=lambda s: None)["outcome"] == "fell"
    r = br.run_sequence(Env([ok()], puck_after=[(24.0, 0.0)], pick_works=False), say=lambda s: None)
    assert r["outcome"] == "pick_failed" and r["attempts"][0]["retrieval"]["steps"][-1]["why"] == "puck still on the floor"
    r = br.run_sequence(Env([ok(), ok(), ok()], puck_after=[(24.0, 0.0)] * 3), max_attempts=2, say=lambda s: None)
    assert r["outcome"] == "max_attempts" and len(r["attempts"]) == 2
    r = br.run_sequence(Env([ok()], puck_after=[(20.0, 0.0)], basket_start=(6.0, 0.0)), say=lambda s: None)
    assert r["outcome"] == "too_near_the_basket"                                                  # a puck lying in front of a basket that close is not walked to


def test_a_fall_in_a_mover_ends_the_retrieval():
    env = Env([ok()], puck_after=[(24.0, 0.0)])
    env.mover.forward = lambda v: "fell"
    assert br.run_sequence(env, say=lambda s: None)["outcome"] == "fell"


def test_the_looks_are_merged_into_one_body_frame_reading():
    from pi_pipeline.vision import basket_finder as bf, puck_finder as pf
    puck = lambda d, b: pf.PuckReading(120.0, 130.0, 14, 14, 150, b, d)                                       # noqa: E731
    basket = lambda d, b: bf.BasketReading(120.0, 110.0, 36, 28, b, d + 2, d, False)                          # noqa: E731
    offsets = {"look_left": -35.0, "look_right": 35.0, "centre": 0.0}
    seen = {"look_left": (None, puck(14.0, 5.0)), "look_right": (basket(30.0, -4.0), None), "centre": (basket(18.0, 1.0), puck(20.0, 2.0))}
    b, p = br.merge_looks(seen, offsets)
    assert b.claw_in == 18.0 and b.bearing_deg == 1.0                                                         # the centre picture's basket first
    assert p.claw_in == 14.0 and p.bearing_deg == -30.0                                                       # the nearest puck, in the body frame: 5 degrees right of a picture pointing 35 left
    assert br.merge_looks({}, offsets) == (None, None)
    b, p = br.merge_looks({"look_right": (basket(30.0, -4.0), None)}, offsets)
    assert b.bearing_deg == 31.0 and p is None
