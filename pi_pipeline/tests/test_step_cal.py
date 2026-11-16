"""The step calibration (behavior/step_cal.py): the arithmetic and the trial loop on fakes."""
from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.behavior import step_cal as sc
from pi_pipeline.vision import ball_finder as bf


def ball(d, b=0.0):
    return bf.BallReading(120.0, 150.0, 800, 24, 24, 24.0, d, b, False)


class FakeWorld:
    """A robot and a camera that agree: a step of `secs` closes `rate * (secs - start)` inches."""

    def __init__(self, d=30.0, rate=3.0, start=0.2, fall_on=None):
        self.d, self.rate, self.start, self.fall_on = d, rate, start, fall_on
        self.steps, self.backs = [], 0

    def _go(self, kind, secs):
        self.steps.append((kind, secs))
        if self.fall_on == len(self.steps):
            return "fell"
        self.d -= self.rate * max(0.0, secs - self.start)
        return "ok"

    def walk_scripted(self, secs):
        return self._go("small", secs)

    def walk(self, secs):
        return self._go("long", secs)

    def back(self, secs):
        self.backs += 1
        self.d += 8.0
        return "ok"

    def look(self):
        return ball(self.d, 0.0) if self.d > 0 else None


def test_forward_distance_is_the_distance_times_the_cosine_of_the_bearing():
    assert sc.forward_in(10.0, 0.0) == 10.0
    assert abs(sc.forward_in(10.0, 60.0) - 5.0) < 1e-9


def test_the_fit_recovers_the_rate_and_the_start_delay_and_needs_enough_points():
    pts = [(s, 3.0 * (s - 0.2)) for s in (0.4, 0.6, 0.9, 1.2, 0.6, 0.9)]
    f = sc.fit_line(pts)
    assert abs(f["rate_in_s"] - 3.0) < 0.01 and abs(f["start_s"] - 0.2) < 0.01 and f["spread_in"] < 0.01
    assert sc.fit_line(pts[:2]) is None and sc.fit_line([(0.9, 2.0)] * 4) is None             # too few, or one duration only


def test_the_trial_order_is_short_first_small_before_long_and_repeats_in_a_row():
    t = sc.order("all", 2)
    assert t[:4] == [("small", 0.4), ("small", 0.4), ("small", 0.6), ("small", 0.6)] and t[-2:] == [("long", 3.0), ("long", 3.0)]
    assert all(k == "small" for k, _ in sc.order("small", 1)) and len(sc.order("long", 3)) == 9


def test_a_run_measures_each_step_backs_up_when_the_ball_gets_close_and_suggests_the_constants():
    w = FakeWorld(d=16.0, rate=3.0, start=0.2)
    res = sc.run_step_cal(w, w.look, sc.order("small", 2), say=lambda *_: None, sleep=lambda s: None)
    assert res["ended"] == "done" and len(res["rows"]) == 8 and w.backs >= 1                  # 8 steps close more than the 16 in the ball started at: it backed up
    fit = res["summary"]["small"]["fit"]
    assert abs(fit["rate_in_s"] - 3.0) < 0.05 and abs(fit["start_s"] - 0.2) < 0.05
    assert 2.0 < res["summary"]["small"]["suggest_NUDGE_IN_PER_S"] < 3.0                     # inches per second over the whole step, the delay included


def test_a_fall_a_lost_ball_a_ball_that_stays_too_close_and_the_stop_file_end_the_run():
    w = FakeWorld(fall_on=2)
    assert sc.run_step_cal(w, w.look, sc.order("small", 2), say=lambda *_: None, sleep=lambda s: None)["ended"] == "fell"
    assert sc.run_step_cal(FakeWorld(d=30.0), lambda: None, sc.order("small", 1), say=lambda *_: None, sleep=lambda s: None)["ended"] == "lost"
    close = FakeWorld(d=5.0)
    close.back = lambda secs: "ok"                                                           # it cannot back away
    assert sc.run_step_cal(close, close.look, sc.order("small", 1), say=lambda *_: None, sleep=lambda s: None)["ended"] == "ball_too_close"
    w2 = FakeWorld()
    assert sc.run_step_cal(w2, w2.look, sc.order("small", 1), say=lambda *_: None, sleep=lambda s: None, stopped=lambda: True)["ended"] == "stopped" and w2.steps == []


def test_the_long_walk_uses_the_chase_walk_and_the_small_step_the_scripted_one():
    w = FakeWorld(d=34.0)
    sc.run_step_cal(w, w.look, [("small", 0.6), ("long", 1.5)], say=lambda *_: None, sleep=lambda s: None)
    assert w.steps == [("small", 0.6), ("long", 1.5)] and bc.SerialRobot.walk_scripted and bc.SerialRobot.walk
