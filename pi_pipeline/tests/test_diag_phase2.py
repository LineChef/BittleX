import json

import pytest

from pi_pipeline.diag import RingBuffer
from pi_pipeline.diag.core import Diag
from pi_pipeline.diag.sysmon import Sysmon, SysmonConfig
from pi_pipeline.diag.watchdog import (
    Watchdog, WatchdogConfig, WatchdogCore, WatchVerdict,
)


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_LOG_DIR", str(tmp_path))
    dg = Diag()
    yield dg
    if dg._fp:
        dg.close()


def _man(dg):
    return json.loads((dg.session_dir / "manifest.json").read_text())


# --------------------------------------------------------------- core additions
def test_close_finalizes_the_manifest(d):
    d.start_session("gait")
    d.event("gait", "INFO", "a")
    d.event("gait", "WARN", "b")
    d.close()
    man = _man(d)
    assert man["clean_exit"] is True
    assert "duration_s" in man and "ended_wall" in man
    assert man["event_counts"]["WARN"] >= 1
    assert man["incident_count"] == 0


def test_incident_flushes_the_black_box_and_counts(d):
    d.start_session("gait")
    d.attach_ring(RingBuffer(seconds=1, hz=10)).push(x=1)
    d.incident("gait", "servo.stall", joint=2, err_deg=24.0)
    assert list(d.session_dir.glob("blackbox_*.csv"))
    d.close()
    assert _man(d)["incident_count"] == 1


def test_taxonomy_name_flushes_even_at_info(d):
    d.start_session("gait")
    d.attach_ring(RingBuffer(seconds=1, hz=10)).push(x=1)
    d.event("gait", "INFO", "battery.sag", voltage=6.1)   # INFO, but a taxonomy name
    assert list(d.session_dir.glob("blackbox_*.csv"))


def test_excepthook_logs_fatal_and_marks_unclean(d, monkeypatch):
    import sys
    d.start_session("t")
    d.install_excepthook()
    d.install_excepthook()                                # idempotent
    try:
        raise ValueError("kaboom")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    evs = [json.loads(l) for l in (d.session_dir / "events.jsonl").read_text().splitlines() if l]
    fatal = [e for e in evs if e["name"] == "unhandled.exception"]
    assert fatal and "kaboom" in fatal[0]["err"]
    assert _man(d)["clean_exit"] is False


# --------------------------------------------------------------- WatchdogCore
def test_core_ok_before_start():
    c = WatchdogCore()
    assert c.poll(1.0)[0] is WatchVerdict.OK


def test_core_emits_periodic_heartbeat_with_hz():
    c = WatchdogCore(WatchdogConfig(heartbeat_every_s=1.0, stall_after_s=5.0, startup_grace_s=0.0))
    c.start(0.0)
    for k in range(1, 41):                 # 40 beats over 0.8 s -> ~50 Hz
        c.beat(k * 0.02)
    v, ctx = c.poll(1.0)
    assert v is WatchVerdict.HEARTBEAT
    assert 40 <= ctx["loop_hz"] <= 60


def test_core_detects_a_stall_once_per_episode():
    c = WatchdogCore(WatchdogConfig(stall_after_s=0.25, startup_grace_s=0.5, heartbeat_every_s=10.0))
    c.start(0.0)
    c.beat(0.6)
    assert c.poll(0.7)[0] is WatchVerdict.OK          # fresh beat
    v, ctx = c.poll(1.0)                              # 0.4 s silent
    assert v is WatchVerdict.STALL and ctx["silent_s"] >= 0.25
    assert c.poll(1.1)[0] is WatchVerdict.OK          # latched -- doesn't re-fire
    c.beat(1.2)
    v, _ = c.poll(1.6)                                # silent again -> fires again
    assert v is WatchVerdict.STALL


def test_core_startup_grace_suppresses_stall():
    c = WatchdogCore(WatchdogConfig(stall_after_s=0.1, startup_grace_s=2.0, heartbeat_every_s=10.0))
    c.start(0.0)
    assert c.poll(1.5)[0] is WatchVerdict.OK          # no beats, but still in grace


# --------------------------------------------------------------- Watchdog thread
def test_watchdog_thread_fires_on_stall_and_calls_on_stall():
    fired = []
    events = []
    wd = Watchdog(WatchdogConfig(stall_after_s=0.1, startup_grace_s=0.0, heartbeat_every_s=10.0),
                  on_stall=lambda: fired.append(1),
                  emit=lambda s, l, n, **kv: events.append(n),
                  poll_interval_s=0.02)
    wd.start()
    wd.beat()
    import time
    time.sleep(0.4)                                   # stop beating
    wd.stop()
    assert fired and "loop.stall" in events


# --------------------------------------------------------------- Sysmon
def test_sysmon_is_a_noop_when_readers_return_none(monkeypatch):
    import pi_pipeline.diag.sysmon as sm
    monkeypatch.setattr(sm, "read_battery_v", lambda: None)
    monkeypatch.setattr(sm, "read_pi_throttled", lambda: None)
    monkeypatch.setattr(sm, "read_soc_temp_c", lambda: None)
    got = []
    reading = Sysmon().sample(lambda *a, **k: got.append(a))
    assert reading == {} and got == []


def test_sysmon_emits_battery_sag_rate_limited(monkeypatch):
    import pi_pipeline.diag.sysmon as sm
    monkeypatch.setattr(sm, "read_battery_v", lambda: 6.0)
    monkeypatch.setattr(sm, "read_pi_throttled", lambda: None)
    monkeypatch.setattr(sm, "read_soc_temp_c", lambda: None)
    t = [0.0]
    mon = Sysmon(SysmonConfig(batt_sag_v=6.4, repeat_every_s=30.0), clock=lambda: t[0])
    got = []
    mon.sample(lambda s, l, n, **kv: got.append(n))
    t[0] = 10.0
    mon.sample(lambda s, l, n, **kv: got.append(n))   # still within repeat window
    t[0] = 45.0
    mon.sample(lambda s, l, n, **kv: got.append(n))
    assert got == ["battery.sag", "battery.sag"]      # not the middle one
