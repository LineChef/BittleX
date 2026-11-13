"""The `K`-skill stand-up (link/kskill.py): the message format and the link's use of it."""
import pytest

from pi_pipeline import motion_feel
from pi_pipeline.gait import standup
from pi_pipeline.link import kskill


def _legs_reported(monkeypatch, prof, *, reached=True):
    """The board's `j` reply for the tests: the legs at the stand pose (reached) or still at rest (not yet)."""
    goal = prof["balance_urdf_deg"] if reached else prof["rest_urdf_deg"]
    j = [0] * 16
    for k in range(8):
        j[kskill.URDF_TO_SERVO[k]] = goal[k]
    monkeypatch.setattr(kskill, "read_joints", lambda link, **kw: list(j))
    return j


def _k_message(wrote):
    """The K message the link sent: the chunks from the one starting with 'K' to the one ending with '~', joined."""
    start = next(i for i, w in enumerate(wrote) if w[:1] == b"K")
    out = b""
    for w in wrote[start:]:
        out += w
        if out.endswith(b"~"):
            return out
    return out


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


def _speeds(slow, mid):
    """The per-stage speeds the file's numbers give: STAND_SLOW_STAGES slow ones at each end, the middle ones fast."""
    n, k = int(motion_feel.STAND_STEPS), int(motion_feel.STAND_SLOW_STAGES)
    return [int(slow) if (i < k or i >= n - k) else int(mid) for i in range(n)]


def test_the_timing_comes_from_the_motion_feel_file_the_override_and_the_environment(monkeypatch, tmp_path):
    from pi_pipeline import motion_feel as mf
    ov = tmp_path / "feel.json"
    monkeypatch.setenv("G2_MOTION_FEEL", str(ov))
    for k in ("G2_STAND_STEPS", "G2_STAND_SPEED", "G2_STAND_PAUSE", "G2_STAND_WAIT_S"):
        monkeypatch.delenv(k, raising=False)
    assert kskill.tuning() == {"steps": 8, "speed": 12, "speeds": _speeds(motion_feel.STAND_SPEED, motion_feel.STAND_SPEED_MID), "delay": 0, "wait_s": 3.4, "front_start": 0.2, "rear_end": 0.7}      # the numbers in the file (slow at the ends, fast in the middle)
    ov.write_text('{"STAND_SPEED": 16, "STAND_WAIT_S": 3.0}')
    t = kskill.tuning()
    assert t["speed"] == 16 and t["wait_s"] == 3.0 and t["steps"] == 8                           # the override file wins, only for what it names
    monkeypatch.setenv("G2_STAND_SPEED", "12")
    assert kskill.tuning()["speed"] == 12                                                         # the environment wins over both
    monkeypatch.setenv("G2_STAND_SPEED", "junk")
    ov.write_text("not json")
    assert kskill.tuning()["speed"] == 12 and mf.get("CLAW_DEG_S") == 60.0                       # junk falls through to the file's number


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


def test_the_stand_up_waits_for_the_board_and_forces_the_pose_if_it_never_gets_there(monkeypatch):
    """2026-11-08: the Pi moved on after a fixed wait while the board was still rising. Now it polls the board's joint reading until the legs reach the stand pose; if they never do, it forces them there."""
    from pi_pipeline.link import serial_link
    from pi_pipeline.link.serial_link import SerialLink
    prof = {"stand_via": "kbalance", "rest_urdf_deg": [64, -50, 64, -50, 74, -56, 74, -56], "balance_urdf_deg": [15, 56, 15, 56, 20, 50, 20, 50], "arm_rest": 59, "arm_walk": 0}
    monkeypatch.setattr(standup, "_poses", lambda: prof)
    monkeypatch.setattr(serial_link.time, "sleep", lambda s: None)
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    for k in ("G2_GYRO_BALANCE", "G2_STAND_VIA", "G2_STAND_GYRO"):
        monkeypatch.delenv(k, raising=False)
    wrote = []

    class Ser:
        is_open = True
        def write(self, b): wrote.append(bytes(b))
        def flush(self): pass
    lk = SerialLink("/dev/null")
    lk._ser = Ser()
    # still at rest on every poll: it keeps waiting, then forces the stand pose with two full leg commands
    _legs_reported(monkeypatch, prof, reached=False)
    lk.last_motion_command = "krest"
    assert lk._stand_up_kskill(standup) is True
    forced = [w for w in wrote if w.startswith(b"i8 ")]
    assert len(forced) == 2 and forced[0].strip() == standup.move_cmd(standup.balance_pose()).encode()
    # the legs arrive on the third poll: no forcing
    wrote.clear()
    seq = iter([False, False, True])
    goal = prof["balance_urdf_deg"]
    rest = prof["rest_urdf_deg"]

    def reading(link, **kw):
        legs = goal if next(seq) else rest
        j = [0] * 16
        for k in range(8):
            j[kskill.URDF_TO_SERVO[k]] = legs[k]
        return j
    monkeypatch.setattr(kskill, "read_joints", reading)
    lk.last_motion_command = "krest"
    assert lk._stand_up_kskill(standup) is True
    assert not [w for w in wrote if w.startswith(b"i8 ")]


