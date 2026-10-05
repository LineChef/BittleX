import json

from pi_pipeline.power.battery import BatteryLevel
from pi_pipeline.power.runtime_tracker import RuntimeTracker, RuntimeWatcher


class Boot:
    """A fake machine: a boot id, an uptime counter, and whether the OS is shutting down."""
    def __init__(self, boot_id="boot-1", up=0.0):
        self.boot_id, self.up, self.shutting_down = boot_id, up, False

    def tracker(self, path):
        return RuntimeTracker(path, beat_s=3600, boot_id=lambda: self.boot_id, uptime=lambda: self.up,
                              shutting_down=lambda: self.shutting_down, wall=lambda: 1000.0 + self.up)


def test_a_boot_that_lost_power_is_logged_as_a_run_on_the_next_boot(tmp_path):
    p = tmp_path / "rt.json"
    m = Boot("boot-1", up=10.0)
    t = m.tracker(p).start()
    m.up = 5400.0; t.beat()                       # last heartbeat at 1.5 h, then the power dies (no stop())
    m2 = Boot("boot-2", up=5.0)
    t2 = m2.tracker(p).start()
    assert [r["runtime_s"] for r in t2.runs()] == [5400] and t2.mean_runtime_s() == 5400


def test_a_clean_shutdown_is_not_counted_as_a_battery_run(tmp_path):
    p = tmp_path / "rt.json"
    m = Boot("boot-1", up=10.0)
    t = m.tracker(p).start()
    m.up = 3000.0; m.shutting_down = True; t.stop()
    assert Boot("boot-2").tracker(p).start().runs() == []


def test_a_plain_service_restart_in_the_same_boot_keeps_the_boot_going(tmp_path):
    p = tmp_path / "rt.json"
    m = Boot("boot-1", up=100.0)
    t = m.tracker(p).start()
    m.up = 900.0; t.stop()                        # not shutting down: just a restart
    t2 = m.tracker(p).start()
    assert t2.runs() == [] and json.loads(p.read_text())["current"]["boot_id"] == "boot-1"


def test_mean_of_runs_ignores_forgotten_ones_and_survives_a_corrupt_file(tmp_path):
    p = tmp_path / "rt.json"
    t = Boot().tracker(p)
    t.add_run(3600); t.add_run(7200); t.add_run(600)
    assert t.mean_runtime_s() == (3600 + 7200 + 600) / 3
    assert t.forget_run(2) and t.mean_runtime_s() == 5400 and not t.forget_run(9)
    p.write_text("{not json")
    assert Boot().tracker(p).runs() == [] and Boot().tracker(p).mean_runtime_s() is None


def test_watcher_is_silent_until_a_runtime_is_known_then_warns_at_80_and_95_percent(tmp_path):
    m = Boot(up=0.0)
    t = m.tracker(tmp_path / "rt.json")
    alerts = []
    now = [0.0]
    w = RuntimeWatcher(t, lambda lv, u: alerts.append((lv, round(u, 2))), clock=lambda: now[0], repeat_s=300)
    m.up = 99999.0
    assert w.poll_once() is None                  # nothing measured yet: stays quiet
    t.add_run(10000)
    for up in (7000, 7900, 8000, 8100):
        m.up = float(up); now[0] += 60; w.poll_once()
    assert alerts == [(BatteryLevel.LOW, 0.8)]    # fires once at 80%, not again within the repeat interval
    m.up = 9600.0; now[0] += 60; w.poll_once()
    assert alerts[-1] == (BatteryLevel.CRITICAL, 0.96)
    m.up = 9600.0; now[0] += 301; w.poll_once()
    assert len(alerts) == 3                       # repeats after the interval


def test_a_configured_full_runtime_overrides_the_logged_mean(tmp_path):
    m = Boot(up=1800.0)
    t = m.tracker(tmp_path / "rt.json"); t.add_run(100000)
    alerts = []
    RuntimeWatcher(t, lambda lv, u: alerts.append(lv), full_runtime_s=2000).poll_once()
    assert alerts == [BatteryLevel.LOW]


def test_pi_alert_sounds_the_siren_then_names_the_pi_battery():
    from pi_pipeline.voice.__main__ import make_pi_battery_alert
    events = []
    tts = type("T", (), {"speak": lambda self, t: events.append(("say", t))})()
    on_alert = make_pi_battery_alert(tts, audible=True, siren=lambda: events.append("siren"))
    on_alert(BatteryLevel.LOW, 0.8)
    assert events == ["siren", ("say", "My Pi battery is at about twenty percent.")]
