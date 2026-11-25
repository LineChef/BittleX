"""The circling search (behavior/basket_run.circle_search) on a simulated floor: the tub at the origin, G2 somewhere round it, a camera with a 35 degree half view that cannot see a puck behind the tub, movers that do what they are told (pivots, a wide arc of a guessed radius that curves while it turns, a turn that can come up a tenth short)."""
import math
import time
from types import SimpleNamespace as NS

from pi_pipeline.behavior import basket_run as br

TUB_R = 2.75                                                        # the tub's half width, inches


class Sim:
    ARC_RADIUS_IN = 15.0                                            # measured 2026-11-24: a radius near 15 inches

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
        self.last_arc_gyro_deg = self.last_arc_deg
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
    for radius in (10.0, 20.0):                                                               # the arc was measured near 15 inches: the circle must still hold if it is a third off either way
        sim = Sim(puck=None, arc_radius=radius)
        r = br.circle_search(Env(sim), say=lambda s: None)
        radii = [math.hypot(x, y) for x, y in sim.path]
        assert r["outcome"] == "circled_twice" and min(radii) >= 5.0 and max(radii) <= 32.0, (radius, min(radii), max(radii))


def test_a_turn_that_comes_up_short_is_corrected_by_the_next_look():
    sim = Sim(puck=(0.0, 8.0), turn_gain=0.9)
    r = br.circle_search(Env(sim), say=lambda s: None)
    assert r["outcome"] == "found"


def test_the_tub_out_of_view_makes_him_sweep_never_spin_and_a_half_turn_ends_it():
    st = br.CircleState(side=1)
    st.find_forward = br.CIRCLE_FIND_FORWARD_MAX                                              # (the forward steps at the start are the next test)
    a = br.next_circle_action(None, None, st)
    assert a.kind == "pivot" and a.value > 0 and "out of view" in a.why                         # the tub is on his right
    st = br.CircleState(side=-1)
    st.find_forward = br.CIRCLE_FIND_FORWARD_MAX
    assert br.next_circle_action(None, None, st).value < 0
    st = br.CircleState(side=1)
    st.find_forward = br.CIRCLE_FIND_FORWARD_MAX
    acts = [br.next_circle_action(None, None, st) for _ in range(7)]
    assert [a.value for a in acts[:6]] == [30.0, 30.0, -30.0, -30.0, -30.0, -30.0] and acts[6].kind == "give_up"       # on 60 degrees, then back and past the start: 180 degrees of pivots at most
    assert sum(abs(a.value) for a in acts[:6]) == br.CIRCLE_LOST_MAX_DEG
    st = br.CircleState(side=1)                                                                # a peek that turned 90 or more has gone past the tub: back first
    st.phase, st.arcs, st.peek_turn = "look", 1, 108.0
    assert br.next_circle_action(None, None, st).value == -30.0 and st.peek_turn == 78.0


def test_the_tub_not_in_view_at_the_start_makes_him_walk_forward_and_look_again_before_any_pivot():
    st = br.CircleState(side=1)
    acts = [br.next_circle_action(None, None, st) for _ in range(br.CIRCLE_FIND_FORWARD_MAX + 1)]
    assert [a.kind for a in acts[:-1]] == ["forward"] * br.CIRCLE_FIND_FORWARD_MAX and all(a.value == br.CIRCLE_FIND_FORWARD_IN for a in acts[:-1])
    assert acts[-1].kind == "pivot" and st.phase == "face"                                    # still not seen after the forward steps: the sweep
    sim = Sim(puck=None, start=(0.0, -34.0))                                                  # 34 inches out: past the simulated camera range (30), so not seen at first
    r = br.circle_search(Env(sim), say=lambda s: None, ignore_puck=True, max_laps=1000, streak_target=1, deadline=time.monotonic() + 20.0)
    assert r["steps"][0]["action"] == "forward" and r["outcome"] in ("passed", "time_up")
    assert min(math.hypot(x, y) for x, y in sim.path) >= 6.0
    st = br.CircleState(side=1)                                                               # after the start (a peek that lost it) the forward steps are not used
    st.phase = "look"
    assert br.next_circle_action(None, None, st).kind == "pivot"


