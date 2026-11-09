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


def test_the_link_plays_the_stand_up_as_a_k_skill_by_default_and_not_when_switched_off(monkeypatch):
    from pi_pipeline.link import serial_link
    from pi_pipeline.link.serial_link import SerialLink
    prof = {"stand_via": "kbalance", "rest_urdf_deg": [64, -50, 64, -50, 74, -56, 74, -56], "balance_urdf_deg": [15, 56, 15, 56, 20, 50, 20, 50], "arm_rest": 59, "arm_walk": 0}
    monkeypatch.setattr(standup, "_poses", lambda: prof)
    monkeypatch.setattr(serial_link.time, "sleep", lambda s: None)
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    monkeypatch.delenv("G2_GYRO_BALANCE", raising=False)
    wrote = []

    class Ser:
        is_open = True
        def write(self, b): wrote.append(bytes(b).strip())
        def flush(self): pass
    lk = SerialLink("/dev/null")
    lk._ser = Ser()
    lk.last_motion_command = "krest"
    monkeypatch.setenv("G2_STAND_VIA", "kbalance")
    assert lk._stand_up_kskill(standup) is False and wrote == []              # switched off for the run: the plain firmware stand-up
    monkeypatch.delenv("G2_STAND_VIA")
    monkeypatch.delenv("G2_STAND_GYRO", raising=False)
    assert lk._stand_up_kskill(standup) is True                               # the default
    assert wrote[0] == b"gB" and wrote[1][:1] == b"K" and wrote[1][-1:] == b"~" and wrote[2] == b"gb"      # the gyro on for the rise, the skill, the gyro off right after
    lk.last_motion_command = "kwkF"
    wrote.clear()
    assert lk._stand_up_kskill(standup) is False and wrote == []              # only from rest
    lk.last_motion_command = "krest"
    monkeypatch.setenv("G2_STAND_GYRO", "0")
    assert lk._stand_up_kskill(standup) is True and wrote[0][:1] == b"K" and b"gB" not in wrote and b"gb" not in wrote      # the gyro setting off: just the skill
    monkeypatch.setattr(standup, "_poses", lambda: None)
    lk.last_motion_command = "krest"
    assert lk._stand_up_kskill(standup) is False                              # the stock robot (no arm poses) keeps its own stand-up


def test_the_timing_comes_from_the_motion_feel_file_the_override_and_the_environment(monkeypatch, tmp_path):
    from pi_pipeline import motion_feel as mf
    ov = tmp_path / "feel.json"
    monkeypatch.setenv("G2_MOTION_FEEL", str(ov))
    for k in ("G2_STAND_STEPS", "G2_STAND_SPEED", "G2_STAND_PAUSE", "G2_STAND_WAIT_S"):
        monkeypatch.delenv(k, raising=False)
    assert kskill.tuning() == {"steps": 8, "speed": 12, "speeds": [12, 12, 28, 28, 28, 28, 12, 12], "delay": 0, "wait_s": 3.4}      # the numbers in the file (slow at the ends, fast in the middle)
    ov.write_text('{"STAND_SPEED": 16, "STAND_WAIT_S": 3.0}')
    t = kskill.tuning()
    assert t["speed"] == 16 and t["wait_s"] == 3.0 and t["steps"] == 8                           # the override file wins, only for what it names
    monkeypatch.setenv("G2_STAND_SPEED", "12")
    assert kskill.tuning()["speed"] == 12                                                         # the environment wins over both
    monkeypatch.setenv("G2_STAND_SPEED", "junk")
    ov.write_text("not json")
    assert kskill.tuning()["speed"] == 12 and mf.get("CLAW_DEG_S") == 60.0                       # junk falls through to the file's number


