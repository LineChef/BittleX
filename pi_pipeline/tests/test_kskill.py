"""The `K`-skill stand-up (link/kskill.py): the message format and the link's use of it."""
import pytest

from pi_pipeline.gait import standup
from pi_pipeline.link import kskill


def test_payload_layout_matches_a_behavior_skill():
    frames = kskill.stand_frames([64, -50, 64, -50, 74, -56, 74, -56], [15, 56, 15, 56, 20, 50, 20, 50], 59, 0, steps=6)
    data = kskill.behavior_payload(frames, [12] * 6, [2] * 6)
    assert len(data) == 7 + 6 * kskill.FRAME_LEN
    header = [b - 256 if b > 127 else b for b in data[:7]]
    assert header == [-6, 0, 0, 1, 0, 0, 0]                                   # six frames, no loop
    f0 = [b - 256 if b > 127 else b for b in data[7:7 + 20]]
    assert f0[16:] == [12, 2, 0, 0]                                           # speed, delay, no trigger
    last = [b - 256 if b > 127 else b for b in data[7 + 5 * 20:7 + 6 * 20]]
    assert last[1] == 0 and last[8] == 15 and last[9] == 15 and last[10] == 20 and last[12] == 56      # the last frame is the balance pose, lift at its walking angle


def test_both_sides_move_together_and_the_rear_legs_lead():
    start, goal = [64, -50, 64, -50, 74, -56, 74, -56], [15, 56, 15, 56, 20, 50, 20, 50]
    frames = kskill.stand_frames(start, goal, steps=10)
    for f in frames:
        assert f[8] == f[9] and f[10] == f[11] and f[12] == f[13] and f[14] == f[15]          # left and right the same in every frame
    first = frames[0]
    rear_moved = abs(first[10] - 74) / abs(20 - 74)
    front_moved = abs(first[8] - 64) / abs(15 - 64)
    assert rear_moved > front_moved                                           # the back legs are further along at the start


def test_message_is_k_payload_tilde_and_never_holds_the_terminator():
    msg = kskill.message(kskill.stand_payload([64, -50, 64, -50, 74, -56, 74, -56], [15, 56, 15, 56, 20, 50, 20, 50], 59, 0, steps=18, speed_raw=12, delay_raw=2))
    assert msg[:1] == b"K" and msg[-1:] == b"~" and b"~" not in msg[1:-1]
    assert len(msg) <= kskill.BUFF_LEN
    with pytest.raises(ValueError):
        kskill.message(b"abc~def")
    with pytest.raises(ValueError):
        kskill.behavior_payload([[0] * 16] * 200, [1] * 200, [1] * 200)         # too big for the buffer


def test_the_link_plays_the_stand_up_as_a_k_skill_only_when_asked(monkeypatch):
    from pi_pipeline.link import serial_link
    from pi_pipeline.link.serial_link import SerialLink
    prof = {"stand_via": "kbalance", "rest_urdf_deg": [64, -50, 64, -50, 74, -56, 74, -56], "balance_urdf_deg": [15, 56, 15, 56, 20, 50, 20, 50], "arm_rest": 59, "arm_walk": 0}
    monkeypatch.setattr(standup, "_poses", lambda: prof)
    monkeypatch.setattr(serial_link.time, "sleep", lambda s: None)
    wrote = []

    class Ser:
        is_open = True
        def write(self, b): wrote.append(bytes(b))
        def flush(self): pass
    lk = SerialLink("/dev/null")
    lk._ser = Ser()
    lk.last_motion_command = "krest"
    monkeypatch.delenv("G2_STAND_VIA", raising=False)
    assert lk._stand_up_kskill(standup) is False and wrote == []              # the profile says kbalance
    monkeypatch.setenv("G2_STAND_VIA", "kskill")
    assert lk._stand_up_kskill(standup) is True and wrote[0][:1] == b"K" and wrote[0][-1:] == b"~"
    lk.last_motion_command = "kwkF"
    wrote.clear()
    assert lk._stand_up_kskill(standup) is False and wrote == []              # only from rest


def test_the_timing_comes_from_the_motion_feel_file_the_override_and_the_environment(monkeypatch, tmp_path):
    from pi_pipeline import motion_feel as mf
    ov = tmp_path / "feel.json"
    monkeypatch.setenv("G2_MOTION_FEEL", str(ov))
    for k in ("G2_STAND_STEPS", "G2_STAND_SPEED", "G2_STAND_PAUSE", "G2_STAND_WAIT_S"):
        monkeypatch.delenv(k, raising=False)
    assert kskill.tuning() == {"steps": 8, "speed": 20, "delay": 0, "wait_s": 2.6}              # the numbers in the file
    ov.write_text('{"STAND_SPEED": 16, "STAND_WAIT_S": 3.0}')
    t = kskill.tuning()
    assert t["speed"] == 16 and t["wait_s"] == 3.0 and t["steps"] == 8                           # the override file wins, only for what it names
    monkeypatch.setenv("G2_STAND_SPEED", "12")
    assert kskill.tuning()["speed"] == 12                                                         # the environment wins over both
    monkeypatch.setenv("G2_STAND_SPEED", "junk")
    ov.write_text("not json")
    assert kskill.tuning()["speed"] == 20 and mf.get("CLAW_DEG_S") == 60.0                       # junk falls through to the file's number