def test_the_circle_goes_face_square_arc_straight_glance_and_peeks_only_every_few_arcs(monkeypatch):
    monkeypatch.setattr(br, "CIRCLE_STRAIGHT_IN", 6.0)                                           # the straight walk is off by default; this is the walk when it is on
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


def test_a_tub_in_the_forward_picture_is_too_tight_only_near_his_nose_or_near_and_he_turns_away():
    tub = lambda d, b: NS(claw_in=d, bearing_deg=b)                                           # noqa: E731
    for d, b, lo, hi in ((14.0, 5.0, 54, 66), (14.0, 12.0, 54, 66), (11.0, 40.0, 45, 57), (11.5, 60.0, 27, 33)):
        st = br.CircleState(side=1)
        st.phase, st.arcs = "glance", 1
        st.events.append({"arc": 1})
        a = br.next_circle_action(None, tub(d, b), st)
        assert a.kind in ("pivot", "nudge") and a.value < 0 and lo <= abs(a.value) <= hi, (d, b, a)       # away from the tub
        assert st.phase == "arc" and st.soft[-1]["kind"] == "too_tight"
    st = br.CircleState(side=1)
    st.phase, st.arcs = "glance", 1
    st.events.append({"arc": 1})
    a = br.next_circle_action(None, tub(21.0, 35.0), st)                                      # the 2026-11-24 picture: 21 inches, 35 degrees off his nose: the arc brought it forward, the circle is fine
    assert a.kind == "arc" and not st.soft
    st = br.CircleState(side=1)
    st.phase, st.arcs = "glance", 1
    assert br.next_circle_action(None, tub(8.0, 40.0), st).kind == "back"                    # and nearer than the limit he backs off first
    st = br.CircleState(side=-1)
    st.phase, st.arcs = "glance", 1
    st.events.append({"arc": 1})
    assert br.next_circle_action(None, tub(14.0, -5.0), st).value > 0                        # the mirror: the tub on his left, away is to the right


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


def _test_run(sim, **kw):
    kw = {"max_laps": 1000, "peek_every": 3, "ignore_puck": True, "deadline": time.monotonic() + 20.0, **kw}
    return br.circle_search(Env(sim), say=lambda s: None, **kw)


def test_the_circle_test_passes_after_three_clean_laps_in_a_row_on_a_floor_that_holds_the_radius():
    r = _test_run(Sim(puck=None), streak_target=3)
    rep = r["report"]
    assert r["outcome"] == "passed" and rep["streak"] >= 3 and len(rep["laps"]) >= 3
    assert all(lap["clean"] for lap in rep["laps"][-3:])
    assert rep["gyro_over_asked"] == 1.0 and rep["distance_in"]["min"] >= br.CIRCLE_MIN_IN
    assert all("gyro_deg" in e and "straight_in" in e for e in r["arcs"][:-1]) and any("peek" in e for e in r["arcs"])      # every arc was logged, with what each peek read


def test_the_test_ignores_a_puck_and_the_goals_own_defaults_are_unchanged():
    r = _test_run(Sim(puck=(0.0, 8.0)), streak_target=1)
    assert r["outcome"] == "passed"
    r = br.circle_search(Env(Sim(puck=None)), say=lambda s: None)                                    # the goal's call: two laps end it
    assert r["outcome"] == "circled_twice" and len(r["arcs"]) <= 18
    st = br.CircleState()
    assert (st.max_laps, st.peek_every, st.streak_target) == (br.CIRCLE_MAX_LAPS, br.CIRCLE_PEEK_EVERY, 0)