def test_the_k_stand_up_plays_with_the_gyro_on_when_asked(monkeypatch):
    """Owner, 2026-11-08: "turn the gyro on for the standup": G2_GYRO_BALANCE=1 sends gB before the K skill (and nothing turns it off during the rise)."""
    from pi_pipeline.link import serial_link
    from pi_pipeline.link.serial_link import SerialLink
    prof = {"stand_via": "kskill", "rest_urdf_deg": [64, -50, 64, -50, 74, -56, 74, -56], "balance_urdf_deg": [15, 56, 15, 56, 20, 50, 20, 50], "arm_rest": 59, "arm_walk": 0}
    monkeypatch.setattr(standup, "_poses", lambda: prof)
    monkeypatch.setattr(serial_link.time, "sleep", lambda s: None)
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    out = []

    class Ser:
        is_open = True
        def write(self, b): out.append(bytes(b))
        def flush(self): pass
    lk = SerialLink("/dev/null")
    lk._ser = Ser()
    lk.last_motion_command = "krest"
    monkeypatch.setenv("G2_GYRO_BALANCE", "0")
    monkeypatch.setenv("G2_STAND_GYRO", "0")
    assert lk._stand_up_kskill(standup) and out[0][:1] == b"K"                      # gyro off: just the skill
    out.clear()
    lk.last_motion_command = "krest"
    monkeypatch.setenv("G2_GYRO_BALANCE", "1")
    assert lk._stand_up_kskill(standup)
    assert out[0].strip() == b"gB" and out[1][:1] == b"K"                           # gyro on first, then the skill


def test_unequal_speed_is_slow_at_the_ends_and_fast_in_the_middle(monkeypatch, tmp_path):
    ov = tmp_path / "feel.json"
    ov.write_text('{"STAND_SPEED": 12, "STAND_SPEED_MID": 28, "STAND_SLOW_STAGES": 2}')
    monkeypatch.setenv("G2_MOTION_FEEL", str(ov))
    for k in ("G2_STAND_STEPS", "G2_STAND_SPEED", "G2_STAND_SPEED_MID", "G2_STAND_SLOW_STAGES"):
        monkeypatch.delenv(k, raising=False)
    t = kskill.tuning()
    assert t["speeds"] == [12, 12, 28, 28, 28, 28, 12, 12]
    data = kskill.stand_payload([64, -50, 64, -50, 74, -56, 74, -56], [15, 56, 15, 56, 20, 50, 20, 50], 59, 0, steps=8, speed_raw=12, speeds=t["speeds"])
    got = [data[7 + k * kskill.FRAME_LEN + 16] for k in range(8)]
    assert got == [12, 12, 28, 28, 28, 28, 12, 12]                                  # the speed byte of each frame


def test_the_k_stand_up_from_the_attention_pose_is_on_unless_switched_off(monkeypatch):
    """The attention-pose stand-up (where most of the 2026-11-07 falls were) uses the K skill (STAND_ATT_KSKILL, on since 2026-11-08); the legs start straight and the lift servo is not eased."""
    from pi_pipeline.link import serial_link
    from pi_pipeline.link.serial_link import SerialLink
    prof = {"stand_via": "kbalance", "rest_urdf_deg": [64, -50, 64, -50, 74, -56, 74, -56], "balance_urdf_deg": [15, 56, 15, 56, 20, 50, 20, 50], "arm_rest": 59, "arm_walk": 0}
    monkeypatch.setattr(standup, "_poses", lambda: prof)
    monkeypatch.setattr(serial_link.time, "sleep", lambda s: None)
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    monkeypatch.delenv("G2_GYRO_BALANCE", raising=False)
    monkeypatch.delenv("G2_STAND_VIA", raising=False)
    wrote = []

    class Ser:
        is_open = True
        def write(self, b): wrote.append(bytes(b))
        def flush(self): pass
    lk = SerialLink("/dev/null")
    lk._ser = Ser()
    lk.last_motion_command = "kcalib"
    monkeypatch.setenv("G2_STAND_ATT_KSKILL", "0")
    assert lk._stand_up_kskill(standup) is False and wrote == []              # switched off for the run
    monkeypatch.delenv("G2_STAND_ATT_KSKILL", raising=False)
    assert lk._stand_up_kskill(standup) is True                               # the default
    k = next(w for w in wrote if w[:1] == b"K")
    first = [b - 256 if b > 127 else b for b in k[8:8 + 20]]                  # frame 0
    assert first[1] == 0 and first[10] > 0                                    # the lift servo stays at 0 (not eased from 59); the rear legs have begun to rise from straight
