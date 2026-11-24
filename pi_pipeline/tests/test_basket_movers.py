"""The basket movers (behavior/basket_movers.py) on a fake robot: the measured back-up table, the forward pace and the turns, with the line-up loop in front."""
from pi_pipeline.behavior import ball_chase as chase
from pi_pipeline.behavior import basket_lineup as bl
from pi_pipeline.behavior import basket_movers as bm
from pi_pipeline.behavior import chase_pace


class FakeRobot:
    def __init__(self, fall_on=None):
        self.calls, self.fall_on = [], fall_on

    def _do(self, name, *a, **k):
        self.calls.append((name, a, k))
        return "fell" if self.fall_on == name else "ok"

    def walk(self, seconds):
        return self._do("walk", seconds)

    def walk_scripted(self, seconds):
        return self._do("walk_scripted", seconds)

    def back(self, seconds):
        return self._do("back", seconds)

    def turn(self, degrees, seconds, stop_deg=0.0):
        return self._do("turn", degrees, seconds, stop_deg=stop_deg)


def test_the_back_up_table_reproduces_the_measured_runs_and_inverts():
    for secs, inches in bm.BACK_POINTS:
        assert abs(bm.back_inches(secs) - inches) < 1e-9
        if inches <= bm.BACK_MAX_IN:
            assert abs(bm.back_seconds(inches) - secs) < 1e-9
    assert bm.back_seconds(15.3) == bm.back_seconds(bm.BACK_MAX_IN)                  # past the cap on one step
    assert bm.back_seconds(0.5) == bm.BACK_MIN_S == 1.0                              # under the shortest measured run: that run
    assert bm.back_seconds(6.0) < bm.back_seconds(9.3) == 2.0 < bm.back_seconds(12.0) < 3.0
    assert bm.back_seconds(99) == bm.back_seconds(bm.BACK_MAX_IN)                    # a safety cap on one step
    for inches in (1.5, 3.0, 6.0, 10.0):
        assert abs(bm.back_inches(bm.back_seconds(inches)) - max(inches, bm.BACK_POINTS[0][1])) < 1e-9


def test_the_movers_send_the_walks_and_turns_the_ball_goal_uses():
    r = FakeRobot()
    m = bm.BasketMover(r)
    assert m.back(6.0) == "ok" and r.calls[-1][0] == "back" and abs(r.calls[-1][1][0] - bm.back_seconds(6.0)) < 1e-9
    m.forward(6.0)
    assert r.calls[-1][0] == "walk_scripted" and abs(r.calls[-1][1][0] - bm.forward_seconds(6.0)) < 1e-9
    m.forward(0.5)
    assert r.calls[-1][1][0] == chase.MIN_MOVE_S
    m.pivot(27.0)
    name, (deg, secs), kw = r.calls[-1]
    assert name == "turn" and deg == 27.0 and kw["stop_deg"] == 27.0 and secs == max(chase.MIN_MOVE_S, 27.0 / chase_pace.DEFAULTS["turn_deg_s"])
    m.pivot(-54.0)
    assert r.calls[-1][1][0] == -54.0
    m.nudge(6.0)
    name, (deg, secs), kw = r.calls[-1]
    assert deg == 6.0 and secs == max(chase.MIN_MOVE_S, 6.0 / chase_pace.DEFAULTS["pulse_deg_s"]) and kw["stop_deg"] == 6.0       # a pulse never runs shorter than a gait that moves him
    m.scan(27.0)
    assert r.calls[-1][1][0] == 27.0
    n = len(r.calls)
    m.nudge(0.0)
    assert len(r.calls) == n                                                          # a zero turn sends nothing
    m.pivot(500.0)
    assert r.calls[-1][1][0] == bm.TURN_MAX_DEG                                       # the safety cap on one step


def test_a_robot_without_a_scripted_walk_walks_with_walk():
    class Plain:
        def __init__(self):
            self.calls = []

        def walk(self, seconds):
            self.calls.append(("walk", seconds))
            return "ok"

    r = Plain()
    bm.BasketMover(r).forward(3.0)
    assert r.calls[-1][0] == "walk"