def test_the_clock_ends_the_test_and_a_spoiled_lap_resets_the_streak():
    r = _test_run(Sim(puck=None), deadline=0.0)                                                      # the time is already up
    assert r["outcome"] == "time_up" and r["arcs"] == []
    st = br.CircleState(streak_target=2)
    st.arcs, st.angle_deg = 8, 3 * 360.0
    assert br.clean_streak(st) == 3
    st.note_soft("back_off", d=8.0)                                                                  # during the lap 3 just ended? no: before the first arc nothing counts
    assert st.soft[-1]["lap"] == 3 and br.clean_streak(st) == 3
    st.soft[-1]["lap"] = 1
    assert br.clean_streak(st) == 1 and [row["clean"] for row in br.lap_table(st)] == [True, False, True]
    st = br.CircleState()
    st.note_soft("back_off")                                                                         # before the first arc: the start-up, no lap
    assert st.soft[0]["lap"] == -1 and br.clean_streak(st) == 0


def test_a_back_off_a_tub_in_the_forward_picture_and_a_peek_out_of_band_are_soft_failures():
    tub = lambda d, b: NS(claw_in=d, bearing_deg=b)                                                  # noqa: E731
    st = br.CircleState(side=1)
    st.phase, st.arcs = "glance", 1
    st.events.append({"arc": 1})
    br.next_circle_action(None, tub(8.0, 40.0), st)
    br.next_circle_action(None, tub(14.0, 10.0), st)
    st.phase = "look"
    br.next_circle_action(None, tub(24.0, 30.0), st)
    assert [s["kind"] for s in st.soft] == ["back_off", "too_tight", "out_of_band"]
    assert st.events[0]["peek"] == (24.0, 30.0)


def test_there_is_no_straight_walk_by_default_and_the_arc_goes_straight_to_the_glance():
    assert br.CIRCLE_STRAIGHT_IN == 0.0
    st = br.CircleState(side=1)
    st.phase = "arc"
    assert br.next_circle_action(None, None, st).kind == "arc" and st.phase == "glance" and st.events[0]["straight_in"] == 0.0     # no 'forward 0 inches': a zero walk still walks (the slow start)
    r = _test_run(Sim(puck=None), streak_target=1)
    assert all(s["action"] != "forward" for s in r["steps"])


def test_the_straight_walk_is_the_default_unless_the_gain_is_on_and_the_reading_is_fresh(monkeypatch):
    monkeypatch.setattr(br, "CIRCLE_STRAIGHT_IN", 6.0)
    assert br.straight_for(None) == br.CIRCLE_STRAIGHT_IN and br.straight_for(10.0) == br.CIRCLE_STRAIGHT_IN                 # gain 0: off
    monkeypatch.setattr(br, "CIRCLE_STRAIGHT_GAIN", 0.5)
    assert br.straight_for(10.0) == br.CIRCLE_STRAIGHT_IN + 3.0 and br.straight_for(30.0) == br.CIRCLE_STRAIGHT_MIN_IN
    assert br.straight_for(0.0) == br.CIRCLE_STRAIGHT_MAX_IN


def test_a_camera_stall_and_a_fall_end_the_test_with_their_own_outcome():
    class Stall(Env):
        def look(self):
            raise br.CameraStalled()
    assert br.circle_search(Stall(Sim()), say=lambda s: None, ignore_puck=True)["outcome"] == "camera_stalled"
    sim = Sim()
    sim.pivot = lambda deg: "fell"
    assert _test_run(sim, streak_target=3)["outcome"] == "fell"


def test_the_end_of_run_summary_lists_every_lap_and_arc():
    r = _test_run(Sim(puck=None), streak_target=1)
    lines = br.circle_report_lines(r)
    assert lines[0].startswith("CIRCLE TEST passed") and any("lap 1:" in x for x in lines) and any("arc 1:" in x for x in lines)