def test_the_k_message_goes_out_in_short_pieces_and_the_legs_check_is_tolerant():
    sent = []
    kskill.write_chunked(sent.append, bytes(range(100)), sleep=lambda s: None)
    assert all(len(c) <= kskill.CHUNK_BYTES for c in sent) and b"".join(sent) == bytes(range(100))
    goal = [15, 56, 15, 56, 20, 50, 20, 50]
    j = [0] * 16
    for k in range(8):
        j[kskill.URDF_TO_SERVO[k]] = goal[k] + 4
    assert kskill.legs_reached(j, goal) is True                      # within 6 deg
    j[kskill.URDF_TO_SERVO[3]] = goal[3] + 12
    assert kskill.legs_reached(j, goal) is False and kskill.legs_reached(None, goal) is False


def _arm_link(monkeypatch, wrote, *, reached=True):
    from pi_pipeline.link import serial_link
    from pi_pipeline.link.serial_link import SerialLink
    prof = {"stand_via": "kbalance", "rest_urdf_deg": [64, -50, 64, -50, 74, -56, 74, -56], "balance_urdf_deg": [15, 56, 15, 56, 20, 50, 20, 50], "arm_rest": 59, "arm_walk": 0}
    monkeypatch.setattr(standup, "_poses", lambda: prof)
    _legs_reported(monkeypatch, prof, reached=reached)
    monkeypatch.setattr(serial_link.time, "sleep", lambda s: None)
    monkeypatch.setenv("G2_ATTACHMENT", "arm")
    for k in ("G2_GYRO_BALANCE", "G2_STAND_VIA", "G2_STAND_GYRO"):
        monkeypatch.delenv(k, raising=False)

    class Ser:
        is_open = True
        def write(self, b): wrote.append(bytes(b))
        def flush(self): pass
    lk = SerialLink("/dev/null")
    lk._ser = Ser()
    return lk


def test_the_eased_stand_up_runs_from_rest_sit_and_the_attention_pose(monkeypatch):
    """Owner, 2026-11-08, a hard rule: every stand-up is the eased K stand-up. From rest, a sit and the attention pose; the gyro on for the rise and off right after."""
    wrote = []
    lk = _arm_link(monkeypatch, wrote)
    for last, lift_in_first in (("krest", True), ("ksit", False), ("kcalib", False)):
        wrote.clear()
        lk.last_motion_command = last
        assert lk._stand_up_kskill(standup) is True
        assert wrote[0].strip() == b"gB" and wrote[-1].strip() == b"gb"                  # gyro on for the rise, off right after
        k = _k_message(wrote)
        assert k[:1] == b"K" and k[-1:] == b"~" and b"~" not in k[1:-1]
        first = [b - 256 if b > 127 else b for b in k[8:8 + 20]]
        assert (first[1] > 0) == lift_in_first                                           # the lift servo eases only from rest (the claw is already down from a sit or the attention pose)


def test_no_switch_turns_it_off_and_other_starts_read_the_board(monkeypatch):
    wrote = []
    lk = _arm_link(monkeypatch, wrote)
    for v in ("kbalance", "sequenced", "kskill"):
        monkeypatch.setenv("G2_STAND_VIA", v)
        wrote.clear()
        lk.last_motion_command = "krest"
        assert lk._stand_up_kskill(standup) is True and _k_message(wrote)[:1] == b"K"     # the environment cannot bring back another stand-up
    monkeypatch.delenv("G2_STAND_VIA")
    wrote.clear()
    lk.last_motion_command = ""                                                          # a fresh process: the legs the board reports are the start
    assert lk._stand_up_kskill(standup) is True and _k_message(wrote)[:1] == b"K"
    monkeypatch.setattr(kskill, "read_joints", lambda link, **kw: None)                   # the pose is unreadable (owner, 2026-11-09): he is laid in rest first, then stood up from rest
    wrote.clear()
    lk.last_motion_command = ""
    assert lk._stand_up_kskill(standup) is True
    assert wrote[0].strip() == b"krest" and wrote[1].strip() == b"gb" and _k_message(wrote)[:1] == b"K"          # the rest comes before the K stand-up, never a firmware stand-up


