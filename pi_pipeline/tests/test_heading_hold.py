import importlib.util
import os
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


def test_openloop_applies_foot_trim():
    import inspect
    from pi_pipeline.gait import run_gait
    assert "foot_trim" in inspect.signature(run_gait.openloop).parameters


def test_several_feet_trimmed_at_once():
    from pi_pipeline.gait import heading_hold as hh
    assert hh.parse_foot_trims("fl=-0.3/fr=+0.3") == [("fl", -0.3), ("fr", 0.3)] and hh.parse_foot_trims("") is None
    base = [10, 20, 30, 40, 50, 60, 70, 80]
    both = hh.apply_foot_trims(base, [("fl", -0.3), ("fr", 0.3)])
    assert both[0] == hh.apply_foot_trim(base, "fl", -0.3)[0] and both[2] == hh.apply_foot_trim(base, "fr", 0.3)[2]


def _plant(hold, drift_dps=7.0, gain_dps_per_g=9.0, seconds=12.5, imu_hz=5.0):
    """Right-positive yaw plant: drifts at drift_dps, a trim g on the front-left foot adds gain_dps_per_g * g (negative = left). The hold sees the IMU at imu_hz, held in between."""
    import math
    yaw, seen, t, dt, trace = 0.0, 0.0, 0.0, 1 / 80, []
    next_imu = 0.0
    while t < seconds:
        if t >= next_imu:
            seen, next_imu = yaw, next_imu + 1 / imu_hz
        g = hold.update(math.radians(seen), dt)
        yaw += (drift_dps + gain_dps_per_g * g) * dt
        t += dt
        trace.append((yaw, g))
    return trace


def test_foot_hold_contains_drift_without_hunting():
    from pi_pipeline.gait import heading_hold as hh
    tr = _plant(hh.FootHold("fl"), drift_dps=6.0)
    yaws = [y for y, _ in tr]
    assert max(abs(y) for y in yaws) < 30 and abs(yaws[-1]) < 25           # open loop is +75 deg after 12.5 s
    assert all(-0.6 <= g <= 0.2 for _, g in tr)
    late = [g for _, g in tr[len(tr) // 2:]]
    assert max(late) - min(late) < 0.35                                       # settles, no big swings


def test_foot_hold_idle_inside_deadband_and_releases_when_inactive():
    import math
    from pi_pipeline.gait import heading_hold as hh
    h = hh.FootHold("fl")
    for _ in range(80):
        assert abs(h.update(math.radians(3.0), 1 / 80)) < 1e-9               # 3 deg off, no drift rate: nothing
    h.update(math.radians(40.0), 1 / 80)
    for _ in range(400):
        g = h.update(math.radians(40.0), 1 / 80, active=False)
    assert abs(g) < 1e-9


def test_ingest_gate_rejects_steering_test_runs():
    spec = importlib.util.spec_from_file_location("g2_ingest_t", os.path.join(os.path.dirname(__file__), "..", "..", "tools", "g2_ingest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    why = mod.gate({"foot_trim": "fl:0.5", "end_reason": "stopped"}, [], {"rows": 100}, {})
    assert any("never fed to the sim" in w for w in why)
    # the front-foot heading hold is on in every walk since 2026-10-07: a light touch is fine, a run where it worked hard is not
    assert not any("heading hold" in w for w in mod.gate({"foot_hold": "fl", "end_reason": "stopped"}, [], {"rows": 100, "steer_u_mean_abs": 0.2}, {}))
    assert any("worked hard" in w for w in mod.gate({"foot_hold": "fl", "end_reason": "stopped"}, [], {"rows": 100, "steer_u_mean_abs": 0.5}, {}))


def test_foot_hold_feed_forward_starts_the_trim_and_default_is_zero(monkeypatch):
    import math
    from pi_pipeline.gait import heading_hold as hh
    monkeypatch.delenv("G2_FOOT_HOLD_FF", raising=False)
    assert hh.default_foot_hold_ff() == 0.0
    monkeypatch.setenv("G2_FOOT_HOLD_FF", "-0.25")
    assert hh.default_foot_hold_ff() == -0.25
    h = hh.FootHold("fl", ff=-0.25)
    for _ in range(160):
        g = h.update(0.0, 1 / 80)              # dead on target: the trim goes to the feed-forward and stays
    assert abs(g + 0.25) < 1e-6
    assert _plant(hh.FootHold("fl", ff=-0.25), drift_dps=6.0)[-1][0] < 25


def test_foot_hold_eases_off_fast_when_the_drift_stops():
    import math
    from pi_pipeline.gait import heading_hold as hh
    h = hh.FootHold("fl")
    yaw, seen, t, dt, next_imu, trace = 0.0, 0.0, 0.0, 1 / 80, 0.0, []
    while t < 20.0:
        if t >= next_imu:
            seen, next_imu = yaw, next_imu + 0.2
        g = h.update(math.radians(seen), dt)
        drift = 6.0 if t < 10.0 else 0.0                       # the drift stops half way (a surface change, warm servos)
        yaw += (drift + 9.0 * g) * dt
        t += dt
        trace.append((t, yaw, g))
    assert min(y for _, y, _ in trace) > -12.0                  # no hard swing to the left after the drift is gone
    late = [g for tt, _, g in trace if tt > 14.0]
    assert max(abs(g) for g in late) < 0.25                     # and the trim has eased off
    # releasing is faster than building up
    h2 = hh.FootHold("fl")
    h2.g = -0.6
    for _ in range(40):
        h2.update(math.radians(-8.0), 1 / 80)                   # 0.5 s with the heading already left of target
    assert h2.g > -0.2


def test_default_foot_trim_is_the_measured_v4_value_and_can_be_overridden(monkeypatch):
    from pi_pipeline.gait import heading_hold as hh
    monkeypatch.delenv("G2_FOOT_TRIM", raising=False)
    assert hh.default_foot_trim("trained/Release_CandidateV4_ppo.onnx") == [("fl", -0.2)]
    assert hh.default_foot_trim("trained/Release_CandidateV6_ppo.onnx") == [("fl", -0.5)]
    assert hh.default_foot_trim("trained/other_ppo.onnx") is None and hh.default_foot_trim(None) is None
    monkeypatch.setenv("G2_FOOT_TRIM", "fl=-0.25")
    assert hh.default_foot_trim("trained/other_ppo.onnx") == [("fl", -0.25)]
    monkeypatch.setenv("G2_FOOT_TRIM", "off")
    assert hh.default_foot_trim("trained/Release_CandidateV4_ppo.onnx") is None
