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


def test_every_firmware_skill_that_raises_him_is_eased_from_lying_or_sitting(monkeypatch):
    """Standing rule (user, 2026-10-18): wave, check, nod and the rest stand him up through the firmware un-eased, so the link ramps first and the skill starts from a stand."""
    monkeypatch.setenv("G2_STAND_RAMP_S", "0.2")
    monkeypatch.setattr("pi_pipeline.link.serial_link.time.sleep", lambda s: None)
    for last in ("", "d", "krest", "kzz", "ksit"):
        for skill in ("khi", "kck", "kwh", "knd", "kscrh", "kstr", "kpu", "kcmh", "kbuttUp", "kwkF", "kup", "kbalance"):
            lk = _link_with(b"")
            lk.last_motion_command = last
            lk.send(skill, read_reply=False, settle=0.0)
            sent = [w.decode().strip() for w in lk._ser.written]
            assert sent[-1] == skill and len(sent) == 5 and all(c.startswith("i") for c in sent[:-1]), (last, skill, sent)


def test_skills_that_leave_him_down_and_skills_from_a_stand_are_not_ramped(monkeypatch):
    monkeypatch.setenv("G2_STAND_RAMP_S", "0.2")
    monkeypatch.setattr("pi_pipeline.link.serial_link.time.sleep", lambda s: None)
    for skill in ("krest", "ksit", "kzz", "kzero"):
        lk = _link_with(b"")
        lk.last_motion_command = "d"
        lk.send(skill, read_reply=False, settle=0.0)
        assert [w.decode().strip() for w in lk._ser.written] == [skill]
    for last in ("kbalance", "kup", "khi", "kwkF", "i8 50 12 0"):
        lk = _link_with(b"")
        lk.last_motion_command = last
        lk.send("khi", read_reply=False, settle=0.0)
        assert [w.decode().strip() for w in lk._ser.written] == ["khi"]
    lk = _link_with(b"")
    lk.last_motion_command = "d"
    lk.send("b9 5 16 8", read_reply=False, settle=0.0)                       # a beep or a head move is not a stand-up
    lk.send("m0 30", read_reply=False, settle=0.0)
    assert [w.decode().strip() for w in lk._ser.written] == ["b9 5 16 8", "m0 30"]


# ------------------------------------------------------------------ eased transitions into every skill (user, 2026-10-18)
def _ramped(monkeypatch, last, skill, *, stand="off", last_t=None):
    monkeypatch.setenv("G2_TRANSITION_RAMP_S", "0.8")
    monkeypatch.setenv("G2_STAND_RAMP_S", stand)
    monkeypatch.setattr("pi_pipeline.link.serial_link.time.sleep", lambda s: None)
    lk = _link_with(b"")
    lk.last_motion_command, lk._last_motion_t = last, last_t
    lk.send(skill, read_reply=False, settle=0.0)
    return [w.decode().strip() for w in lk._ser.written]


def test_a_trick_from_a_stand_eases_into_its_first_frame(monkeypatch):
    from pi_pipeline.link import transitions as tr
    sent = _ramped(monkeypatch, "kbalance", "khi")
    assert sent[-1] == "khi" and all(c.startswith("i8 ") for c in sent[:-1])
    hi = tr.table()["hi"]["first"]
    assert len(sent) - 1 == 15                                                    # largest joint move 82.5 deg (mirror mean) / 110 deg/s = 0.75 s at 20 steps/s
    last_pose = [int(x) for x in sent[-2].split()[1::2]]
    assert last_pose == [round((a + b) / 2) for a, b in zip(hi, tr.mirror(hi))]   # `hi` may be mirrored by the firmware: the mean of both sides
    assert "i0" not in " ".join(sent)                                             # the head is never moved by the ramp


def test_the_ramp_length_follows_the_largest_joint_move(monkeypatch):
    sent = _ramped(monkeypatch, "kbalance", "kvtL")                               # 8 deg: the 0.25 s minimum
    assert sent[-1] == "kvtL" and len(sent) - 1 == 5
    sent = _ramped(monkeypatch, "kbalance", "ktrL")                               # 31 deg -> 0.28 s
    assert len(sent) - 1 == 6
    assert _ramped(monkeypatch, "kbalance", "kup") == ["kup"]                      # already there / a stop: as it is


