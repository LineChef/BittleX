"""The Pi-side heading hold (gait/heading_hold.py): signs, limits and closed-loop behaviour on a simple plant."""
import math

import pytest

from pi_pipeline.gait import heading_hold as hh


def test_stride_difference_signs_and_stance_fixed_point():
    stand = [50, 0, 50, 0, 50, 0, 50, 0]
    assert hh.apply_stride_difference(stand, 0.2) == stand                      # the stance angle is the fixed point
    swing = [70, 5, 30, -5, 30, 5, 70, -5]                                       # FLsh +20, FRsh -20, BRhip -20, BLhip +20 from stance
    out = hh.apply_stride_difference(swing, 0.1)
    assert out[0] == 68 and out[6] == 68                                         # left legs x0.9: 50 + 0.9*20
    assert out[2] == 28 and out[4] == 28                                         # right legs x1.1: 50 - 22
    assert [out[i] for i in (1, 3, 5, 7)] == [5, -5, 5, -5]                      # knees untouched


def test_a_rightward_drift_asks_for_longer_left_strides():
    c = hh.HeadingHold()
    u = 0.0
    for _ in range(200):
        u = c.update(math.radians(20.0), 0.0125)                                 # +20 deg = drifted right
    assert u < 0                                                                 # negative u: right legs shorter, left longer -> turns left


def test_output_is_clipped_and_slew_limited():
    c = hh.HeadingHold()
    assert abs(c.update(math.radians(170.0), 0.0125)) <= hh.U_RATE * 0.0125 + 1e-12      # one tick cannot jump
    for _ in range(4000):
        u = c.update(math.radians(170.0), 0.0125)
    assert u == pytest.approx(-hh.U_MAX)


def test_releases_when_inactive():
    c = hh.HeadingHold()
    for _ in range(400):
        c.update(math.radians(30.0), 0.0125)
    assert c.u < -0.01
    for _ in range(2000):
        u = c.update(math.radians(30.0), 0.0125, active=False)
    assert u == pytest.approx(0.0, abs=1e-9)


def _simulate(push_deg_s, hold, seconds=30.0, dt=0.0125):
    """Plant from steer_probe.py: right-turn rate = 12.2 deg/s per unit u, plus a steady push to the right."""
    c, yaw, trace = hh.HeadingHold(), 0.0, []
    for _ in range(int(seconds / dt)):
        u = c.update(math.radians(yaw), dt) if hold else 0.0
        yaw += (12.2 * u + push_deg_s) * dt
        trace.append(yaw)
    return trace


def test_closed_loop_halves_a_g2_sized_push_and_removes_a_smaller_one():
    at = lambda tr, s: tr[int(s / 0.0125) - 1]
    free, held = _simulate(3.0, False), _simulate(3.0, True)
    assert at(free, 12.5) == pytest.approx(37.5, abs=0.5)                         # G2's average post-swap drift, ~+36 deg per 12.5 s
    assert abs(at(held, 12.5)) < 0.6 * at(free, 12.5)                             # limited authority: the hold cancels roughly half of it
    small = _simulate(1.5, True)
    assert abs(at(small, 30.0)) < 5.0                                             # a push within the authority is driven back toward 0
    assert max(abs(v) for v in small) < 15.0                                      # without runaway


def test_wrap_deg():
    assert hh.wrap_deg(190.0) == pytest.approx(-170.0) and hh.wrap_deg(-190.0) == pytest.approx(170.0)