def test_the_peek_learns_how_far_to_turn_from_the_signed_bearing_and_clamps_it():
    tub = lambda d, b: NS(claw_in=d, bearing_deg=b)                                                  # noqa: E731
    st = br.CircleState(side=1)
    st.phase, st.arcs = "peek", 1
    assert br.next_circle_action(None, None, st).value == br.bl._pivot_for(br.CIRCLE_PEEK_DEG) and st.peek_turn == br.CIRCLE_PEEK_DEG
    br.next_circle_action(None, None, st)                                                            # not in view: one step on toward the tub
    assert st.peek_turn == br.CIRCLE_PEEK_DEG + br.CIRCLE_LOST_STEP_DEG
    br.next_circle_action(None, tub(14.0, 14.0), st)                                                 # found 14 degrees to the right after 90: it stood 104 off before the peek
    assert abs(st.peek_deg - (14.0 + 90.0 - br.CIRCLE_PEEK_TARGET_DEG)) < 1e-6
    st.phase, st.arcs = "peek", 2
    assert br.next_circle_action(None, None, st).value == br.bl._pivot_for(st.peek_deg)
    st = br.CircleState(side=1)                                                                      # the tub past his nose (to the left) after the peek: it stood nearer than the peek turned
    st.phase, st.peek_turn = "look", 108.0
    a = br.next_circle_action(None, tub(14.0, -18.0), st)
    assert abs(st.peek_deg - (-18.0 + 108.0 - br.CIRCLE_PEEK_TARGET_DEG)) < 1e-6 and a.value < 0 and abs(a.value) > 90                       # a longer turn back, not a shorter one
    st = br.CircleState(side=1)
    st.phase, st.peek_turn = "look", 300.0
    br.next_circle_action(None, tub(14.0, 0.0), st)
    assert st.peek_deg == br.CIRCLE_PEEK_MAX_DEG


def test_every_look_is_logged_with_how_long_the_picture_took_and_whether_one_came():
    class Timed(Env):
        last_look_s, last_quick_failed = 0.8, False

        def look(self):
            self.last_look_s = 0.8
            return self.sim.look()
    r = br.circle_search(Timed(Sim()), say=lambda s: None, ignore_puck=True, max_laps=1000, peek_every=3, streak_target=1)
    rep = r["report"]
    assert rep["look_s"]["n"] == len(rep["looks"]) >= 10 and rep["look_s"]["misses"] == 0 and rep["look_s"]["max"] == 0.8
    assert any("looks (picture waits" in x for x in br.circle_report_lines(r))
    assert br.AFTER_PICTURE_TIMEOUT_S == 4.0 and br.STAND_IDLE_REST_S == 6.0


def test_a_look_with_no_picture_after_six_seconds_standing_lies_him_down_and_the_next_move_stands_him_up():
    class Robot:
        posture, _moved_at = "stand", 100.0

        def _clock(self):
            return self.now
        now = 100.0

        def stand_up_from_rest(self):
            self.posture = "stand"
            self.ups = getattr(self, "ups", 0) + 1
            return "ok"

    env = br.RealEnv.__new__(br.RealEnv)
    env.robot = Robot()
    laid = []
    env.lie_down = lambda: (laid.append(1), setattr(env.robot, "posture", "rest"))
    env.robot.now = 105.0
    assert env.idle_stand_s() == 5.0 and env._rest_if_idle() is False and not laid                  # stood 5 s: not yet
    env.robot.now = 106.5
    assert env._rest_if_idle() is True and laid == [1] and env.idle_rests == 1                       # 6.5 s with no picture: lie down
    assert env.idle_stand_s() is None                                                                # lying: not standing idle
    env.ready_to_move()
    assert env.robot.ups == 1 and env.robot.posture == "stand"                                       # the next move stands him up first
    env.ready_to_move()
    assert env.robot.ups == 1


def test_the_circle_stands_him_up_before_a_move_when_a_look_laid_him_down():
    class Ready(Env):
        def __init__(self, sim):
            super().__init__(sim)
            self.ready = 0

        def ready_to_move(self):
            self.ready += 1
    env = Ready(Sim())
    r = br.circle_search(env, say=lambda s: None, ignore_puck=True, max_laps=1000, streak_target=1, deadline=time.monotonic() + 20.0)
    assert env.ready >= len([s for s in r["steps"] if s["action"] not in ("give_up", "found")])