def test_when_the_eased_stand_up_cannot_run_the_command_is_dropped_not_sent_as_a_firmware_stand_up(monkeypatch):
    from pi_pipeline.link.serial_link import SerialLink
    wrote = []
    lk = _arm_link(monkeypatch, wrote)
    monkeypatch.setattr(SerialLink, "is_connected", property(lambda self: True))
    monkeypatch.setattr(kskill, "read_joints", lambda link, **kw: None)
    lk.last_motion_command = ""                                                          # unknown start, no answer from the board
    lk._ease_transition = SerialLink._ease_transition.__get__(lk)
    assert lk.send("kbalance", read_reply=False, settle=0.0) == ""
    assert not any(w.strip() == b"kbalance" for w in wrote)                              # no firmware stand-up reached the wire


def test_the_attention_stand_up_has_its_own_slower_numbers(monkeypatch, tmp_path):
    monkeypatch.setenv("G2_MOTION_FEEL", str(tmp_path / "none.json"))
    for k in ("G2_STAND_SPEED", "G2_STAND_ATT_SPEED", "G2_STAND_SPEED_MID", "G2_STAND_ATT_SPEED_MID", "G2_STAND_WAIT_S", "G2_STAND_ATT_WAIT_S"):
        monkeypatch.delenv(k, raising=False)
    rest, att = kskill.tuning(), kskill.tuning(from_attention=True)
    assert rest["speeds"] == _speeds(motion_feel.STAND_SPEED, motion_feel.STAND_SPEED_MID) and rest["wait_s"] == 3.4          # the rest stand-up is unchanged
    assert att["speeds"] == [10, 10, 22, 22, 22, 22, 10, 10] and att["wait_s"] == 4.0            # the attention-pose stand-up is a little slower
    assert att["speed"] < rest["speed"]                                                       # slower at the first and last stages (the middle stages are the owner's to tune either way)


def test_the_move_into_the_attention_pose_is_an_eased_k_skill_and_kcalib_is_not_sent(monkeypatch):
    """Owner, 2026-11-08: he sat hard into the attention position. The Pi plays the move as an eased K skill (untested on G2 until the next session)."""
    from pi_pipeline.link.serial_link import SerialLink
    wrote = []
    lk = _arm_link(monkeypatch, wrote)
    prof = standup._poses()
    att_legs = [0] * 16
    monkeypatch.setattr(kskill, "read_joints", lambda link, **kw: [0] * 16)                    # the legs read as straight: the attention pose reached
    monkeypatch.setattr(SerialLink, "is_connected", property(lambda self: True))
    lk.last_motion_command = "kbalance"
    assert lk.send("kcalib", read_reply=False, settle=0.0) == ""
    assert not any(w.strip() == b"kcalib" for w in wrote)                                         # the firmware kcalib never reached the wire
    k = _k_message(wrote)
    assert k[:1] == b"K" and k[-1:] == b"~" and lk.last_motion_command == "kcalib"
    n = [b - 256 if b > 127 else b for b in k[1:8]]
    assert n[0] == -6                                                                            # six stages
    last = [b - 256 if b > 127 else b for b in k[1 + 7 + 5 * 20:1 + 7 + 6 * 20]]
    assert last[8:16] == [0] * 8 and last[0:8] == [0] * 8                                        # the last stage is the attention pose (legs straight), the arm joints at 0
    wrote.clear()
    assert lk._attention_entry_eased() is True and wrote == []                                   # already there: nothing is sent
    lk.last_motion_command = "kwkF"
    assert lk._attention_entry_eased() is False and wrote == []                                  # an unknown pose: the caller sends the firmware kcalib as before
    monkeypatch.setenv("G2_ATT_ENTRY_EASED", "0")
    lk.last_motion_command = "kbalance"
    assert lk._attention_entry_eased() is False                                                  # switched off in motion_feel
    del att_legs, prof


