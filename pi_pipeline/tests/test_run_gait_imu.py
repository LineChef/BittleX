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


# -------------------------------------------------------- yaw sign into the policy

def test_policy_quat_turns_a_firmware_right_turn_into_a_sim_negative_yaw(rg):
    """Firmware yaw (after imu_parse) is + for a RIGHT turn; PyBullet, where the policy
    was trained, is + for a LEFT turn. The policy must see the sim's sign."""
    import residual_policy
    r, p, y = residual_policy.quat_to_euler(rg.policy_quat(0.05, -0.03, math.radians(20.0)))
    assert y == pytest.approx(-math.radians(20.0))
    assert r == pytest.approx(0.05) and p == pytest.approx(-0.03)   # roll/pitch untouched


class _TurningRightLink:
    """First IMU frame heading 0, then G2 has turned 20 deg right. The line prints
    yaw negated (firmware `-ypr[0]`), so a +20 deg right turn prints -20.0."""

    def __init__(self):
        self.sent, self._n = [], 0

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return ""

    def poll_imu(self):
        self._n += 1
        return ["MCU:  0.00  0.00  1.00    0.0   0.0   0.0" if self._n == 1
                else "MCU:  0.00  0.00  1.00  -20.0   0.0   0.0"]


def test_loop_feeds_the_policy_sim_signed_yaw_and_logs_firmware_yaw(rg, monkeypatch, tmp_path):
    pytest.importorskip("onnxruntime")
    import residual_policy
    monkeypatch.setattr(rg, "diag", None)
    seen = []
    real_step = rg.ResidualGaitPolicy.step

    def spy(self, q, g):
        seen.append(residual_policy.quat_to_euler(q)[2])
        return real_step(self, q, g)

    monkeypatch.setattr(rg.ResidualGaitPolicy, "step", spy)
    log = tmp_path / "walk.csv"
    rg.run(_TurningRightLink(), 0.10, 0.2, 80.0, "auto", disable_firmware_balance=True,
           thermal_guard=False, send_every=1, log_path=str(log))
    assert seen and seen[-1] == pytest.approx(-math.radians(20.0), abs=1e-6)
    rows = [r for r in log.read_text().splitlines() if r[:1].isdigit()]
    assert float(rows[-1].split(",")[3]) == pytest.approx(math.radians(20.0), abs=1e-4)   # log: + = right


# -------------------------------------------------------- probe_imu_under_load

class _FakeLink:
    """sent: every command passed to _send(). poll_imu(): returns one canned
    IMU line per call so a bounded loop terminates instead of spinning on
    wall-clock time in a test."""

    def __init__(self, imu_lines_per_poll=1):
        self.sent = []
        self._n = imu_lines_per_poll

    def send(self, cmd, read_reply=True, settle=0.0):
        self.sent.append(cmd)
        return ""

    def poll_imu(self):
        return ["ICM:  0.10  0.20  0.98   10.0   -5.0    2.0"] * self._n


def test_probe_imu_under_load_sends_stand_pose_and_counts_imu_lines(rg, monkeypatch):
    lk = _FakeLink(imu_lines_per_poll=2)
    monkeypatch.setattr(rg.time, "sleep", lambda s: None)
    n = rg.probe_imu_under_load(lk, seconds=0.05, hz=rg.CONTROL_HZ)
    assert lk.sent[0] == "gP"          # start the continuous IMU stream first
    assert lk.sent[-2] == "gp"         # stop it
    assert lk.sent[-1] == "d"          # always leaves the robot resting
    # everything sent in between is the same neutral-stand command, matching
    # the real control loop's actual command (not a walking gait)
    stand_cmd = rg.deploy_map.policy_deg_to_move_cmd(rg.STAND_URDF_DEG)
    assert all(c == stand_cmd for c in lk.sent[1:-2])
    n_stand_cmds = len(lk.sent) - 3   # excludes 'gP', 'gp', 'd'
    assert n_stand_cmds > 0           # at least one stand command was actually sent
    assert n == n_stand_cmds * 2      # 2 IMU lines counted per poll, matching _FakeLink


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
           thermal_guard=False, send_every=1)      # every tick: isolates tick rate from send cadence
    moves = [c for c in lk.sent if c.startswith("i") and " " in c]
    assert len(moves) >= 70            # ~80 ticks in 1 s, minus the stand pose
    assert lk._emitted <= 16           # while only ~5 IMU frames/s arrived (incl. setup pauses)
    # balance off is the explicit "gb" (bare "g" toggles), restored on exit
    assert "g" not in lk.sent and lk.sent.index("gb") < lk.sent.index("gP")
    assert lk.sent[-1] == "d" and lk.sent[-2] == "gB"     # balance restored first, the rest LAST (gB right after d left G2 standing, 2026-10-06)


