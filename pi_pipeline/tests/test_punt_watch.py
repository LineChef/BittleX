"""The post-punt watch (behavior/punt_watch.py): a stop detector, then follow, stop, still, acquire or lose."""
import itertools

import pytest

from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.behavior import live_follow as lf
from pi_pipeline.behavior import punt_watch as pw
from pi_pipeline.tests.test_ball_chase import FakeCamera, FakeRobot, disc, picture
from pi_pipeline.vision import ball_finder as bf


def test_the_ball_is_stopped_only_when_the_last_pictures_agree_in_place_and_size():
    cfg = pw.WatchConfig(stable_n=4, bearing_tol_deg=2.0, size_tol=0.15, min_span_s=0.5)
    d = pw.StopDetector(cfg)
    for i, (b, w) in enumerate([(10.0, 0.10), (12.0, 0.10), (14.0, 0.09), (15.0, 0.09)]):
        assert d.add(i * 0.25, b, w) is False                                               # still rolling: the bearing moves
    d.clear()
    for i in range(4):
        last = d.add(i * 0.25, 15.0 + 0.3 * i, 0.10)
    assert last is True
    d.clear()
    for i, w in enumerate([0.10, 0.12, 0.14, 0.16]):
        last = d.add(i * 0.25, 15.0, w)
    assert last is False                                                                    # the same bearing but growing: coming toward him
    d.clear()
    assert [d.add(i * 0.05, 15.0, 0.1) for i in range(4)][-1] is False                     # too short a span to call it stopped


class Clock:
    t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class WatchRobot:
    def __init__(self):
        self.calls, self._roll, self._pitch, self.posture = [], [], [], "stand"

    def relax(self):
        self.calls.append("relax")
        return "ok"

    def claw_pose(self, pan, lift):
        self.calls.append(("claw", round(pan, 1), lift))
        return "ok"

    def _fell(self):
        return False

    def _tilt(self, *a, **k):
        return (0.0, 0.0)

    def _tx(self, c):
        pass


class Script:
    """A grabber whose newest picture depends on the clock: the ball rolls from x=0.2 to x=0.8 over 3 s, then lies still (or vanishes)."""

    def __init__(self, clock, vanish_at=None):
        self.clock, self.vanish_at, self.rows, self.stop_flag = clock, vanish_at, [], type("E", (), {"set": lambda s: None})()

    def start(self):
        pass

    def join(self, timeout=None):
        pass

    def take(self):
        t = self.clock()
        idx = int(t / 0.25) + 1
        if self.vanish_at is not None and t >= self.vanish_at:
            return (t - 0.2, [], idx)
        x = 0.2 + 0.6 * min(1.0, t / 3.0)
        return (t - 0.2, [("ball", 1.0, x, 0.6, 0.1, 0.1)], idx)


def reading(distance=14.0, bearing=3.0):
    return bf.BallReading(120.0, 150.0, 800, 24, 24, 24.0, distance, bearing, False)


def run_watch(vanish_at=None, still=reading(), seconds=10.0, on_ready=None):
    c = Clock()
    r = WatchRobot()
    said, spoken = [], []
    res = pw.watch_after_punt(r, object(), lambda find, cfg, clock, save: Script(c, vanish_at), lambda j: [], lambda cam: still, pw.WatchConfig(seconds=seconds, stable_n=6),
                              lf.LiveConfig(tick_s=0.05), say=said.append, announce=spoken.append, sleep=c.sleep, clock=c, on_ready=on_ready)
    return res, r, spoken


def test_a_rolling_ball_is_followed_until_it_stops_then_the_still_acquires_it():
    res, robot, spoken = run_watch()
    assert res.ended == "stopped" and res.found and spoken == ["target acquired"]
    assert res.moves >= 3 and res.pictures >= 0
    assert res.reading.bearing_deg != 3.0                                                   # the still's bearing is turned into G2's own direction by the claw's pan
    assert robot.calls[0] == "relax" and robot.calls[1] == ("claw", 0.0, 120.0) and robot.calls[-1] == ("claw", 0.0, 0.0)


def test_a_ball_that_vanishes_is_lost_with_the_side_it_was_last_seen_on():
    res, robot, spoken = run_watch(vanish_at=1.5)
    assert res.ended == "lost" and not res.found and spoken == ["I lost it"]
    assert res.last_bearing is not None and res.last_side == (1 if res.last_bearing > 0 else -1)         # the side is the sign of the last world bearing (the claw's direction plus the offset)
    assert ("claw", 0.0, 0.0) != robot.calls[-1]                                              # the claw stays up for the caller's turn and look


def test_a_still_without_the_ball_is_lost_too():
    res, robot, spoken = run_watch(still=None)
    assert res.ended == "lost" and spoken == ["I lost it"]


def test_a_ball_still_rolling_at_the_limit_counts_as_stopped_where_it_is():
    res, robot, spoken = run_watch(seconds=1.0)
    assert res.ended == "timeout" and res.found


def test_the_chase_starts_from_the_acquired_reading_without_taking_a_picture_first():
    """first_reading: the planner decides on it at once (a ball 14 in away and 3 deg off: walk), and the camera is not asked first."""
    asked = []

    class Cam(FakeCamera):
        def look(self):
            asked.append(1)
            return super().look()
    robot = FakeRobot()
    out = bc.run_chase(robot, Cam([picture([disc(122, 110, 50)])]), lambda: False, max_steps=1, first_reading=reading(14.0, 3.0), sleep=lambda s: None, say=lambda m: None, dry_run=True)
    assert out == "steps" and asked == []


def test_the_ready_cue_comes_once_the_claw_is_up():
    c = Clock()
    r = WatchRobot()
    seen = []
    pw.watch_after_punt(r, object(), lambda find, cfg, clock, save: Script(c), lambda j: [], lambda cam: reading(), pw.WatchConfig(seconds=3.0, stable_n=6), lf.LiveConfig(tick_s=0.05),
                        say=lambda *_: None, sleep=c.sleep, clock=c, on_ready=lambda: seen.append(list(r.calls)))
    assert len(seen) == 1 and seen[0][:2] == ["relax", ("claw", 0.0, 120.0)]               # the cue is given after the attention pose and the claw raise


class OldSightingGrabber(Script):
    """The ball was seen before the claw could pan (in the rows the stream recorded), then not for a while: the lost clock must not already be running when the follow starts."""

    def __init__(self, clock):
        super().__init__(clock)
        self.rows = [{"det": [("ball", 0.7)], "t_capture": -5.0}]

    def take(self):
        t = self.clock()
        return (t - 0.2, [], int(t / 0.25) + 1) if t < 2.0 else (t - 0.2, [("ball", 1.0, 0.5, 0.6, 0.1, 0.1)], int(t / 0.25) + 1)


def test_a_sighting_before_the_claw_was_up_does_not_start_the_lost_clock():
    c = Clock()
    r = WatchRobot()
    res = pw.watch_after_punt(r, object(), lambda find, cfg, clock, save: OldSightingGrabber(c), lambda j: [], lambda cam: reading(), pw.WatchConfig(seconds=8.0, stable_n=4, lost_after_s=2.5, never_seen_s=4.0),
                              lf.LiveConfig(tick_s=0.05), say=lambda *_: None, sleep=c.sleep, clock=c)
    assert res.ended in ("stopped", "timeout") and res.found                                 # it waited for the ball to come back into view
