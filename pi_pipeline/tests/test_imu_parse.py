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