def test_gait_move_command_is_simultaneous_i_not_sequential_m():
    """`m` moves joints one at a time (>=144 ms per 8-joint command) -- the
    gait loop must send `i`, which moves them together."""
    from pi_pipeline.gait import deploy_map
    cmd = deploy_map.policy_deg_to_move_cmd([50, 0, 50, 0, 50, 0, 50, 0])
    assert cmd == "i8 50 12 0 9 50 13 0 10 50 14 0 11 50 15 0"


def test_send_every_n_thins_joint_commands_and_policy_path_is_accepted(rg, monkeypatch):
    """`--send-every 3` is what Release_CandidateV2/V2.1 were trained with (i@27):
    the loop still ticks at 80 Hz but sends a joint command only every 3rd tick."""
    pytest.importorskip("onnxruntime")
    monkeypatch.setattr(rg, "diag", None)
    every1, every3 = _FiveHzImuLink(), _FiveHzImuLink()
    import residual_policy
    path = residual_policy.default_policy_path()       # --policy PATH, here the default file
    rg.run(every1, 0.10, 1.0, 80.0, "auto", disable_firmware_balance=True,
           thermal_guard=False, policy_path=path, send_every=1)
    rg.run(every3, 0.10, 1.0, 80.0, "auto", disable_firmware_balance=True,
           thermal_guard=False, policy_path=path, send_every=3)
    n1 = len([c for c in every1.sent if c.startswith("i") and " " in c])
    n3 = len([c for c in every3.sent if c.startswith("i") and " " in c])
    assert n3 < n1 * 0.5 and n3 >= 20                  # ~1/3 as many (+ the stand pose)


def test_default_policy_sends_at_its_trained_cadence(rg, monkeypatch):
    """The deployed policy's sidecar says how often it was trained to send joint
    commands (V2.1: every 3rd tick); the loop follows that unless --send-every is given."""
    pytest.importorskip("onnxruntime")
    import residual_policy
    monkeypatch.setattr(rg, "diag", None)
    expect = residual_policy.send_every_for(residual_policy.default_policy_path())
    assert expect == 3, "deployed V2.1 sidecar should carry cmd_send_every_n=3"
    lk = _FiveHzImuLink()
    rg.run(lk, 0.10, 1.0, 80.0, "auto", disable_firmware_balance=True, thermal_guard=False)
    moves = [c for c in lk.sent if c.startswith("i") and " " in c]
    assert 20 <= len(moves) <= 40


class _FallenLink:
    """Reports a steady 90-degree roll (G2 on its side) on every poll."""

    def __init__(self):
        self.sent = []

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return ""

    def poll_imu(self):
        return ["MCU:  0.00  0.00  1.00    0.0   0.0  90.0"]


def test_fall_guard_rests_and_stops_the_loop_when_tilted_past_the_limit(rg, monkeypatch):
    pytest.importorskip("onnxruntime")
    import time
    monkeypatch.setattr(rg, "diag", None)
    lk = _FallenLink()
    t0 = time.monotonic()
    rg.run(lk, 0.10, 5.0, 80.0, "auto", disable_firmware_balance=True,
           thermal_guard=False, send_every=1)             # asked for 5 s
    assert time.monotonic() - t0 < 3.0                    # ...but it stopped after ~0.3 s of tilt
    assert lk.sent[-2:] == ["d", "gB"] or lk.sent[-1] == "d" or "d" in lk.sent[-3:]
    moves = [c for c in lk.sent if c.startswith("i") and " " in c]
    assert len(moves) < 60                                # not 400 ticks of driving a fallen robot


