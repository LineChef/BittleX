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


def test_nothing_happens_without_a_test(tmp_path):
    p = tmp_path / "rt.json"
    t = Boot().tracker(p)
    assert t.collect() is None and t.test() is None and t.runs() == []
    assert not p.exists()                               # no test, no file, no writes


def test_a_test_that_lost_power_is_recorded_as_the_time_between_start_and_last_beat(tmp_path):
    p = tmp_path / "rt.json"
    m = Boot("boot-1", up=60.0)
    t = m.tracker(p)
    assert t.arm()
    m.up = 60.0 + 5400.0; t.beat()                      # last heartbeat 1.5 h in, then the power dies
    m.up = 61.0; m.boot_id = "boot-2"                   # next boot
    t2 = m.tracker(p)
    msg = t2.collect()
    assert [r["runtime_s"] for r in t2.runs()] == [5400] and "1.50 h" in msg
    assert t2.test() is None and t2.collect() is None   # settled once


def test_a_clean_shutdown_during_a_test_discards_it(tmp_path):
    p = tmp_path / "rt.json"
    m = Boot("boot-1", up=10.0)
    t = m.tracker(p)
    t.arm()
    m.up = 3000.0; t.beat()
    data = json.loads(p.read_text()); data["test"]["ended_clean"] = True; p.write_text(json.dumps(data))   # what run_heartbeat does on a clean shutdown
    m.boot_id = "boot-2"
    t2 = m.tracker(p)
    assert "discarded" in t2.collect() and t2.runs() == []


def test_a_test_still_running_on_this_boot_is_not_collected_or_restarted(tmp_path):
    m = Boot("boot-1")
    t = m.tracker(tmp_path / "rt.json")
    assert t.arm() and not t.arm()
    assert t.collect() is None and t.test() is not None


def test_cancel_clears_the_test(tmp_path):
    t = Boot().tracker(tmp_path / "rt.json")
    t.arm()
    assert t.cancel() and t.test() is None and not t.cancel()


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
    assert w.poll_once() is None                        # nothing measured yet: stays quiet
    t.add_run(10000)
    for up in (7000, 7900, 8000, 8100):
        m.up = float(up); now[0] += 60; w.poll_once()
    assert alerts == [(BatteryLevel.LOW, 0.8)]          # once at 80%, not again within the repeat interval
    m.up = 9600.0; now[0] += 60; w.poll_once()
    assert alerts[-1] == (BatteryLevel.CRITICAL, 0.96)
    m.up = 9600.0; now[0] += 301; w.poll_once()
    assert len(alerts) == 3                             # repeats after the interval


def test_a_configured_full_runtime_overrides_the_recorded_mean(tmp_path):
    m = Boot(up=1800.0)
    t = m.tracker(tmp_path / "rt.json"); t.add_run(100000)
    alerts = []
    RuntimeWatcher(t, lambda lv, u: alerts.append(lv), full_runtime_s=2000).poll_once()
    assert alerts == [BatteryLevel.LOW]


def test_the_watcher_is_off_by_default():
    from pi_pipeline.config import Settings
    assert Settings().pi_battery_watch is False


def test_pi_alert_sounds_the_siren_then_names_the_pi_battery():
    from pi_pipeline.voice.__main__ import make_pi_battery_alert
    events = []
    tts = type("T", (), {"speak": lambda self, t: events.append(("say", t))})()
    on_alert = make_pi_battery_alert(tts, audible=True, siren=lambda: events.append("siren"))
    on_alert(BatteryLevel.LOW, 0.8)
    assert events == ["siren", ("say", "My Pi battery is at about twenty percent.")]
