import pytest

from pi_pipeline.link import opencat
from pi_pipeline.link.serial_link import SerialLink


def test_skill_command_builder():
    assert opencat.skill("wkF") == "kwkF"
    assert opencat.skill(" sit ") == "ksit"
    with pytest.raises(ValueError):
        opencat.skill("")


def test_move_joints_builder():
    assert opencat.move_joints([(0, 30), (8, -35)]) == "m0 30 8 -35"
    with pytest.raises(ValueError):
        opencat.move_joints([])


def test_beep_builder():
    assert opencat.beep([(12, 8), (14, 8)]) == "b12 8 14 8"


def test_is_safe_blocks_calibration():
    assert opencat.is_safe("kbalance")
    assert opencat.is_safe("d")
    assert not opencat.is_safe("c")
    assert not opencat.is_safe("c 0")
    assert not opencat.is_safe("cd")
    assert not opencat.is_safe("")


def test_serial_link_send_without_connection_is_safe():
    """No pyserial / no port: connect() fails, send() returns '' and never raises."""
    link = SerialLink("/dev/nonexistent-xyz", 115200, auto_reconnect=True)
    assert link.is_connected is False
    assert link.connect() is False
    assert link.send("kbalance") == ""     # must not raise
    link.close()


def test_serial_link_list_ports_returns_list():
    ports = SerialLink.list_ports()
    assert isinstance(ports, list)


# ------------------------------------------------------------------ IMU demux
class _FakeSerial:
    """Enough of pyserial.Serial for SerialLink's read paths."""

    def __init__(self, data=b""):
        self.buf = bytearray(data)
        self.is_open = True
        self.written = []

    @property
    def in_waiting(self):
        return len(self.buf)

    def read(self, n):
        out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out

    def write(self, b):
        self.written.append(b)

    def flush(self):
        pass

    def close(self):
        self.is_open = False


def _link_with(data, read_timeout=0.05):
    lk = SerialLink("/dev/null", read_timeout=read_timeout)
    lk._ser = _FakeSerial(data)
    return lk


IMU = b"MCU:  0.00  0.00  1.00    0.0   1.0   2.0\r\n"


def test_reply_read_skips_interleaved_imu_frames():
    lk = _link_with(IMU + IMU + b"8.1\r\n" + IMU)
    assert lk.send("P", settle=0.0) == "8.1"
    assert lk.poll_imu() == [IMU.decode().strip()] * 3


def test_poll_imu_is_non_blocking_and_keeps_partial_lines():
    lk = _link_with(IMU + b"MCU:  0.00  0.")
    import time
    t0 = time.monotonic()
    assert lk.poll_imu() == [IMU.decode().strip()]
    assert time.monotonic() - t0 < 0.01
    lk._ser.buf += b"00  1.00    0.0   3.0   4.0\n"
    assert lk.poll_imu() == ["MCU:  0.00  0.00  1.00    0.0   3.0   4.0"]


def test_poll_imu_drops_move_command_echoes():
    lk = _link_with(b"m\r\n" + IMU + b"m\r\n")
    assert lk.poll_imu() == [IMU.decode().strip()]
    assert lk.read_line() == ""                    # echoes consumed, not queued as replies


def test_read_line_times_out_on_its_own_deadline():
    import time
    lk = _link_with(b"", read_timeout=0.05)
    t0 = time.monotonic()
    assert lk.read_line() == ""
    assert time.monotonic() - t0 < 0.2


# Over the Pi's UART2 link the BiBoard ends IMU frames with a TAB, not a newline
# (real capture 2026-09-30); only the trailing `gP` echo carries "\r\n".
ICM_TAB = b"ICM:  0.20  0.17 10.4717640.5    1.1    0.9\t"