def test_fall_guard_can_be_disabled(rg, monkeypatch):
    pytest.importorskip("onnxruntime")
    monkeypatch.setattr(rg, "diag", None)
    lk = _FallenLink()
    rg.run(lk, 0.10, 0.5, 80.0, "auto", disable_firmware_balance=True,
           thermal_guard=False, send_every=1, fall_abort_deg=0)
    assert len([c for c in lk.sent if c.startswith("i") and " " in c]) >= 30   # ran its full 0.5 s


def test_openloop_lift_scale_widens_the_swing_and_logs_the_imu(rg, tmp_path):
    import numpy as np

    class _Lk:
        def __init__(self):
            self.sent = []

        def send(self, cmd, **kw):
            self.sent.append(cmd)

        def poll_imu(self):
            return ["MCU:  0.00  0.00  1.00    0.0   1.0   2.0"]

    def moves(scale, log=None):
        lk = _Lk()
        rg.openloop(lk, 1, 80.0, lift_scale=scale, log_path=log, sleep=lambda s: None,
                    balance_off=True)
        cmds = [c for c in lk.sent if c.startswith("i") and " " in c][1:]     # drop the stand pose
        return lk, np.array([[int(x) for x in c[1:].split()[1::2]] for c in cmds])

    _, base = moves(1.0)
    lk, wide = moves(1.6, str(tmp_path / "ol.csv"))
    assert (wide.max(0) - wide.min(0)).sum() > 1.4 * (base.max(0) - base.min(0)).sum()
    assert lk.sent[0] == "gb" and lk.sent[-1] == "d" and "gP" in lk.sent
    assert len((tmp_path / "ol.csv").read_text().splitlines()) > 50


def test_openloop_stops_when_fallen(rg):
    class _Lk:
        sent = []

        def send(self, cmd, **kw):
            self.sent.append(cmd)

        def poll_imu(self):
            return ["MCU:  0.00  0.00  1.00    0.0   0.0  90.0"]

    lk = _Lk()
    lk.sent = []
    t = [0.0]

    def clk():
        return t[0]

    def slp(s):
        t[0] += max(s, 0.01)

    rg.openloop(lk, 6, 80.0, sleep=slp, clock=clk)
    assert t[0] < 8.0                      # a full 6-cycle run is 7.5 s + the 2 s stand; it stopped early
    assert lk.sent[-1] == "d"


def test_openloop_knees_only_leaves_the_shoulder_swing_alone(rg):
    import numpy as np

    class _Lk:
        def __init__(self):
            self.sent = []

        def send(self, cmd, **kw):
            self.sent.append(cmd)

        def poll_imu(self):
            return []

    def swing(**kw):
        lk = _Lk()
        rg.openloop(lk, 1, 80.0, sleep=lambda s: None, fall_abort_deg=0, **kw)
        c = [x for x in lk.sent if x.startswith("i") and " " in x][1:]
        a = np.array([[int(v) for v in x[1:].split()[1::2]] for x in c])
        return a.max(0) - a.min(0)                       # per-joint swing, URDF order

    base = swing()
    knees = swing(lift_scale=2.0, lift_joints="knees")
    both = swing(lift_scale=2.0, lift_joints="knees", shoulder_scale=0.7)
    sh, kn = [0, 2, 4, 6], [1, 3, 5, 7]
    assert np.allclose(knees[sh], base[sh], atol=1)                  # shoulders untouched
    assert (knees[kn] > 1.8 * base[kn]).all()                        # knees ~x2
    assert (both[sh] < 0.8 * base[sh]).all()                         # shoulders shrunk


def test_openloop_ramp_starts_as_plain_wkf_and_reaches_the_scaled_gait(rg):
    import numpy as np

    class _Lk:
        def __init__(self):
            self.sent = []

        def send(self, cmd, **kw):
            self.sent.append(cmd)

        def poll_imu(self):
            return []

    def frames(**kw):
        lk = _Lk()
        rg.openloop(lk, 3, 80.0, sleep=lambda s: None, fall_abort_deg=0, **kw)
        c = [x for x in lk.sent if x.startswith("i") and " " in x][1:]
        return np.array([[int(v) for v in x[1:].split()[1::2]] for x in c])

    plain = frames()
    ramped = frames(lift_scale=2.0, lift_joints="knees", ramp_cycles=1.0)
    assert np.allclose(ramped[:5], plain[:5], atol=1)                      # first frames == plain wkF
    knees = [1, 3, 5, 7]
    last = slice(200, 300)                                                  # cycle 3: fully ramped
    assert (np.ptp(ramped[last][:, knees], axis=0) > 1.8 * np.ptp(plain[last][:, knees], axis=0)).all()


