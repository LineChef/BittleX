"""The circling search (behavior/basket_run.circle_search) on a simulated floor: the tub at the origin, G2 somewhere round it, a camera with a 35 degree half view that cannot see a puck behind the tub, movers that do exactly what they are told (plus a turn that comes up a tenth short)."""
import math
from types import SimpleNamespace as NS

from pi_pipeline.behavior import basket_run as br

TUB_R = 2.75                                                        # the tub's half width, inches


class Sim:
    def __init__(self, puck=None, start=(0.0, -9.0), heading=0.0, turn_gain=1.0):
        self.x, self.y, self.h, self.puck, self.turn_gain = start[0], start[1], heading, puck, turn_gain
        self.path = [start]
        self.legs = 0

    def _bearing(self, px, py):
        b = math.degrees(math.atan2(px - self.x, py - self.y)) - self.h
        return (b + 180.0) % 360.0 - 180.0

    def look(self):
        dt = math.hypot(self.x, self.y)
        bt = self._bearing(0.0, 0.0)
        tub = NS(claw_in=dt, bearing_deg=bt) if abs(bt) <= 35.0 and dt <= 30.0 else None
        puck = None
        if self.puck is not None:
            dp = math.hypot(self.puck[0] - self.x, self.puck[1] - self.y)
            bp = self._bearing(*self.puck)
            hidden = dp > dt and abs(bp - bt) <= math.degrees(math.atan2(TUB_R, dt))                  # behind the tub
            if abs(bp) <= 35.0 and dp <= 16.0 and not hidden:
                puck = NS(claw_in=dp, bearing_deg=bp)
        return tub, puck

    def move(self, d):
        self.x += d * math.sin(math.radians(self.h))
        self.y += d * math.cos(math.radians(self.h))
        self.path.append((self.x, self.y))

    def pivot(self, deg):
        self.h += deg * self.turn_gain
        return "ok"

    nudge = scan = pivot

    def forward(self, v):
        self.legs += 1
        self.move(v)
        return "ok"

    def back(self, v):
        self.move(-v)
        return "ok"


class Env:
    def __init__(self, sim):
        self.sim, self.mover = sim, sim

    def look(self):
        return self.sim.look()


def test_a_puck_behind_the_tub_is_found_by_circling_and_he_never_comes_inside_the_buffer():
    for puck in ((0.0, 8.0), (-8.0, 2.0), (7.0, -3.0), (4.0, 6.0)):
        sim = Sim(puck=puck)
        r = br.circle_search(Env(sim), say=lambda s: None)
        assert r["outcome"] == "found", (puck, r["outcome"], r["steps"][-1])
        assert min(math.hypot(x, y) for x, y in sim.path) >= 6.0, puck                          # never inside the line-up's 6 inch buffer


def test_with_no_puck_anywhere_it_ends_after_two_laps_and_stays_round_the_tub():
    sim = Sim(puck=None)
    r = br.circle_search(Env(sim), say=lambda s: None)
    assert r["outcome"] == "circled_twice" and r["steps"][-1]["angle_deg"] >= 720
    radii = [math.hypot(x, y) for x, y in sim.path]
    assert min(radii) >= 6.0 and max(radii) <= 26.0                                           # the circle holds its radius
    total = sum(1 for s in r["steps"] if s["action"] == "forward")
    assert 20 <= total <= 40                                                                  # about two laps of 6 inch legs round a 13 inch circle


def test_a_turn_that_comes_up_short_is_corrected_by_the_next_look():
    sim = Sim(puck=(0.0, 8.0), turn_gain=0.9)
    r = br.circle_search(Env(sim), say=lambda s: None)
    assert r["outcome"] == "found"


def test_the_tub_out_of_view_makes_him_pivot_toward_the_side_it_should_be_on_and_a_full_turn_ends_it():
    st = br.CircleState(side=1)
    a = br.next_circle_action(None, None, st)
    assert a.kind == "pivot" and a.value < 0 and "out of view" in a.why                         # a leg turned right, so the tub is on his left
    st = br.CircleState(side=-1)
    assert br.next_circle_action(None, None, st).value > 0
    st = br.CircleState(side=1)
    kinds = [br.next_circle_action(None, None, st).kind for _ in range(13)]
    assert kinds[:12] == ["pivot"] * 12 and kinds[12] == "give_up"                            # 12 x 30 degrees is a full turn
    assert br.next_circle_action(None, None, br.CircleState()).why != "tub_lost"


def test_a_puck_in_view_ends_the_search_and_too_near_the_tub_backs_off_first():
    st = br.CircleState()
    assert br.next_circle_action(NS(claw_in=10.0, bearing_deg=3.0), NS(claw_in=14.0, bearing_deg=0.0), st).kind == "found"
    a = br.next_circle_action(None, NS(claw_in=7.0, bearing_deg=2.0), br.CircleState())
    assert a.kind == "back" and a.value > 0
