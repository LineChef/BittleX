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
    assert robot.calls[-1] == ("claw", 0.0, 0.0)                                              # the claw goes home before the caller's turn and look


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


def _after_punt(post_punt_watch, **kw):
    frames = [picture([disc(122, 110, 50)])]
    trace = []
    robot = FakeRobot()
    out = bc.run_chase(robot, FakeCamera(frames), lambda: False, max_punts=1, max_steps=10, after_punt_look=True, trace=trace, post_punt_watch=post_punt_watch,
                       sleep=lambda s: None, say=lambda m: None, **kw)
    return out, trace


def test_the_watch_replaces_the_one_picture_after_the_last_punt_and_feeds_the_scorer_its_reading():
    r = reading(30.0, 8.0)
    out, trace = _after_punt(lambda: pw.WatchResult(ended="stopped", found=True, reading=r, pictures=40, bad_frames=3, moves=9))
    ap = next(e for e in trace if e["kind"] == "after_punt")
    assert out == "punted" and ap["ball"]["distance_in"] == 30.0 and ap["watch"] == "stopped" and ap["claw_moves"] == 9 and ap["bad_frames"] == 3


def test_a_lost_ball_is_an_after_punt_with_no_ball_and_a_watch_that_cannot_run_falls_back_to_the_one_picture():
    out, trace = _after_punt(lambda: pw.WatchResult(ended="lost", found=False, last_side=-1))
    ap = next(e for e in trace if e["kind"] == "after_punt")
    assert ap["ball"] is None and ap["watch"] == "lost" and ap["last_side"] == -1
    out, trace = _after_punt(lambda: pw.WatchResult(ended="error"))
    ap = next(e for e in trace if e["kind"] == "after_punt")
    assert "watch" not in ap and ap["picture"] is True                                       # the old single picture was taken
    out, trace = _after_punt(lambda: pw.WatchResult(ended="fell"))
    assert out == "fell"


def test_the_setting_switches_the_watch_off(monkeypatch):
    monkeypatch.setattr(bc, "POST_PUNT_WATCH", False)
    called = []
    out, trace = _after_punt(lambda: called.append(1) or pw.WatchResult(ended="stopped", found=True, reading=reading()))
    assert not called and next(e for e in trace if e["kind"] == "after_punt").get("watch") is None


def test_the_ball_goal_carries_where_the_ball_stopped_into_the_next_attempt():
    from pi_pipeline.goals.approach import AttemptContext
    from pi_pipeline.goals.ball_punt import BallPunt
    seen = {}

    class Chase:
        POST_PUNT_WATCH = True
        LOST_LOOKS = 3
        DEFAULT_MAX_SECONDS = 75.0

        class ChasePlanner:
            def __init__(self):
                self.punt_log, self.walk_log, self.back_s, self.lost = [], [], 0.0, 0

            def _turn_rate(self, side, short):
                return 25.0

        @staticmethod
        def run_chase(robot, camera, stop, **kw):
            seen.update(kw)
            return "punted"
    ap = BallPunt(robot=type("R", (), {"claw_pose": lambda s, a, b: "ok", "turn": lambda s, d, secs, stop_deg=0.0: seen.setdefault("turned", d)})(), camera=object(), pace=None)
    import pi_pipeline.goals.ball_punt as bp
    orig = bp._chase
    bp._chase = lambda: Chase
    try:
        import time as _t
        ap._last_watch = (_t.monotonic(), pw.WatchResult(ended="stopped", found=True, reading=reading(20.0, 5.0)))
        ap.run_attempt({}, AttemptContext(stop=lambda: False, say=lambda m: None))
        assert seen["first_reading"].distance_in == 20.0 and ap._last_watch is None             # used once
        seen.clear()
        ap._last_watch = (_t.monotonic(), pw.WatchResult(ended="lost", found=False, last_side=-1))
        ap.run_attempt({}, AttemptContext(stop=lambda: False, say=lambda m: None))
        assert seen["first_reading"] is None and seen["turned"] == -40.0                         # turned toward the side it was last seen on, then the normal search
    finally:
        bp._chase = orig


def test_a_punt_that_leaves_the_arm_up_lets_the_watch_start_without_the_attention_move():
    class UpRobot(WatchRobot):
        def claw_is_up(self):
            return True
    c = Clock()
    r = UpRobot()
    res = pw.watch_after_punt(r, object(), lambda find, cfg, clock, save: Script(c), lambda j: [], lambda cam: reading(), pw.WatchConfig(seconds=6.0, stable_n=6), lf.LiveConfig(tick_s=0.05),
                              say=lambda *_: None, sleep=c.sleep, clock=c)
    assert "relax" not in r.calls and ("claw", 0.0, 120.0) not in r.calls[:1] and res.found


def test_the_last_punt_of_an_attempt_leaves_the_arm_up_when_the_watch_will_run(monkeypatch):
    calls = []

    class R(FakeRobot):
        def punt(self):
            calls.append("punt")
            return "ok"

        def punt_arm_up(self):
            calls.append("punt_arm_up")
            return "ok"
    frames = [picture([disc(122, 110, 50)])]
    bc.run_chase(R(), FakeCamera(frames), lambda: False, max_punts=1, max_steps=10, after_punt_look=True, post_punt_watch=lambda: pw.WatchResult(ended="stopped", found=True, reading=reading()),
                 sleep=lambda s: None, say=lambda m: None)
    assert calls == ["punt_arm_up"]
    calls.clear()
    monkeypatch.setattr(bc, "POST_PUNT_WATCH", False)
    bc.run_chase(R(), FakeCamera(frames), lambda: False, max_punts=1, max_steps=10, after_punt_look=True, post_punt_watch=lambda: pw.WatchResult(ended="stopped"), sleep=lambda s: None, say=lambda m: None)
    assert calls == ["punt"]