def test_openloop_logs_battery_voltage_during_the_walk(rg, tmp_path):
    class _Lk:
        def __init__(self):
            self.sent, self._other, self.n = [], [], 0

        def send(self, cmd, **kw):
            self.sent.append(cmd)
            if cmd == "P":
                self._other.append("Voltage: 7.55 V")

        def poll_imu(self):
            return ["MCU:  0.00  0.00  1.00    0.0   1.0   2.0"]

        def pop_other(self):
            out, self._other = self._other, []
            return out

    t = [0.0]

    def clk():
        return t[0]

    def slp(s):
        t[0] += max(s, 0.0125)

    lk = _Lk()
    rg.openloop(lk, 2, 80.0, log_path=str(tmp_path / "v.csv"), volt_every_s=0.5,
                sleep=slp, clock=clk, fall_abort_deg=0)
    rows = (tmp_path / "v.csv").read_text().splitlines()
    assert rows[1].endswith(",volt") and "P" in lk.sent
    assert any(r.endswith(",7.55") for r in rows[2:])


def test_openloop_holds_its_rate_when_sends_take_time_and_can_skip_frames(rg):
    """The pacing is a deadline, not a sleep after the work; send_every=3 sends every 3rd frame (the policy loop's cadence)."""
    clock_t = [0.0]

    class _Lk:
        sent = 0

        def send(self, cmd, **kw):
            if cmd.startswith("i"):
                self.sent += 1
                clock_t[0] += 0.005                      # a serial send blocks about 5 ms at 115200 baud

        def poll_imu(self):
            return []

    lk = _Lk()
    rg.openloop(lk, 2, 80.0, fall_abort_deg=0, send_every=3, sleep=lambda s: clock_t.__setitem__(0, clock_t[0] + s), clock=lambda: clock_t[0])
    # 2 cycles = 200 frames = 2.5 s of walk, after the 2 s stand sleep(2.0) (also on this fake clock) plus the stand command's own 5 ms
    assert 4.9 < clock_t[0] < 5.2                           # + the 0.5 s the walk now waits at the end so the board gets the rest command
    assert lk.sent == 1 + 67                                 # the stand command + every 3rd of 200 frames


def test_openloop_always_ends_with_the_rest_command(rg, tmp_path):
    """After a scripted walk G2 is told to rest, on a normal finish, after a fall, and after an error mid-walk."""
    class _Lk:
        def __init__(self, level=True):
            self.sent, self.level = [], level

        def send(self, cmd, **kw):
            self.sent.append(cmd)

        def poll_imu(self):
            return [] if self.level else ["MCU:  0.00  0.00  1.00    0.0   0.0  90.0"]

    ok = _Lk()
    rg.openloop(ok, 1, 80.0, log_path=str(tmp_path / "a.csv"), sleep=lambda s: None, send_every=3)
    assert ok.sent[-2:] == ["gp", "d"]
    fell = _Lk(level=False)
    rg.openloop(fell, 3, 80.0, log_path=str(tmp_path / "b.csv"), sleep=lambda s: None, send_every=3)
    assert fell.sent[-1] == "d"

    class _Boom(_Lk):
        def poll_imu(self):
            raise RuntimeError("serial gone")
    boom = _Boom()
    try:
        rg.openloop(boom, 1, 80.0, log_path=str(tmp_path / "c.csv"), sleep=lambda s: None)
    except RuntimeError:
        pass
    assert boom.sent[-1] == "d"


