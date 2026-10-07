"""yaw_drift_check: the fit reports a steady drift and the sensor scatter around it."""
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gait"))
import yaw_drift_check as Y  # noqa: E402


def test_steady_drift_rate_and_net():
    samples = [(k * 0.2, 0.0, 0.0, math.radians(0.5 * k * 0.2)) for k in range(301)]      # 0.5 deg/s for 60 s
    r = Y.analyze(samples)
    assert abs(r["rate_deg_s"] - 0.5) < 1e-6 and abs(r["net_deg"] - 30.0) < 1e-6 and r["scatter_deg"] < 1e-6


def test_flat_yaw_has_zero_rate():
    r = Y.analyze([(k * 0.2, 0.01, -0.02, 0.3) for k in range(50)])
    assert abs(r["rate_deg_s"]) < 1e-9 and r["roll_sd_deg"] < 1e-9


def test_too_few_frames_is_an_error():
    try:
        Y.analyze([(0.0, 0, 0, 0)])
    except ValueError:
        return
    raise AssertionError("expected ValueError")