def test_the_eased_entry_is_left_to_finish_not_forced_when_the_board_does_not_report_it(monkeypatch):
    wrote = []
    lk = _arm_link(monkeypatch, wrote)
    monkeypatch.setattr(kskill, "read_joints", lambda link, **kw: [30] * 16)                    # still standing
    monkeypatch.delenv("G2_ATT_ENTRY_EASED", raising=False)
    lk.last_motion_command = "kbalance"
    assert lk._attention_entry_eased() is True
    assert not [w for w in wrote if w.startswith(b"i8 ")]                                       # no forced jump to legs straight (owner, 2026-11-12: it snapped him down)


def _legs_joints(urdf_legs):
    j = [0] * 16
    for k in range(8):
        j[kskill.URDF_TO_SERVO[k]] = urdf_legs[k]
    return j


def test_the_pose_is_read_before_every_stand_up_an_unknown_one_gets_a_rest_first(monkeypatch, tmp_path):
    """Owner, 2026-11-09: read the pose before every stand-up; if it is unknown or unexpected, send the rest command first, then stand up. And every stand-up is logged."""
    import json
    monkeypatch.setenv("G2_MOTION_EVENTS", str(tmp_path / "ev.jsonl"))
    wrote = []
    lk = _arm_link(monkeypatch, wrote)
    prof = standup._poses()
    goal = prof["balance_urdf_deg"]
    # 1. the board reports a sit while the Pi last sent krest: the read pose wins (a sit start), no rest first
    monkeypatch.setattr(kskill, "read_joints", lambda link, **kw: _legs_joints(standup.SIT_URDF_DEG))
    lk.last_motion_command = "krest"
    assert lk._stand_up_kskill(standup) is True
    assert not any(w.strip() == b"krest" for w in wrote)
    # 2. legs in a readable pose that is none of the known ones (the survey bow): eased up from the angles the board reports, no rest first (owner, 2026-11-10)
    wrote.clear()
    odd = [a + 40 for a in goal]
    reads = iter([_legs_joints(odd), _legs_joints(odd)] + [_legs_joints(goal)] * 50)
    monkeypatch.setattr(kskill, "read_joints", lambda link, **kw: next(reads))
    lk.last_motion_command = "kbalance"
    assert lk._stand_up_kskill(standup) is True
    assert not any(w.strip() == b"krest" for w in wrote) and _k_message(wrote)[:1] == b"K"
    # 3. unreadable on every try: three reads, then the rest first as well
    wrote.clear()
    n = []
    monkeypatch.setattr(kskill, "read_joints", lambda link, **kw: n.append(1) or None)
    lk.last_motion_command = ""
    assert lk._stand_up_kskill(standup) is True and wrote[0].strip() == b"krest" and len(n) >= 3
    ev = [e for e in (json.loads(line) for line in open(tmp_path / "ev.jsonl")) if e["event"] == "stand_up"]          # (a `stand_up_start` line is written before each rise)
    assert [e["event"] for e in ev] == ["stand_up"] * 3
    assert [e["pose_read"] for e in ev] == ["sit", "unknown", "unknown"] and [e["rested_first"] for e in ev] == [False, False, True]
    assert ev[0]["start"] == "ksit" and ev[1]["start"] == "unknown" and ev[1]["eased_from_reported"] is True and all("seconds" in e and e["outcome"] in ("reached", "forced") for e in ev)


def test_the_attention_stand_up_has_the_back_legs_finish_before_the_front_legs_get_going():
    """Owner, 2026-11-12: the back legs stand first. From the attention pose the back legs are at their stand angles by the fifth of eight stages while the front legs are still near the start;
    the stand-up from rest keeps its own timing."""
    from pi_pipeline.gait import standup
    goal = standup.balance_pose()
    t, r = kskill.tuning(from_attention=True), kskill.tuning()
    assert (t["front_start"], t["rear_end"]) == (0.45, 0.65) and (r["front_start"], r["rear_end"]) == (0.2, 0.7)
    fr = kskill.stand_frames([0.0] * 8, goal, None, None, t["steps"], t["front_start"], t["rear_end"])

    def done(frame, idx):
        return sum(frame[kskill.URDF_TO_SERVO[k]] / goal[k] for k in idx) / len(idx)
    assert done(fr[4], (4, 5, 6, 7)) > 0.98 and done(fr[4], (0, 1, 2, 3)) < 0.3
    assert all(done(fr[i], (0, 1, 2, 3)) < 0.05 for i in range(3))            # the front legs have not moved in the first three stages
