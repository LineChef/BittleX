"""The Pi-side heading hold (gait/heading_hold.py): signs, limits and closed-loop behaviour on a simple plant."""
import math

import pytest

from pi_pipeline.gait import heading_hold as hh


def test_stride_difference_signs_and_stance_fixed_point():
    stand = [50, 0, 50, 0, 50, 0, 50, 0]
    assert hh.apply_stride_difference(stand, 0.2) == stand                      # the stance angle is the fixed point
    swing = [70, 5, 30, -5, 30, 5, 70, -5]                                       # FLsh +20, FRsh -20, BRhip -20, BLhip +20 from stance
    out = hh.apply_stride_difference(swing, 0.1)
    assert out[0] == 72 and out[6] == 72                                         # left legs x1.1: 50 + 1.1*20 (u > 0 = longer LEFT strides = a right turn on G2)
    assert out[2] == 32 and out[4] == 32                                         # right legs x0.9: 50 - 18
    assert [out[i] for i in (1, 3, 5, 7)] == [5, -5, 5, -5]                      # knees untouched


def test_a_rightward_drift_asks_for_longer_right_strides():
    c = hh.HeadingHold()
    u = 0.0
    for _ in range(200):
        u = c.update(math.radians(20.0), 0.0125)                                 # +20 deg = drifted right
    assert u < 0                                                                 # negative u: left legs shorter, right longer -> G2 turns left (measured 2026-10-06)


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


def test_fixed_u_mode_ignores_heading_and_is_slew_limited_and_clipped():
    c = hh.HeadingHold()
    c.fixed_u = -0.15
    first = c.update(math.radians(80.0), 0.0125)
    assert first == pytest.approx(-hh.U_RATE * 0.0125)                            # slewed, not a jump, and the heading error is not used
    for _ in range(2000):
        u = c.update(math.radians(-80.0), 0.0125)
    assert u == pytest.approx(-0.15)
    c.fixed_u = 0.9
    for _ in range(4000):
        u = c.update(0.0, 0.0125)
    assert u == pytest.approx(hh.U_MAX)                                           # clipped at the same limit


def test_feed_forward_starts_the_output_at_the_known_drift_and_feedback_still_acts():
    c = hh.HeadingHold(ff=-0.15)
    for _ in range(2000):
        u = c.update(0.0, 0.0125)                                                 # on heading: the output settles at the feed-forward
    assert u == pytest.approx(-0.15, abs=1e-6)
    for _ in range(2000):
        u = c.update(math.radians(-20.0), 0.0125)                                 # drifted LEFT of the target: feedback backs the correction off
    assert u > -0.15


def test_integral_contribution_is_clamped():
    c = hh.HeadingHold(ki=0.004, i_lim=0.05)
    for _ in range(8000):
        c.update(math.radians(10.0), 0.0125, active=True)                          # a long steady rightward error
    assert abs(c.ki * c.integral) <= 0.05 + 1e-9


def test_scaled_joints_never_leave_the_reach_the_walk_uses():
    swing = [11, 0, 80, 0, 75, 0, 85, 0]                       # the unscaled extremes of the four swing joints
    out = hh.apply_stride_difference(swing, -0.38)              # right strides 38% longer
    assert out[4] <= 75 + hh.JOINT_MARGIN_DEG and out[2] <= 80 + hh.JOINT_MARGIN_DEG    # the back-right hip / front-right shoulder stay off the floor
    low = hh.apply_stride_difference([11, 0, 11, 0, 22, 0, 28, 0], -0.38)
    assert low[2] >= 11 - hh.JOINT_MARGIN_DEG and low[4] >= 22 - hh.JOINT_MARGIN_DEG
    assert hh.apply_stride_difference([50, 0, 50, 0, 50, 0, 50, 0], -0.38) == [50, 0, 50, 0, 50, 0, 50, 0]    # stance unchanged


# ------------------------------------------------------------------ one-foot trim (the per-foot steering test, 2026-10-07)
def test_a_foot_trim_scales_only_that_foots_swing_about_the_stance_and_clamps_it():
    from pi_pipeline.gait import heading_hold as hh
    base = [70, 40, 30, 55, 65, 40, 35, 30]                               # URDF order: FLsh FLel FRsh FRel BRhip BRkn BLhip BLkn
    out = hh.apply_foot_trim(base, "bl", 0.25)
    assert out[6] == round(50 + 1.25 * (35 - 50)) and [out[i] for i in range(8) if i != 6] == [base[i] for i in range(8) if i != 6]      # only the back-left hip moved
    assert hh.apply_foot_trim(base, "fl", -0.25)[0] == round(50 + 0.75 * (70 - 50))
    reach = hh.apply_foot_trim([50, 0, 50, 0, 50, 0, 80, 0], "bl", 1.0)                                         # a huge stretch never goes past the walk's own reach plus the margin
    assert reach[6] == hh.JOINT_RANGE_DEG[6][1] + hh.JOINT_MARGIN_DEG
    assert hh.apply_foot_trim(base, "br", 0.0) == [int(v) for v in base]                                      # zero changes nothing


def test_foot_trim_text_is_parsed_and_a_bad_foot_is_refused():
    from pi_pipeline.gait import heading_hold as hh
    assert hh.parse_foot_trim("bl=+0.25") == ("bl", 0.25) and hh.parse_foot_trim("FR=-0.1") == ("fr", -0.1) and hh.parse_foot_trim("") is None
    import pytest
    with pytest.raises(ValueError):
        hh.parse_foot_trim("rear=0.2")
