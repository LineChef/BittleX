"""Tilt around every lie-down (behavior/liedown_log.py): one line per lie-down with the tilt before and 1 s and 3 s after the rest command, written by the shared lie-downs."""
import json

import numpy as np
import pytest

from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.behavior import liedown_log as LL


def imu(roll, pitch):
    return f"ICM: 0.00 0.00 1.00 0.0 {pitch:.1f} {roll:.1f}"


class Clock:
    def __init__(self): self.t = 0.0
    def now(self): return self.t
    def sleep(self, s): self.t += s


class Link:
    """Every poll answers one IMU frame; the roll follows `roll_at(t)` so a flip can be staged."""
    def __init__(self, clock, roll_at, pitch=-5.0):
        self.sent, self.clock, self.roll_at, self.pitch, self.last_motion_command = [], clock, roll_at, pitch, ""
    def send(self, c, read_reply=False, settle=0.0):
        self.sent.append(c)
        return ""
    def poll_imu(self): return [imu(self.roll_at(self.clock.t), self.pitch)]
    def pop_other(self): return []
    def drain(self, s=0.0): return None


def _robot(tmp_path, monkeypatch, roll_at, on=True):
    monkeypatch.setenv("G2_LIEDOWN_LOG", str(tmp_path / "ld.jsonl") if on else "0")
    monkeypatch.delenv("G2_LIEDOWN_TIMES", raising=False)
    c = Clock()
    r = bc.SerialRobot(Link(c, roll_at), sleep=c.sleep, clock=c.now)
    return r, c


def _lines(tmp_path):
    p = tmp_path / "ld.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_the_trace_records_the_tilt_before_and_at_1_s_and_3_s(tmp_path, monkeypatch):
    r, _ = _robot(tmp_path, monkeypatch, lambda t: 10.0 + 4.0 * t)                      # the roll climbs 4 deg every second
    rec = LL.trace(r, "test", before=(-12.0, 22.0), volts=7.9)
    assert rec["before"] == [-12.0, 22.0] and rec["pack_v"] == 7.9 and rec["why"] == "test"
    assert set(rec["after"]) == {"1s", "3s"}
    assert rec["after"]["1s"][1] == pytest.approx(14.0, abs=1.0) and rec["after"]["3s"][1] == pytest.approx(22.0, abs=1.0)
    assert rec["flipped"] is False and rec["peak_deg"] > 20
    assert _lines(tmp_path)[0]["after"]["3s"] == rec["after"]["3s"]


def test_a_flip_is_marked_and_the_marks_can_be_changed(tmp_path, monkeypatch):
    r, _ = _robot(tmp_path, monkeypatch, lambda t: 178.0)
    monkeypatch.setenv("G2_LIEDOWN_TIMES", "1,3,10")
    rec = LL.trace(r, "flip")
    assert rec["flipped"] is True and set(rec["after"]) == {"1s", "3s", "10s"}


def test_it_is_off_with_the_switch_and_never_raises(tmp_path, monkeypatch):
    r, _ = _robot(tmp_path, monkeypatch, lambda t: 0.0, on=False)
    assert LL.trace(r, "off") is None and _lines(tmp_path) == []
    assert LL.trace(object(), "no link") is None                                          # a robot with no IMU link


def test_rest_then_stand_logs_the_lie_down_after_the_rest_command(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "wait_for_pose", lambda *a, **k: "rest")
    r, _ = _robot(tmp_path, monkeypatch, lambda t: 15.0)
    r.claw_pose = lambda *a, **k: "ok"
    r._stand_up_from = lambda pose: "ok"
    assert r.rest_then_stand() == "ok"
    sent = r._lk.sent
    assert "krest" in sent
    lines = _lines(tmp_path)
    assert len(lines) == 1 and lines[0]["why"] == "rest then stand" and lines[0]["after"]["3s"] is not None


def test_a_body_found_fallen_is_traced_too(tmp_path, monkeypatch):
    r, _ = _robot(tmp_path, monkeypatch, lambda t: 170.0)
    assert r._already_fell((0.0, 170.0)) is True
    lines = _lines(tmp_path)
    assert lines and lines[0]["why"] == "found fallen before a move" and lines[0]["before"] == [0.0, 170.0]


def test_the_sag_line_carries_the_pack_read_now(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_SAG_LOG", str(tmp_path / "sag.jsonl"))
    monkeypatch.setenv("G2_LIEDOWN_LOG", "0")
    r, _ = _robot(tmp_path, monkeypatch, lambda t: 0.0, on=False)
    from pi_pipeline.power import battery
    monkeypatch.setattr(battery, "read_voltage", lambda link, **k: 7.77)
    r._log_sag((-20.0, 3.0))
    rec = json.loads((tmp_path / "sag.jsonl").read_text().splitlines()[0])
    assert rec["pack_live_v"] == 7.77 and "pack_v" in rec


def test_with_the_log_off_the_lie_down_takes_no_extra_time(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "wait_for_pose", lambda *a, **k: "rest")
    r, c = _robot(tmp_path, monkeypatch, lambda t: 0.0, on=False)
    r.claw_pose = lambda *a, **k: "ok"
    r._stand_up_from = lambda pose: "ok"
    t0 = c.t
    r.rest_then_stand()
    assert c.t - t0 < 2.0 and np.isfinite(c.t)


def test_a_clock_that_does_not_advance_cannot_hold_the_lie_down(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_LIEDOWN_LOG", str(tmp_path / "ld.jsonl"))
    c = Clock()
    r = bc.SerialRobot(Link(c, lambda t: 0.0), sleep=lambda s: None, clock=lambda: 0.0)
    assert LL.trace(r, "frozen clock") is not None


def test_the_tilt_before_is_the_last_one_read_and_no_new_read_is_made(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "wait_for_pose", lambda *a, **k: "rest")
    r, c = _robot(tmp_path, monkeypatch, lambda t: 5.0)
    r.claw_pose = lambda *a, **k: "ok"
    r._stand_up_from = lambda pose: "ok"
    reads = []
    orig = r._tilt
    r._tilt = lambda s=0.5: (reads.append(s), orig(s))[1]
    r._last_tilt_read = (c.t, (-12.0, 22.0))
    r.rest_then_stand()
    assert _lines(tmp_path)[0]["before"] == [-12.0, 22.0] and len(reads) == 1           # the one read is the check after the lie-down, as before