def test_a_fall_in_a_move_is_reported_and_ends_the_line_up():
    r = FakeRobot(fall_on="back")
    m = bm.BasketMover(r)
    assert m.back(4.0) == "fell" and m.state == "fell"

    class Look:
        def __call__(self):
            class R:
                claw_in, bearing_deg = 8.0, 0.0                                       # too close: the first step is a back-up
            return R()

    out = bl.lineup(Look(), m, say=lambda s: None)
    assert out["outcome"] == "fell" and len(r.calls) == 2 and out["steps"][-1]["action"] == "back"


def test_the_largest_and_smallest_line_up_steps_stay_inside_the_measured_paces():
    assert bm.back_seconds(bl.BACK_STEP_MAX_IN) <= 3.0 and bm.back_seconds(bl.MIN_STEP_IN) >= bm.BACK_MIN_S      # the line-up's back-up steps (1.5 to 6 inches) sit inside the measured 1 to 3 s
    assert bm.forward_seconds(bl.FAR_STEP_MAX_IN) <= 4.0 and bm.forward_seconds(bl.MIN_STEP_IN) >= chase.MIN_MOVE_S
    for deg in (3.0, 6.0, 17.0, 27.0, 54.0):
        assert chase.MIN_MOVE_S <= max(chase.MIN_MOVE_S, deg / chase_pace.DEFAULTS["pulse_deg_s"]) <= 4.0


def test_a_pace_book_sets_the_walk_and_turn_times_and_the_measured_start_run_is_reproduced():
    class Book:
        def walk_in_s(self):
            return 9.164

        def turn_deg_s(self, side, short):
            return (10.0 if short else 20.0) * (1 if side > 0 else 0.5)

    assert abs(bm.forward_seconds(6.0, 9.164) - (chase_pace.WALK_START_S + 6.0 / 9.164)) < 1e-9
    assert bm.forward_seconds(10.0, 9.164) > 2.0 > bm.forward_seconds(6.0, 9.164)                 # 2026-11-23: a 2 s walk moved about 10 inches
    r = FakeRobot()
    m = bm.BasketMover(r, book=Book())
    m.forward(9.164)
    assert abs(r.calls[-1][1][0] - 2.0) < 1e-9                                                    # start 1 s + 1 s of walking
    m.pivot(40.0)
    assert r.calls[-1][1][1] == 40.0 / 20.0                                                       # right, long turn rate
    m.pivot(-40.0)
    assert r.calls[-1][1][1] == 40.0 / 10.0                                                       # left side is slower in this book
    m.nudge(10.0)
    assert r.calls[-1][1][1] == max(chase.MIN_MOVE_S, 10.0 / 10.0)                                # a pulse uses the pulse rate


def test_the_line_up_tells_the_mover_how_far_the_target_is_so_a_turn_can_be_a_pivot():
    from pi_pipeline.link import opencat
    seen = []

    class R(FakeRobot):
        lineup_ball_in = None

        def turn(self, degrees, seconds, stop_deg=0.0):
            seen.append(self.lineup_ball_in)
            return super().turn(degrees, seconds, stop_deg)

    r = R()
    m = bm.BasketMover(r)
    m.set_distance(12.0)
    m.pivot(27.0)
    assert seen == [12.0] and opencat.lineup_uses_pivot(seen[-1]) is True                  # 12 in: the in-place pivot (kvtR / kvtL)
    assert opencat.lineup_uses_pivot(None) is False and opencat.lineup_uses_pivot(5.0) is False       # no distance or under 8 in: the walking arc, which moves forward
    for told in (None, 5.6, 60.0):                                                          # but the basket mover never lets a turn be the arc: a scan, a near puck, a far target
        seen.clear()
        m.set_distance(told)
        m.pivot(27.0)
        assert opencat.lineup_uses_pivot(seen[-1]) is True

    class World:
        def __init__(self):
            self.d, self.b, self.dist_at_turn = 12.0, 30.0, []

        def look(self):
            return type("Rd", (), {"claw_in": self.d, "bearing_deg": self.b})()

        def set_distance(self, inches):
            self.last = inches

        def pivot(self, deg):
            self.dist_at_turn.append(self.last)
            self.b -= deg

        nudge = pivot

        def forward(self, inches):
            self.d -= inches

        def back(self, inches):
            self.d += inches
    w = World()
    bl.lineup(w.look, w, say=lambda s: None)
    assert w.dist_at_turn and all(x is not None for x in w.dist_at_turn)                  # every turn step was told the distance
