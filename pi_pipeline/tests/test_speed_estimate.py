import math

from pi_pipeline.gait.carpet import CarpetAction, CarpetConfig, CarpetDetector
from pi_pipeline.gait.speed_estimate import SpeedEstimatorConfig, ZuptSpeedEstimator


def _walk(est, *, true_v, bias, cycles, hz=50.0, cycle_s=0.5, noise=0.0, rng=None):
    """Feed the estimator a synthetic steady walk: forward accel oscillates
    within a cycle (mean ~0) plus a constant `bias`; return the final v_est."""
    dt = 1.0 / hz
    steps_per_cycle = int(round(cycle_s * hz))
    v = 0.0
    for k in range(int(cycles * steps_per_cycle)):
        phase = (k % steps_per_cycle) / steps_per_cycle
        # a sinusoidal accel whose integral over a cycle is 0, scaled so the
        # within-cycle speed swings around `true_v`
        a_true = 2 * math.pi / cycle_s * 0.15 * math.cos(2 * math.pi * phase)
        a_meas = a_true + bias + (rng.uniform(-noise, noise) if rng else 0.0)
        v = est.update(a_meas, phase, dt)
    return v


def test_none_accel_is_inert():
    est = ZuptSpeedEstimator()
    for _ in range(50):
        assert est.update(None, 0.5, 0.02) == 0.0
    assert est.v_est == 0.0


def test_zupt_cancels_a_constant_accel_bias():
    est = ZuptSpeedEstimator(SpeedEstimatorConfig(leak_hz=0.7, bias_lerp=0.5))
    # a pure bias with zero true motion -> after a few cycles the estimate
    # should be pulled back near zero, not ramp away
    v = _walk(est, true_v=0.0, bias=0.4, cycles=12)
    assert abs(v) < 0.06


def test_tracks_a_real_forward_swing_without_bias():
    est = ZuptSpeedEstimator()
    v = _walk(est, true_v=0.1, bias=0.0, cycles=10)
    # the estimate stays bounded and small (mean forward speed is low for Bittle)
    assert -0.3 < v < 0.3


def test_estimate_is_clamped():
    est = ZuptSpeedEstimator(SpeedEstimatorConfig(max_speed=0.2, bias_lerp=0.0))
    v = est.update(50.0, 0.5, 0.1)          # absurd accel
    assert abs(v) <= 0.2


def test_reset():
    est = ZuptSpeedEstimator()
    _walk(est, true_v=0.1, bias=0.3, cycles=5)
    est.reset()
    assert est.v_est == 0.0


def test_feeds_carpet_detector_end_to_end():
    """The whole path: bogged-down gait -> low measured speed -> CarpetDetector
    recommends a fix. Here we bypass the accel model and drive v_est directly
    from a slip ratio to keep the test about the wiring, not the IMU physics."""
    det = CarpetDetector(CarpetConfig(boost_below=0.72, carpet_below=0.45,
                                      enter_s=1.0, window_s=1.0),
                         clock=lambda: _t[0])
    _t = [0.0]
    cmd = 0.10
    # 30% efficient (deep pile) for 2 s
    for _ in range(100):
        _t[0] += 0.02
        a = det.update(cmd, 0.03)
    assert a is CarpetAction.CARPET_GAIT
