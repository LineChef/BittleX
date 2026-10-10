"""The always-on power diary (power/power_log.py): sleep / wake lines, heartbeats, and a power loss turned into a measured Pi runtime."""
from pi_pipeline.power.power_log import PowerLog, format_line
from pi_pipeline.power.runtime_tracker import RuntimeTracker, RuntimeWatcher
from pi_pipeline.power.sleep_watch import SleepWatch


class Machine:
    def __init__(self, boot="boot-1", up=10.0):
        self.boot, self.up, self.shutting_down = boot, up, False

    def log(self, path):
        return PowerLog(path, boot_id=lambda: self.boot, uptime=lambda: self.up, wall=lambda: 1_000_000.0 + self.up,
                        shutting_down=lambda: self.shutting_down)

    def tracker(self, path):
        return RuntimeTracker(path, boot_id=lambda: self.boot, uptime=lambda: self.up, shutting_down=lambda: self.shutting_down)


def test_sleep_and_wake_are_logged_and_heartbeats_carry_the_state(tmp_path):
    m = Machine()
    pl = m.log(tmp_path / "p.jsonl")
    t = [0.0]
    w = SleepWatch(is_resting=lambda: True, after_s=300, clock=lambda: t[0], on_event=pl.event)
    t[0] = 301.0
    assert w.tick()
    pl.heartbeat()
    w.wake("wake word")
    pl.heartbeat()
    rows = pl.lines()
    assert [r["event"] for r in rows] == ["sleep", "alive", "wake", "alive"]
    assert rows[0]["rested_s"] == 301 and rows[1]["asleep"] is True and rows[2]["why"] == "wake word" and rows[3]["asleep"] is False
    assert "sleep" in format_line(rows[0])


def test_a_power_loss_becomes_a_counted_runtime_once(tmp_path):
    m = Machine("boot-1", up=10.0)
    pl = m.log(tmp_path / "p.jsonl").start(every_s=3600)
    m.up = 3600.0
    pl.event("sleep", rested_s=300)
    m.up = 11776.0
    pl.heartbeat()                                     # last sign of life, then the power dies (no stop line)
    m.boot, m.up = "boot-2", 20.0
    tr = m.tracker(tmp_path / "rt.json")
    pl2 = m.log(tmp_path / "p.jsonl")
    msg = pl2.collect_into(tr)
    assert "power lost" in msg and "asleep" in msg
    assert tr.runs() == [{"runtime_s": 11776, "ended": 1_000_000.0 + 11776.0, "source": "log", "counted": True}]
    assert RuntimeWatcher(tr, lambda *a: None).full_runtime_s() == 11776
    assert pl2.collect_into(tr) is None and len(tr.runs()) == 1     # settled once only


def test_a_clean_shutdown_or_a_stopped_service_is_not_a_full_runtime(tmp_path):
    m = Machine("boot-1", up=10.0)
    pl = m.log(tmp_path / "p.jsonl")
    m.up = 500.0
    m.shutting_down = True
    pl.stop()
    m.boot, m.shutting_down = "boot-2", False
    tr = m.tracker(tmp_path / "rt.json")
    assert "clean shutdown" in m.log(tmp_path / "p.jsonl").collect_into(tr) and tr.runs() == []
    m.up = 900.0
    m.log(tmp_path / "p.jsonl").stop()                 # the service stopped by hand (a walk), then the battery died
    m.boot = "boot-3"
    assert "lower bound" in m.log(tmp_path / "p.jsonl").collect_into(tr)
    assert tr.runs()[0]["counted"] is False and tr.mean_runtime_s() is None


def test_a_boot_already_recorded_by_a_battery_test_is_only_marked_settled(tmp_path):
    m = Machine("boot-1", up=10.0)
    m.log(tmp_path / "p.jsonl").heartbeat()
    m.boot = "boot-2"
    tr = m.tracker(tmp_path / "rt.json")
    assert "battery test" in m.log(tmp_path / "p.jsonl").collect_into(tr, record=False)
    assert tr.runs() == [] and m.log(tmp_path / "p.jsonl").collect_into(tr) is None


def test_a_line_cut_by_the_power_loss_is_skipped_and_the_log_is_trimmed(tmp_path):
    m = Machine()
    p = tmp_path / "p.jsonl"
    pl = PowerLog(p, boot_id=lambda: m.boot, uptime=lambda: m.up, wall=lambda: 0.0, shutting_down=lambda: False, max_lines=3)
    for _ in range(5):
        pl.heartbeat()
    with open(p, "a") as f:
        f.write('{"t": 1, "ev')
    assert len(pl.lines()) == 5
    pl.start(every_s=3600)
    pl.stop()
    assert [r["event"] for r in pl.lines()][-2:] == ["start", "stop"] and len(pl.lines()) <= 5
