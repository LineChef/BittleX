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


class _FiveHzImuLink:
    """Emits one IMU line per 200 ms like stock firmware; records sends."""

    def __init__(self):
        import time
        self._t0 = time.monotonic()
        self._emitted = 0
        self.sent = []

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return ""

    def poll_imu(self):
        import time
        due = int((time.monotonic() - self._t0) / 0.2) + 1
        out = ["MCU:  0.00  0.00  1.00    0.0   0.0   0.0"] * (due - self._emitted)
        self._emitted = due
        return out


def test_loop_ticks_at_control_rate_not_imu_print_rate(rg, monkeypatch):
    """Until 2026-09-22 the loop blocked on readline each tick, so the 5 Hz
    firmware IMU print paced the policy, gait phase and joint commands."""
    pytest.importorskip("onnxruntime")
    monkeypatch.setattr(rg, "diag", None)
    lk = _FiveHzImuLink()
    rg.run(lk, 0.10, 1.0, 80.0, "auto", disable_firmware_balance=True,
           thermal_guard=False)
    moves = [c for c in lk.sent if c.startswith("i") and " " in c]
    assert len(moves) >= 70            # ~80 ticks in 1 s, minus the stand pose
    assert lk._emitted <= 16           # while only ~5 IMU frames/s arrived (incl. setup pauses)
    # balance off is the explicit "gb" (bare "g" toggles), restored on exit
    assert "g" not in lk.sent and lk.sent.index("gb") < lk.sent.index("gP")
    assert lk.sent[-1] == "gB"


def test_gait_move_command_is_simultaneous_i_not_sequential_m():
    """`m` moves joints one at a time (>=144 ms per 8-joint command) -- the
    gait loop must send `i`, which moves them together."""
    from pi_pipeline.gait import deploy_map
    cmd = deploy_map.policy_deg_to_move_cmd([50, 0, 50, 0, 50, 0, 50, 0])
    assert cmd == "i8 50 12 0 9 50 13 0 10 50 14 0 11 50 15 0"
