"""The basket movers (behavior/basket_movers.py) on a fake robot: the measured back-up table, the forward pace and the turns, with the line-up loop in front."""
from pi_pipeline.behavior import ball_chase as chase
from pi_pipeline.behavior import basket_lineup as bl
from pi_pipeline.behavior import basket_movers as bm


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
    assert r.calls[-1][0] == "walk_scripted" and abs(r.calls[-1][1][0] - 2.0) < 1e-9
    m.forward(0.5)
    assert r.calls[-1][1][0] == bm.FWD_MIN_S
    m.pivot(27.0)
    name, (deg, secs), kw = r.calls[-1]
    assert name == "turn" and deg == 27.0 and kw["stop_deg"] == 27.0 and secs == max(chase.MIN_MOVE_S, 27.0 / bm.TURN_DEG_S)
    m.pivot(-54.0)
    assert r.calls[-1][1][0] == -54.0
    m.nudge(6.0)
    name, (deg, secs), kw = r.calls[-1]
    assert deg == 6.0 and secs == max(chase.MIN_MOVE_S, 6.0 / bm.PULSE_DEG_S) and kw["stop_deg"] == 6.0       # a pulse never runs shorter than a gait that moves him
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
    assert bm.forward_seconds(bl.FAR_STEP_MAX_IN) <= 4.0 and bm.forward_seconds(bl.MIN_STEP_IN) >= bm.FWD_MIN_S
    for deg in (3.0, 6.0, 17.0, 27.0, 54.0):
        assert chase.MIN_MOVE_S <= max(chase.MIN_MOVE_S, deg / bm.PULSE_DEG_S) <= 4.0
