"""parse_imu_line() against the CONFIRMED real firmware line shape.

Confirmed 2026-09-20 from PetoiCamp/OpenCatEsp32 src/imu.h `print6Axis()`
(the function actually wired into the main loop via readEnvironment(),
not the dead print6AxisMacro()): "MCU:<ax><ay><az><yaw><pitch><roll>" or
"ICM:<...>" (chip-dependent), fixed-width, yaw printed negated. See
parse_imu_line's own docstring in pi_pipeline/gait/run_gait.py for the
full citation and the still-open gyro-vs-accel gap this uncovered.

run_gait.py is written to run as a script (bare `import residual_policy`),
so load it with its own dir on sys.path -- same pattern as
test_run_gait_skills.py.
"""
import importlib.util
import math
import os
import sys

import pytest

_GAIT_DIR = os.path.join(os.path.dirname(__file__), "..", "gait")


@pytest.fixture(scope="module")
def rg():
    pytest.importorskip("onnxruntime")
    for p in (_GAIT_DIR, os.path.join(_GAIT_DIR, ".."), os.path.join(_GAIT_DIR, "..", "..")):
        sys.path.insert(0, os.path.abspath(p))
    spec = importlib.util.spec_from_file_location(
        "run_gait_under_test_imu", os.path.join(_GAIT_DIR, "run_gait.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mcu_prefix_parses_accel_then_negated_yaw_pitch_roll(rg):
    # snprintf(buffer, "MCU:%6.2f%6.2f%6.2f%7.1f%7.1f%7.1f", ax, ay, az, -yaw, pitch, roll)
    line = "MCU:  0.02 -0.01  1.00  -12.3  45.6  -78.9"
    roll, pitch, yaw, gx, gy, gz = rg.parse_imu_line(line)
    assert roll == pytest.approx(-78.9 * math.pi / 180.0)
    assert pitch == pytest.approx(45.6 * math.pi / 180.0)
    assert yaw == pytest.approx(12.3 * math.pi / 180.0)   # re-negated back to raw


def test_icm_prefix_also_recognised(rg):
    line = "ICM: 0.10 0.20 0.98  10.0 -5.0 2.0"
    roll, pitch, yaw, *_ = rg.parse_imu_line(line)
    assert yaw == pytest.approx(-10.0 * math.pi / 180.0)
    assert pitch == pytest.approx(-5.0 * math.pi / 180.0)
    assert roll == pytest.approx(2.0 * math.pi / 180.0)


def test_mcu_prefix_does_not_smuggle_accel_into_gyro_slot(rg):
    """The real stream carries acceleration, not angular velocity -- the
    gyro slot must come back zero, never populated with accel data, so a
    caller can never mistake one physical quantity for the other."""
    line = "MCU:  0.02 -0.01  1.00  -12.3  45.6  -78.9"
    *_, gx, gy, gz = rg.parse_imu_line(line)
    assert (gx, gy, gz) == (0.0, 0.0, 0.0)


def test_malformed_mcu_line_returns_none(rg):
    assert rg.parse_imu_line("MCU: not numbers here") is None
    assert rg.parse_imu_line("MCU: 1.0 2.0 3.0") is None  # only 3 nums, need 6


def test_legacy_ypr_fallback_still_works(rg):
    roll, pitch, yaw, *_ = rg.parse_imu_line("ypr\t10.0\t20.0\t30.0")
    assert yaw == pytest.approx(10.0 * math.pi / 180.0)
    assert pitch == pytest.approx(20.0 * math.pi / 180.0)
    assert roll == pytest.approx(30.0 * math.pi / 180.0)


def test_garbage_and_empty_lines_return_none(rg):
    assert rg.parse_imu_line("garbage line") is None
    assert rg.parse_imu_line("") is None
