"""The low-battery alarm (2026-11-15: a pack at 30% never sounded it): a rest reading alerts at once, a low pack is read more often, and a run refused for a low pack sounds the alert."""
from pi_pipeline.power import battery
from pi_pipeline.power.battery import BatteryLevel, BatteryMonitor, BatteryWatcher


def test_three_confirming_readings_are_still_needed_for_a_reading_taken_under_load():
    m = BatteryMonitor(7.54, 7.46)
    assert m.update(7.50, 0.0) is None and m.update(7.50, 1.0) is None                  # not confirmed
    assert m.update(7.50, 2.0) == BatteryLevel.LOW


def test_one_rest_reading_at_or_below_the_low_voltage_alerts_at_once():
    m = BatteryMonitor(7.54, 7.46)
    assert m.update(7.53, 0.0, immediate=True) == BatteryLevel.LOW
    assert m.update(7.60, 1.0, immediate=True) is None                                  # above low: no alert (and not counted as one)
    m2 = BatteryMonitor(7.54, 7.46)
    assert m2.update(7.40, 0.0, immediate=True) == BatteryLevel.CRITICAL


def test_a_rest_reading_is_read_again_and_the_better_one_decides_so_a_sag_does_not_alarm():
    reads = iter([7.50, 7.70])                                                          # low, then recovered after resting
    alerts, slept = [], []
    w = BatteryWatcher(lambda: next(reads), lambda lvl, v: alerts.append((lvl, v)), monitor=BatteryMonitor(7.54, 7.46), sleep=slept.append)
    assert w.poll_once(rest=True) is None and alerts == [] and slept == [5.0]
    reads2 = iter([7.50, 7.48])                                                         # still low after the re-read
    w2 = BatteryWatcher(lambda: next(reads2), lambda lvl, v: alerts.append((lvl, v)), monitor=BatteryMonitor(7.54, 7.46), sleep=lambda s: None)
    assert w2.poll_once(rest=True) == BatteryLevel.LOW and alerts == [(BatteryLevel.LOW, 7.50)]


def test_a_reading_that_is_not_at_rest_never_alerts_alone_and_does_not_wait():
    slept = []
    w = BatteryWatcher(lambda: 7.40, lambda *_: None, monitor=BatteryMonitor(7.54, 7.46), sleep=slept.append)
    assert w.poll_once() is None and slept == []                                        # before a walk: one reading, no 5 s wait, needs the usual three


def test_a_low_pack_is_read_more_often_than_the_idle_backstop():
    w = BatteryWatcher(lambda: 7.60, lambda *_: None, monitor=BatteryMonitor(7.54, 7.46), poll_s=1800.0, poll_low_s=300.0, poll_low_v=7.7, sleep=lambda s: None)
    assert w.next_gap_s() == 1800.0                                                     # nothing read yet
    w.poll_once(rest=True)
    assert w.last_volts == 7.60 and w.next_gap_s() == 300.0                             # 7.60 V is under 7.7: every 5 min, not once in 30
    w2 = BatteryWatcher(lambda: 7.95, lambda *_: None, monitor=BatteryMonitor(7.54, 7.46), poll_s=1800.0, poll_low_s=300.0, poll_low_v=7.7, sleep=lambda s: None)
    w2.poll_once(rest=True)
    assert w2.next_gap_s() == 1800.0                                                    # a healthy pack keeps the slow backstop
    w3 = BatteryWatcher(lambda: 7.60, lambda *_: None, monitor=BatteryMonitor(7.54, 7.46), poll_s=1800.0, poll_low_s=0.0, sleep=lambda s: None)
    w3.poll_once(rest=True)
    assert w3.next_gap_s() == 1800.0                                                    # poll_low_s 0 turns the faster poll off


def test_a_refused_run_sounds_the_alert_once_a_minute(monkeypatch):
    got = []
    battery.set_refusal_alert(lambda lvl, v: got.append((lvl, v)))
    monkeypatch.setattr(battery, "_last_refusal", -1e9)
    try:
        class L:
            pass
        monkeypatch.setattr(battery, "read_voltage", lambda link, attempts=3, drain_s=0.2: 7.48)
        ok, pct, v = battery.settled_gate(L(), rest_reads=1, rest_s=0.0, sleep=lambda s: None)
        assert not ok and got == [(BatteryLevel.LOW, 7.48)]
        battery.settled_gate(L(), rest_reads=1, rest_s=0.0, sleep=lambda s: None)
        assert len(got) == 1                                                            # a second refusal inside a minute is not announced again
        monkeypatch.setattr(battery, "_last_refusal", -1e9)
        monkeypatch.setattr(battery, "read_voltage", lambda link, attempts=3, drain_s=0.2: 7.40)
        battery.settled_gate(L(), rest_reads=0, rest_s=0.0, sleep=lambda s: None)
        assert got[-1][0] == BatteryLevel.CRITICAL
    finally:
        battery.set_refusal_alert(None)


def test_a_passing_gate_and_an_unreadable_pack_sound_nothing(monkeypatch):
    got = []
    battery.set_refusal_alert(lambda lvl, v: got.append(v))
    monkeypatch.setattr(battery, "_last_refusal", -1e9)
    try:
        monkeypatch.setattr(battery, "read_voltage", lambda link, attempts=3, drain_s=0.2: 7.90)
        assert battery.settled_gate(object(), rest_reads=0)[0] is True
        monkeypatch.setattr(battery, "read_voltage", lambda link, attempts=3, drain_s=0.2: None)
        battery.settled_gate(object(), rest_reads=0, sleep=lambda s: None)
        assert got == []
    finally:
        battery.set_refusal_alert(None)
