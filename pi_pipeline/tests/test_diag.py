import json

import pytest

from pi_pipeline.diag import RingBuffer
from pi_pipeline.diag.core import Diag


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_LOG_DIR", str(tmp_path))
    dg = Diag()
    yield dg
    dg.close()


def _events(dg):
    return [json.loads(l) for l in (dg.session_dir / "events.jsonl").read_text().splitlines() if l]


def test_session_and_manifest(d, tmp_path):
    sid = d.start_session("gait", policy_path=None, extra={"cmd_fwd": 0.1})
    assert (tmp_path / sid / "events.jsonl").exists()
    man = json.loads((tmp_path / sid / "manifest.json").read_text())
    assert man["session_id"] == sid
    assert man["subsystem_hint"] == "gait"
    assert "git" in man and "config" in man
    assert man["extra"]["cmd_fwd"] == 0.1


def test_event_written(d):
    d.start_session("t")
    d.event("gait", "WARN", "servo.thermal_warn", joint=2, hottest_frac=0.51)
    evs = _events(d)
    warn = [e for e in evs if e["name"] == "servo.thermal_warn"][0]
    assert warn["sub"] == "gait" and warn["lvl"] == "WARN"
    assert warn["joint"] == 2 and warn["hottest_frac"] == 0.51


def test_lazy_autostart(d):
    d.event("sys", "INFO", "hi")           # no explicit start_session
    assert d.session_id is not None
    assert any(e["name"] == "hi" for e in _events(d))


def test_ringbuffer_flush(tmp_path):
    r = RingBuffer(seconds=1, hz=10)       # maxlen 10
    for i in range(25):
        r.push(i=i, roll=i * 0.1, guard="ok")
    p = r.flush(tmp_path / "bb.csv")
    lines = (tmp_path / "bb.csv").read_text().splitlines()
    assert lines[0].split(",")[0] == "i"
    assert len(lines) == 1 + 10            # header + last 10 only
    assert lines[-1].startswith("24,")


def test_ring_autoflush_on_error_event(d):
    d.start_session("t")
    r = d.attach_ring(RingBuffer(seconds=1, hz=10))
    for i in range(10):
        r.push(i=i, guard="ok")
    d.event("gait", "ERROR", "servo.thermal_cooldown", reason="joint 2 hot")
    dumps = list(d.session_dir.glob("blackbox_*.csv"))
    assert len(dumps) == 1
    assert "guard" in dumps[0].read_text().splitlines()[0]


def test_flush_by_name_even_at_info(d):
    d.start_session("t")
    d.attach_ring(RingBuffer(seconds=1, hz=10)).push(x=1)
    d.event("recovery", "INFO", "fall.detected", roll=1.4)   # name is in _FLUSH_NAMES
    assert list(d.session_dir.glob("blackbox_*.csv"))