def test_openloop_restores_balance_before_rest_and_waits_so_the_board_gets_it(rg, tmp_path):
    class _Lk:
        def __init__(self):
            self.sent, self.t = [], 0.0

        def send(self, cmd, **kw):
            self.sent.append((cmd, self.t))

        def poll_imu(self):
            return []

    lk = _Lk()
    def slp(s):
        lk.t += s
    rg.openloop(lk, 1, 80.0, balance_off=True, log_path=str(tmp_path / "d.csv"), sleep=slp, clock=lambda: lk.t, fall_abort_deg=0, send_every=3)
    cmds = [c for c, _ in lk.sent]
    assert cmds[-3:] == ["gp", "gB", "d"]
    t_gB, t_d = lk.sent[-2][1], lk.sent[-1][1]
    assert t_d - t_gB >= 0.3 - 1e-9                      # the balance command has time to take effect before the rest
    assert lk.t - t_d >= 0.5 - 1e-9                      # and the rest has time to reach the board before the process exits


# -------------------------------------------------------- the extra log columns (--log-extra)

def test_accel_is_parsed_from_the_same_line_and_kept_on_the_feed(rg):
    import imu_parse
    assert imu_parse.parse_imu_accel("MCU:  0.02 -0.01  1.00  -12.3  45.6  -78.9") == pytest.approx((0.02, -0.01, 1.0))
    assert imu_parse.parse_imu_accel("ypr 1 2 3") is None
    feed = imu_parse.ImuFeed("auto", rate_mode="zero")
    assert feed.accel is None
    feed.update(["ICM: 0.10 0.20 0.98  10.0 -5.0 2.0"], 100.0)
    assert feed.accel == pytest.approx((0.10, 0.20, 0.98)) and feed.frames == 1
    feed.update(["Voltage: 7.9 V"], 100.1)                          # a non-IMU line changes nothing
    assert feed.frames == 1


def test_extra_columns_mark_fresh_frames_and_are_empty_when_off(rg):
    import imu_parse
    feed = imu_parse.ImuFeed("auto", rate_mode="zero")
    assert rg._extra_cols(feed, 1.0, 7.9, False) == ""
    cols = rg._extra_cols(feed, 1.0, float("nan"), True).split(",")           # before the first frame: nan accel, frame 0, nan age
    assert cols[0] == "" and cols[4] == "0" and cols[5] == "nan"
    feed.update(["MCU:  0.02 -0.01  1.00  -12.3  45.6  -78.9"], 1.0)
    a = rg._extra_cols(feed, 1.05, 7.9, True)
    feed.update([], 1.1)
    b = rg._extra_cols(feed, 1.1, 7.9, True)
    assert a.startswith(",0.02,-0.01,1.00,1,0.050,7.90")
    assert b.split(",")[4] == "1"                                                # same held frame: the counter did not move
    feed.update(["MCU:  0.03 -0.01  1.00  -12.3  45.6  -78.0"], 1.2)
    assert rg._extra_cols(feed, 1.2, 7.9, True).split(",")[4] == "2"            # a new frame: the counter moved


def test_log_extra_adds_the_columns_to_a_real_loop_log_and_default_logs_are_unchanged(rg, monkeypatch, tmp_path):
    pytest.importorskip("onnxruntime")
    monkeypatch.setattr(rg, "diag", None)
    plain, extra = tmp_path / "plain.csv", tmp_path / "extra.csv"
    rg.run(_TurningRightLink(), 0.10, 0.2, 80.0, "auto", disable_firmware_balance=True, thermal_guard=False, send_every=1, log_path=str(plain))
    rg.run(_TurningRightLink(), 0.10, 0.2, 80.0, "auto", disable_firmware_balance=True, thermal_guard=False, send_every=1, log_path=str(extra), log_extra=True)
    head_p = plain.read_text().splitlines()[1].split(",")
    lines_e = extra.read_text().splitlines()
    head_e = lines_e[1].split(",")
    assert head_e[:len(head_p)] == head_p and head_e[len(head_p):] == ["ax", "ay", "az", "imu_n", "imu_age_s", "volt"]
    rows = [r.split(",") for r in lines_e if r[:1].isdigit()]
    assert all(len(r) == len(head_e) for r in rows)
    assert rows[-1][len(head_p) + 2] == "1.00"                                    # az in g
    assert all(len(r.split(",")) == len(head_p) for r in plain.read_text().splitlines() if r[:1].isdigit())
