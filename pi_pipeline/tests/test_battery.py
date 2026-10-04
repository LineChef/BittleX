from pi_pipeline.power.battery import (BatteryLevel, BatteryMonitor, BatteryWatcher, parse_voltage, read_voltage)


def test_parse_voltage_handles_clean_and_noisy_replies():
    assert parse_voltage("Voltage: 7.89 V") == 7.89
    assert parse_voltage("G\nVoltage: 8.02 V\nP") == 8.02
    assert parse_voltage("imuException: 0") is None and parse_voltage(None) is None


def test_read_voltage_retries_past_stray_lines():
    replies = iter(["P", "", "Voltage: 7.5 V"])
    link = type("L", (), {"drain": lambda self, s: "", "send": lambda self, c: next(replies)})()
    assert read_voltage(link) == 7.5


def test_no_alert_while_healthy_or_before_enough_readings():
    m = BatteryMonitor(confirm=3)
    assert [m.update(v, t) for t, v in enumerate([7.9, 7.8, 7.8, 7.7])] == [None] * 4
    m2 = BatteryMonitor(confirm=3)
    assert [m2.update(6.9, t) for t in range(2)] == [None, None]


def test_low_alerts_once_confirmed_then_repeats_only_after_the_interval():
    m = BatteryMonitor(low_v=7.0, critical_v=6.6, confirm=3, repeat_s=300)
    out = [m.update(6.9, t) for t in range(3)]
    assert out == [None, None, BatteryLevel.LOW]
    assert m.update(6.9, 100) is None
    assert m.update(6.9, 400) is BatteryLevel.LOW


def test_a_single_sag_under_load_does_not_alert():
    m = BatteryMonitor(low_v=7.0, confirm=3)
    for t, v in enumerate([7.6, 6.5, 7.6, 7.5]):
        assert m.update(v, t) is None


def test_getting_worse_alerts_immediately_as_critical():
    m = BatteryMonitor(low_v=7.0, critical_v=6.6, confirm=3)
    for t in range(3):
        m.update(6.9, t)
    out = [m.update(6.5, 10 + t) for t in range(3)]
    assert out[-1] is BatteryLevel.CRITICAL


def test_recovery_needs_to_clear_the_hysteresis_band_and_then_can_alert_again():
    m = BatteryMonitor(low_v=7.0, confirm=2, hysteresis_v=0.15)
    m.update(6.9, 0); assert m.update(6.9, 1) is BatteryLevel.LOW
    m.update(7.05, 2); m.update(7.05, 3)
    assert m.level is BatteryLevel.LOW                        # inside the band: still low
    m.update(7.4, 4); m.update(7.4, 5)
    assert m.level is BatteryLevel.OK
    m.update(6.9, 6)
    assert m.update(6.9, 7) is BatteryLevel.LOW               # a fresh alert after recovering


def test_watcher_calls_the_alert_and_skips_missing_readings():
    readings = iter([None, 6.9, 6.9, 6.9])
    alerts = []
    w = BatteryWatcher(lambda: next(readings), lambda lv, v: alerts.append((lv, v)),
                       monitor=BatteryMonitor(confirm=3), poll_s=1)
    for _ in range(4):
        w.poll_once(now=0.0)
    assert alerts == [(BatteryLevel.LOW, 6.9)] and w.last_volts == 6.9


def test_a_failing_alert_handler_does_not_break_the_watcher():
    def boom(*a):
        raise RuntimeError("no speaker")
    w = BatteryWatcher(lambda: 6.0, boom, monitor=BatteryMonitor(confirm=1), poll_s=1)
    assert w.poll_once(now=0.0) is BatteryLevel.CRITICAL