def test_from_lying_the_stand_up_runs_first_then_the_transition(monkeypatch):
    sent = _ramped(monkeypatch, "d", "kwkL", stand="0.2")
    assert sent[-1] == "kwkL" and len(sent) == 4 + 7 + 1                           # 4 stand-up steps, 37 deg balance -> wkL in 0.34 s, the skill


def test_lying_down_and_sitting_from_a_stand_are_eased_too(monkeypatch):
    from pi_pipeline.link import transitions as tr
    for skill, pose in (("krest", tr.REST), ("ksit", tr.table()["sit"]["first"])):
        sent = _ramped(monkeypatch, "kbalance", skill)
        assert sent[-1] == skill and sent[-2] == tr.leg_cmd(pose) and len(sent) > 5


def test_stops_unknown_poses_streams_and_get_ups_are_not_eased(monkeypatch):
    import time
    stride = "i8 50 9 50 10 50 11 50 12 0 13 0 14 0 15 0"
    assert _ramped(monkeypatch, stride, "kbalance") == ["kbalance"]               # a stop / freeze out of a stride
    assert _ramped(monkeypatch, "kwkF", "khi") == ["khi"]                         # after a firmware gait the legs could be anywhere
    assert _ramped(monkeypatch, "khi", "ksit") == ["ksit"]                        # after a trick too
    assert _ramped(monkeypatch, "kwkL", "kwkR") == ["kwkR"]                       # gait to gait
    assert _ramped(monkeypatch, stride, "khi", last_t=time.monotonic()) == ["khi"]   # a walk is streaming poses: the caller owns the motion
    assert len(_ramped(monkeypatch, stride, "khi", last_t=time.monotonic() - 2)) > 1  # a held pose is eased from
    for skill in ("krc", "krl", "kdropRec", "kzero", "kcalib", "kzz"):
        assert _ramped(monkeypatch, "kbalance", skill) == [skill]
    assert _ramped(monkeypatch, "kbalance", "d") == ["d"]                         # rest by `d` is also the fall / freeze token
    monkeypatch.setenv("G2_TRANSITION_RAMP_S", "off")
    monkeypatch.setattr("pi_pipeline.link.serial_link.time.sleep", lambda s: None)
    lk = _link_with(b""); lk.last_motion_command = "kbalance"
    lk.send("khi", read_reply=False, settle=0.0)
    assert [w.decode().strip() for w in lk._ser.written] == ["khi"]


def test_pose_tracking_and_mirroring():
    from pi_pipeline.link import transitions as tr
    assert tr.pose_after("d") == tr.REST and tr.pose_after("kbalance") == tr.BALANCE and tr.pose_after("ksit") == tr.table()["sit"]["first"]
    assert tr.pose_after("kwkF") is None and tr.pose_after("khi") is None and tr.pose_after("i0 30") is None
    assert tr.pose_after("i8 1 9 2 10 3 11 4 12 5 13 6 14 7 15 8") == [1, 2, 3, 4, 5, 6, 7, 8]
    wkl = tr.table()["wkL"]["first"]
    assert tr.target("kwkL") == wkl and tr.target("kwkR") == tr.mirror(wkl)        # L is never mirrored, R is its L mirrored
    assert tr.target("kbalance") is None and tr.target("knosuch") is None


def test_a_head_only_look_does_not_count_as_a_leg_move(monkeypatch):
    monkeypatch.setattr("pi_pipeline.link.serial_link.time.sleep", lambda s: None)
    lk = _link_with(b"")
    lk.send("d", read_reply=False, settle=0.0)
    lk.send("i0 30", read_reply=False, settle=0.0)
    assert lk.last_motion_command == "d"                                          # still lying: the next skill still gets the stand-up


def test_the_skill_frame_table_matches_the_firmware_header():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    if not (root / "rl_training/opencat-gym/reference_gait/InstinctBittleESP.h").exists():
        pytest.skip("firmware header not in this checkout")
    spec = importlib.util.spec_from_file_location("gen_skill_frames", root / "tools/gen_skill_frames.py")
    gen = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen)
    assert gen.main(["--check"]) == 0
    from pi_pipeline.link import transitions as tr
    from pi_pipeline.gait import standup
    assert tr.REST == [standup.REST_URDF_DEG[k] for k in (0, 2, 4, 6, 1, 3, 5, 7)] and tr.table()["rest"]["first"] == tr.REST
    assert tr.table()["sit"]["first"] == [standup.SIT_URDF_DEG[k] for k in (0, 2, 4, 6, 1, 3, 5, 7)]
