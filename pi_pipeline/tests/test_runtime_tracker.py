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
    w = RuntimeWatcher(t, lambda lv, u: alerts.append((lv, round(u, 2))), clock=lambda: now[0], repeat_s=300, warn_fraction=0.8, critical_fraction=0.95, require_arm=False)
    m.up = 99999.0
    assert w.poll_once() is None                        # nothing measured yet: stays quiet
    t.add_run(10000, source="test")
    for up in (7000, 7900, 8000, 8100):
        m.up = float(up); now[0] += 60; w.poll_once()
    assert alerts == [(BatteryLevel.LOW, 0.8)]          # once at 80%, not again within the repeat interval
    m.up = 9600.0; now[0] += 60; w.poll_once()
    assert alerts[-1] == (BatteryLevel.CRITICAL, 0.96)
    m.up = 9600.0; now[0] += 301; w.poll_once()
    assert len(alerts) == 3                             # repeats after the interval


def test_a_configured_full_runtime_overrides_the_recorded_mean(tmp_path):
    m = Boot(up=1800.0)
    t = m.tracker(tmp_path / "rt.json"); t.add_run(100000, source="test")
    alerts = []
    RuntimeWatcher(t, lambda lv, u: alerts.append(lv), full_runtime_s=2000, warn_fraction=0.8, critical_fraction=0.95, require_arm=False).poll_once()
    assert alerts == [BatteryLevel.LOW]


def test_the_watcher_is_on_by_default_but_ignores_rough_manual_readings(tmp_path):
    from pi_pipeline.config import Settings
    assert Settings().pi_battery_watch is True
    m = Boot(up=99999.0)
    t = m.tracker(tmp_path / "rt.json"); t.add_run(6414)           # a manual reading: counted in the mean, not used to warn
    alerts = []
    RuntimeWatcher(t, lambda lv, u: alerts.append(lv), warn_fraction=0.8, critical_fraction=0.95, require_arm=False).poll_once()
    assert alerts == [] and t.mean_runtime_s() == 6414


def test_pi_alert_sounds_the_siren_then_names_the_pi_battery():
    from pi_pipeline.voice.__main__ import make_pi_battery_alert
    events = []
    tts = type("T", (), {"speak": lambda self, t: events.append(("say", t))})()
    on_alert = make_pi_battery_alert(tts, audible=True, sound=lambda: events.append("siren"))
    on_alert(BatteryLevel.LOW, 0.8)
    assert events == ["siren", ("say", "Pi battery is low.")]


# ---- "running on battery": the warning counts only after the person says so

def test_by_default_the_warning_counts_from_boot_and_plugged_in_pauses_it_and_unplugged_restarts_the_count(tmp_path):
    m = Boot("b1", up=0.0)
    t = m.tracker(tmp_path / "rt.json")
    t.add_run(10000, source="test")
    alerts, now = [], [0.0]
    w = RuntimeWatcher(t, lambda lv, u: alerts.append((lv, round(u, 2))), clock=lambda: now[0], repeat_s=300, warn_fraction=0.8, critical_fraction=0.95)    # counts from boot
    m.up = 7900.0; now[0] += 60
    assert w.poll_once() is None
    m.up = 8100.0; now[0] += 60
    assert w.poll_once() is BatteryLevel.LOW and alerts == [(BatteryLevel.LOW, 0.81)]               # 81% since boot
    t.disarm()                                                        # "you're plugged in": charging, pause
    m.up = 9800.0; now[0] += 400
    assert w.poll_once() is None and w.level is BatteryLevel.OK
    t.arm_now()                                                       # "you're unplugged" at uptime 9800: count from here
    m.up = 9800.0 + 7000; now[0] += 60
    assert w.poll_once() is None
    m.up = 9800.0 + 8200; now[0] += 60
    assert w.poll_once() is BatteryLevel.LOW


def test_manual_mode_stays_silent_until_the_person_says_unplugged(tmp_path):
    m = Boot("b1", up=9000.0)
    t = m.tracker(tmp_path / "rt.json"); t.add_run(10000, source="test")
    alerts, now = [], [0.0]
    w = RuntimeWatcher(t, lambda lv, u: alerts.append(lv), clock=lambda: now[0], warn_fraction=0.8, critical_fraction=0.95, require_arm=True)
    assert w.poll_once() is None and alerts == []                     # 9000 s up, but not told he is on battery
    t.arm_now(); m.up += 8100
    assert w.poll_once() is BatteryLevel.LOW


