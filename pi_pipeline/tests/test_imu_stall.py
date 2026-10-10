"""Log-only IMU stall suspect (gait/imu_stall.py): heading jitter while commanded forward."""
import math
import random

from pi_pipeline.gait.imu_stall import ImuStallDetector


def feed(det, seconds, step_deg, forward=True, t0=0.0, seed=1, jitter=True):
    """A 5 Hz IMU stream, 80 Hz ticks; each new frame the heading moves by +-step_deg (jitter) or drifts by step_deg."""
    rng = random.Random(seed)
    yaw, out, t = 0.0, [], t0
    n = int(seconds * 80)
    for i in range(n):
        t = t0 + i / 80
        if i % 16 == 0:
            yaw += step_deg * (rng.choice([-1, 1]) if jitter else 1)
        ev = det.update(t, math.radians(yaw), forward)
        if ev:
            out.append((t, ev))
    return out


def test_a_stall_like_heading_jitter_fires_once():
    d = ImuStallDetector()
    ev = feed(d, 12, 11.0)                               # 10-13 deg per update, like the three wall runs
    assert len(ev) == 1 and ev[0][1]["mean_jitter_deg"] > 8 and d.events == 1


def test_a_normal_walk_does_not_fire():
    d = ImuStallDetector()
    assert feed(d, 20, 1.5) == [] and feed(ImuStallDetector(), 20, 5.9) == []     # the worst older window was 5.9


def test_not_commanded_forward_is_silent_and_resets():
    d = ImuStallDetector()
    assert feed(d, 12, 11.0, forward=False) == []
    d2 = ImuStallDetector()
    feed(d2, 5, 11.0)
    d2.update(5.0, 0.0, False)
    assert d2.mean_jitter_deg() is None


def test_it_waits_for_enough_samples_and_the_settle_time():
    d = ImuStallDetector()
    assert feed(d, 3, 11.0) == []                        # 1.5 s settle, then under 20 frames
    assert d.mean_jitter_deg() is None


def test_rearms_after_the_jitter_stops_and_handles_the_wrap():
    d = ImuStallDetector()
    feed(d, 12, 11.0)
    feed(d, 12, 0.5, t0=12.0)                            # calm again
    assert len(feed(d, 12, 11.0, t0=24.0, seed=2)) == 1 and d.events == 2
    w = ImuStallDetector()
    assert feed(w, 20, 3.0, jitter=False) == []          # a steady turn wraps through 180 and is not jitter
