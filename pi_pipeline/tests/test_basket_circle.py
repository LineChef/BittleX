"""The circling search (behavior/basket_run.circle_search) on a simulated floor: the tub at the origin, G2 somewhere round it, a camera with a 35 degree half view that cannot see a puck behind the tub, movers that do what they are told (pivots, a wide arc of a guessed radius that curves while it turns, a turn that can come up a tenth short)."""
import math
from types import SimpleNamespace as NS

from pi_pipeline.behavior import basket_run as br

TUB_R = 2.75                                                        # the tub's half width, inches


class Sim:
    ARC_RADIUS_IN = 8.6                                             # a first guess: about 4 inches a second at about 28 degrees a second

    def __init__(self, puck=None, start=(0.0, -13.0), heading=0.0, turn_gain=1.0, arc_radius=None):
        self.x, self.y, self.h, self.puck, self.turn_gain = start[0], start[1], heading, puck, turn_gain
        self.arc_radius = arc_radius or self.ARC_RADIUS_IN
        self.path = [start]
        self.legs = 0
        self.last_arc_deg = 0.0

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

    def arc(self, deg):
        """A wide turn: forward along a circle of `arc_radius` while the heading changes by `deg` (+ right), in 5 degree pieces."""
        sign = 1 if deg > 0 else -1
        done = 0.0
        while done < abs(deg) - 1e-9:
            step = min(5.0, abs(deg) - done)
            self.move(self.arc_radius * math.radians(step))
            self.h += sign * step * self.turn_gain
            done += step
        self.legs += 1
        self.last_arc_deg = done * self.turn_gain
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


def test_with_no_puck_anywhere_it_ends_after_two_laps_of_wide_arcs_and_stays_round_the_tub():
    sim = Sim(puck=None)
    r = br.circle_search(Env(sim), say=lambda s: None)
    arcs = [s for s in r["steps"] if s["action"] == "arc"]
    assert r["outcome"] == "circled_twice" and r["steps"][-1]["angle_deg"] >= 720
    assert 14 <= len(arcs) <= 18                                                              # 45 degrees each: two laps are 16 arcs
    radii = [math.hypot(x, y) for x, y in sim.path]
    assert min(radii) >= 6.0 and max(radii) <= 28.0                                           # the circle holds its radius (the correction works from the tub's distance at each look)


def test_a_wider_or_narrower_arc_than_guessed_is_corrected_by_the_looks():
    for radius in (6.0, 12.0):                                                                # the true arc radius is not measured: the circle must not depend on the guess
        sim = Sim(puck=None, arc_radius=radius)
        r = br.circle_search(Env(sim), say=lambda s: None)
        radii = [math.hypot(x, y) for x, y in sim.path]
        assert r["outcome"] == "circled_twice" and min(radii) >= 5.0 and max(radii) <= 32.0, (radius, min(radii), max(radii))


def test_a_turn_that_comes_up_short_is_corrected_by_the_next_look():
    sim = Sim(puck=(0.0, 8.0), turn_gain=0.9)
    r = br.circle_search(Env(sim), say=lambda s: None)
    assert r["outcome"] == "found"


def test_the_tub_out_of_view_makes_him_pivot_toward_its_side_and_a_full_turn_ends_it():
    st = br.CircleState(side=1)
    a = br.next_circle_action(None, None, st)
    assert a.kind == "pivot" and a.value > 0 and "out of view" in a.why                         # the tub is on his right
    st = br.CircleState(side=-1)
    assert br.next_circle_action(None, None, st).value < 0
    st = br.CircleState(side=1)
    kinds = [br.next_circle_action(None, None, st).kind for _ in range(13)]
    assert kinds[:12] == ["pivot"] * 12 and kinds[12] == "give_up"                            # 12 x 30 degrees is a full turn