def test_the_plugged_in_and_unplugged_state_belongs_to_one_boot(tmp_path):
    p = tmp_path / "rt.json"
    m = Boot("b1", up=500.0)
    t = m.tracker(p)
    t.disarm()
    assert t.armed_elapsed_s(from_boot=True) is None                   # paused this boot
    m2 = Boot("b2", up=60.0)                                          # next boot: counting from boot again
    assert m2.tracker(p).armed_elapsed_s(from_boot=True) == 60.0


def test_voice_phrases_for_unplugged_and_plugged_in():
    from pi_pipeline.voice.commands import match_local_command
    for text in ("you're unplugged", "I unplugged you", "you are on battery", "you're running on battery"):
        assert match_local_command(text) == "unplugged", text
    for text in ("you're plugged in", "I plugged you in", "you are charging", "I put you on the charger"):
        assert match_local_command(text) == "plugged", text
    for text in ("walk forward", "what do you see", "tell me about the charger"):
        assert match_local_command(text) not in ("unplugged", "plugged"), text


def test_telling_g2_he_is_unplugged_arms_the_warning_and_he_says_so():
    import types as _t
    from pi_pipeline.voice.loop import VoiceLoop
    said, flags = [], []
    stt = _t.SimpleNamespace(listen=lambda timeout_s=None: "you're unplugged")
    lp = VoiceLoop(wake_word=_t.SimpleNamespace(wait=lambda: None), stt=stt, conversation=_t.SimpleNamespace(
                       send=lambda *a, **k: None, set_mood_hint=lambda h: None, set_narration_hint=lambda h: None),
                   tts=_t.SimpleNamespace(speak=said.append), actuator=_t.SimpleNamespace(perform=lambda *a, **k: None, stop=lambda: None),
                   cue=_t.SimpleNamespace(set=lambda s: None), follow_up_s=0.0, on_power=flags.append)
    lp._one_turn()
    assert flags == [True] and said and "on battery" in said[0]


def test_battery_state_reports_paused_unplugged_or_since_boot(tmp_path):
    m = Boot("b1", up=1000.0)
    t = m.tracker(tmp_path / "rt.json")
    assert t.battery_state() == ("since_boot", 1000.0)
    t.disarm()
    assert t.battery_state() == ("paused", None)
    t.arm_now(); m.up = 1600.0
    assert t.battery_state() == ("since_unplugged", 600.0)


def test_warn_fraction_is_configurable(tmp_path):
    t = RuntimeTracker(tmp_path / "r.json")
    alerts = []
    now = [0.0]
    w = RuntimeWatcher(t, lambda lv, u: alerts.append(lv), full_runtime_s=1000, clock=lambda: now[0], warn_fraction=0.5, require_arm=False)
    t.armed_elapsed_s = lambda from_boot=True: 600.0            # 60% of the runtime used: past a 0.5 warning, short of the default 0.8
    w.poll_once()
    assert alerts


def test_a_run_the_user_vouches_for_counts_for_the_warning_but_a_manual_one_does_not(tmp_path):
    t = Boot().tracker(tmp_path / "rt.json")
    t.add_run(6414)                                      # manual: in the plain mean only
    assert RuntimeWatcher(t, lambda *a: None).full_runtime_s() is None
    t.add_run(11376, source="confirmed")
    t.add_run(11776, source="confirmed")
    assert RuntimeWatcher(t, lambda *a: None).full_runtime_s() == 11576


def test_default_thresholds_are_30_percent_left_for_low_and_20_percent_left_for_critical(tmp_path):
    alerts = []
    now = [0.0]
    m = Boot(up=0.0)
    t = m.tracker(tmp_path / "rt2.json")
    w = RuntimeWatcher(t, lambda lv, u: alerts.append(lv), full_runtime_s=1000, clock=lambda: now[0], require_arm=False)
    for up, expect in ((690, None), (710, BatteryLevel.LOW), (790, BatteryLevel.LOW), (810, BatteryLevel.CRITICAL)):         # low repeats every 5 min while it stays low
        m.up = float(up); now[0] += 600
        assert w.poll_once() is expect
    assert alerts == [BatteryLevel.LOW, BatteryLevel.LOW, BatteryLevel.CRITICAL]