def test_poll_imu_splits_tab_terminated_frames():
    lk = _link_with(ICM_TAB * 3 + b"g\r\n" + ICM_TAB + b"ICM:  0.2")
    assert lk.poll_imu() == [ICM_TAB.decode().strip()] * 4     # 4 whole frames, 1 partial kept
    assert lk.read_line() == ""                               # the `g` echo is not a reply
    lk._ser.buf += b"0  0.17 10.4717640.5    1.1    0.9\t"
    assert len(lk.poll_imu()) == 1                             # the partial frame completes


def test_tab_inside_a_non_imu_reply_is_not_split():
    lk = _link_with(b"S,\tA,\tT,\t\r\n1,\t1,\t0,\t\r\n")
    assert lk.read_line() == "S,\tA,\tT,"
    assert lk.read_line() == "1,\t1,\t0,"


# ------------------------------------------------------------------ eased stand-up (standing rule 2026-10-10)
def test_kup_from_rest_is_preceded_by_a_ramp_but_a_stop_kbalance_from_a_stride_is_not(monkeypatch):
    monkeypatch.setenv("G2_STAND_RAMP_S", "0.2")
    monkeypatch.setattr("pi_pipeline.link.serial_link.time.sleep", lambda s: None)
    lk = _link_with(b"")
    lk.send("kup", read_reply=False, settle=0.0)
    sent = [w.decode().strip() for w in lk._ser.written]
    assert sent[-1] == "kup" and len(sent) == 5 and all(c.startswith("i") for c in sent[:-1])     # 0.2 s x 20 steps/s = 4 ramp steps, then the skill
    assert lk.last_motion_command == "kup"
    lk._ser.written.clear()
    lk.last_motion_command = "i8 50 12 0 9 50 13 0 10 50 14 0 11 50 15 0"                          # mid-policy-walk: a freeze must be immediate
    lk.send("kbalance", read_reply=False, settle=0.0)
    assert [w.decode().strip() for w in lk._ser.written] == ["kbalance"]


def test_standup_helpers_agree_with_deploy_map_and_read_the_last_pose():
    from pi_pipeline.gait import standup, deploy_map
    deg = [50, 0, 50, 0, 50, 0, 50, 0]
    assert standup.move_cmd(deg) == deploy_map.policy_deg_to_move_cmd(deg)
    assert standup.start_pose("") == standup.REST_URDF_DEG and standup.start_pose("kbalance") == standup.BALANCE_URDF_DEG
    assert standup.start_pose(standup.move_cmd([40, 5, 41, 6, 42, 7, 43, 8])) == [40, 5, 41, 6, 42, 7, 43, 8]
    assert standup.start_pose("kwkF") is None and standup.start_pose("i1 2") is None


def test_a_firmware_walk_or_turn_started_from_sit_or_rest_is_eased_but_one_from_a_stride_is_not(monkeypatch):
    monkeypatch.setenv("G2_STAND_RAMP_S", "0.2")
    monkeypatch.setattr("pi_pipeline.link.serial_link.time.sleep", lambda s: None)
    from pi_pipeline.gait import standup
    lk = _link_with(b"")
    lk.last_motion_command = "ksit"                                       # he was sitting (the idle posture): the old start jerked into the gait un-eased (2026-10-10)
    lk.send("kwkL", read_reply=False, settle=0.0)
    sent = [w.decode().strip() for w in lk._ser.written]
    assert sent[-1] == "kwkL" and len(sent) == 5 and all(c.startswith("i") for c in sent[:-1])
    assert standup.start_pose("ksit") == standup.SIT_URDF_DEG
    lk._ser.written.clear()
    lk.last_motion_command = "d"
    lk.send("kwkR", read_reply=False, settle=0.0)
    assert [w.decode().strip() for w in lk._ser.written][-1] == "kwkR" and len(lk._ser.written) == 5
    lk._ser.written.clear()
    lk.last_motion_command = "kwkL"                                        # already walking: a turn token goes out as it is
    lk.send("kwkR", read_reply=False, settle=0.0)
    assert [w.decode().strip() for w in lk._ser.written] == ["kwkR"]
