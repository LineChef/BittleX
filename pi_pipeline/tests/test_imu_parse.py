"""Direct, dependency-free tests for the shared pi_pipeline/gait/imu_parse.py
-- see test_run_gait_imu.py for the same coverage exercised through
run_gait.py's re-export, and test_sensors.py for SensorHub's consumer side.
"""
import math

import pytest

from pi_pipeline.gait.imu_parse import parse_imu_line


def _rad(deg):
    return pytest.approx(deg * math.pi / 180.0)


def test_mcu_prefix_parses_accel_then_negated_yaw_pitch_roll():
    line = "MCU:  0.02 -0.01  1.00  -12.3  45.6  -78.9"
    roll, pitch, yaw, gx, gy, gz = parse_imu_line(line)
    assert roll == _rad(-78.9)
    assert pitch == _rad(45.6)
    assert yaw == _rad(12.3)
    assert (gx, gy, gz) == (0.0, 0.0, 0.0)


def test_icm_prefix_also_recognised():
    roll, pitch, yaw, *_ = parse_imu_line("ICM: 0.10 0.20 0.98  10.0 -5.0 2.0")
    assert yaw == _rad(-10.0)
    assert pitch == _rad(-5.0)
    assert roll == _rad(2.0)


def test_malformed_and_empty_lines_return_none():
    assert parse_imu_line("MCU: not numbers") is None
    assert parse_imu_line("MCU: 1.0 2.0 3.0") is None
    assert parse_imu_line("garbage") is None
    assert parse_imu_line("") is None


# ------------------------------------------------------------------ ImuFeed
from pi_pipeline.gait.imu_parse import IMU_PREFIXES, ImuFeed  # noqa: E402


def _mcu(roll_deg, pitch_deg=0.0):
    return f"MCU:  0.00  0.00  1.00    0.0{pitch_deg:7.1f}{roll_deg:7.1f}"


def test_imu_prefixes_match_the_serial_link_demux():
    from pi_pipeline.link.serial_link import IMU_PREFIXES as LINK_PREFIXES
    assert IMU_PREFIXES == LINK_PREFIXES


def test_feed_holds_the_latest_frame_between_prints():
    f = ImuFeed()
    assert f.frame is None and f.age(0.0) == math.inf
    assert f.update([_mcu(1.0), "m", _mcu(2.0)], now=1.0)   # non-IMU echo ignored
    assert f.frame[0] == _rad(2.0)
    assert not f.update([], now=1.1)                       # nothing new: frame held
    assert f.frame[0] == _rad(2.0) and f.age(1.1) == pytest.approx(0.1)


def test_feed_finite_differences_roll_pitch_rate_across_frames():
    f = ImuFeed()
    f.update([_mcu(0.0, 0.0)], now=0.0)
    assert f.frame[3:] == (0.0, 0.0, 0.0)                  # one frame: no rate yet
    f.update([_mcu(2.0, -4.0)], now=0.2)
    gx, gy, _ = f.frame[3:]
    assert gx == _rad(10.0) and gy == _rad(-20.0)          # deg/s -> rad/s


def test_feed_ignores_bursts_for_the_rate_but_keeps_the_orientation():
    f = ImuFeed()
    f.update([_mcu(0.0)], now=0.0)
    f.update([_mcu(2.0)], now=0.2)
    f.update([_mcu(9.0)], now=0.21)                        # 10 ms later: buffered burst
    assert f.frame[0] == _rad(9.0)
    assert f.frame[3] == _rad(10.0)                        # rate held from the real interval


def test_feed_zero_rate_mode():
    f = ImuFeed(rate_mode="zero")
    f.update([_mcu(0.0)], now=0.0)
    f.update([_mcu(5.0)], now=0.2)
    assert f.frame[3:] == (0.0, 0.0, 0.0)


def test_feed_passes_a_true_gyro_through():
    f = ImuFeed()
    f.update(["10 20 30 1 2 3"], now=0.0)                  # legacy ypr+gyro shape
    assert f.frame[3:] == (_rad(1.0), _rad(2.0), _rad(3.0))