def test_the_circle_goes_face_square_arc_straight_glance_and_peeks_only_every_few_arcs():
    st = br.CircleState(side=1)
    tub = lambda d, b: NS(claw_in=d, bearing_deg=b)                                           # noqa: E731
    assert br.next_circle_action(None, tub(16.0, 20.0), st).why == "circling: face the tub"
    a = br.next_circle_action(None, tub(16.0, 2.0), st)
    assert a.kind == "pivot" and a.value < 0 and abs(a.value) >= 54 and st.phase == "arc"     # the tub goes to his right: a turn to the left of about 90
    a = br.next_circle_action(None, None, st)
    assert a.kind == "arc" and a.value == br.CIRCLE_ARC_DEG and st.phase == "straight"       # one wide arc toward the tub
    a = br.next_circle_action(None, None, st)
    assert a.kind == "forward" and a.value == br.CIRCLE_STRAIGHT_IN and st.phase == "glance"  # a straight walk widens it
    a = br.next_circle_action(None, None, st)                                                 # the forward picture shows no tub: the circle is not too tight
    assert a.kind == "arc" and st.phase == "straight"
    for _ in range(2):                                                                        # arcs 2 and 3
        br.next_circle_action(None, None, st)
        br.next_circle_action(None, None, st)
        st.phase = "glance" if st.phase != "glance" else st.phase
    st.arcs = br.CIRCLE_PEEK_EVERY
    st.phase = "glance"
    a = br.next_circle_action(None, None, st)
    assert a.kind == "pivot" and a.value > 0 and st.phase == "look"                           # every third arc: turn toward the tub to look
    a = br.next_circle_action(None, tub(16.0, 30.0), st)
    assert a.kind == "pivot" and a.value < 0 and abs(a.value) >= 54 and st.phase == "arc"     # back by (90 - 30) at the right radius
    st.phase = "look"
    a2 = br.next_circle_action(None, tub(10.5, 30.0), st)
    assert abs(a2.value) >= abs(a.value)                                                      # too near: turns back further, away from the tub
    st.phase = "look"
    wide = br.next_circle_action(None, tub(40.0, 30.0), st)
    assert abs(wide.value) >= 27 and abs(wide.value) <= abs(a.value)                          # too wide is corrected only a little, never by much


def test_a_tub_in_the_forward_picture_means_too_tight_and_he_turns_away_by_how_far_forward_it_stands():
    tub = lambda d, b: NS(claw_in=d, bearing_deg=b)                                           # noqa: E731
    for b, lo, hi in ((30.0, 54, 66), (60.0, 27, 33), (85.0, 15, 27)):
        st = br.CircleState(side=1)
        st.phase, st.arcs = "glance", 1
        a = br.next_circle_action(None, tub(14.0, b), st)
        assert a.kind in ("pivot", "nudge") and a.value < 0 and lo <= abs(a.value) <= hi, (b, a)   # away from the tub, more the further forward it stands
        assert st.phase == "arc"
    st = br.CircleState(side=1)
    st.phase, st.arcs = "glance", 1
    assert br.next_circle_action(None, tub(8.0, 40.0), st).kind == "back"                    # and nearer than the limit he backs off first
    st = br.CircleState(side=-1)
    st.phase, st.arcs = "glance", 1
    assert br.next_circle_action(None, tub(14.0, -30.0), st).value > 0                       # the mirror: the tub on his left, away is to the right


def test_a_puck_in_view_ends_the_search_and_too_near_the_tub_backs_off_first():
    st = br.CircleState()
    assert br.next_circle_action(NS(claw_in=10.0, bearing_deg=3.0), NS(claw_in=14.0, bearing_deg=0.0), st).kind == "found"
    a = br.next_circle_action(None, NS(claw_in=7.0, bearing_deg=2.0), br.CircleState())
    assert a.kind == "back" and a.value > 0


def test_a_puck_seen_with_the_tub_out_of_view_this_near_is_the_tubs_own_tape():
    class E:
        def __init__(self):
            self.looks = [(NS(claw_in=11.0, bearing_deg=0.0), None), (None, NS(claw_in=4.1, bearing_deg=-30.0)), (None, None)]
            self.mover = type("M", (), {"pivot": lambda s, v: "ok", "nudge": lambda s, v: "ok", "back": lambda s, v: "ok", "arc": lambda s, v: "ok", "forward": lambda s, v: "ok", "set_distance": lambda s, v: None, "last_arc_deg": 45.0})()

        def look(self):
            return self.looks.pop(0) if self.looks else (None, None)
    r = br.circle_search(E(), say=lambda s: None)
    assert r["outcome"] != "found" and r["puck"] is None                                       # the 4 inch "puck" beside a tub read 11 inches a moment ago was not chased
