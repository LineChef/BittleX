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


def test_alert_plays_the_siren_then_speaks_the_matching_line():
    from pi_pipeline.voice.__main__ import make_battery_alert
    events, said = [], []
    tts = type("T", (), {"speak": lambda self, t: events.append(("say", t))})()
    on_alert = make_battery_alert(tts, audible=True, sound=lambda: events.append(("siren",)))
    on_alert(BatteryLevel.LOW, 6.9)
    on_alert(BatteryLevel.CRITICAL, 6.5)
    assert events == [("siren",), ("say", "My battery is low."), ("siren",),
                      ("say", "My battery is critically low. Please charge me.")]


def test_a_silent_setup_neither_sounds_the_siren_nor_speaks():
    from pi_pipeline.voice.__main__ import make_battery_alert
    events = []
    tts = type("T", (), {"speak": lambda self, t: events.append(t)})()
    make_battery_alert(tts, audible=False, sound=lambda: events.append("siren"))(BatteryLevel.LOW, 6.9)
    assert events == []


def test_the_real_diag_event_call_does_not_raise():
    # regression: a keyword named `level` clashed with Diag.event's own `level` argument, so the siren never sounded
    from pi_pipeline.voice.__main__ import make_battery_alert
    tts = type("T", (), {"speak": lambda self, t: None})()
    make_battery_alert(tts, audible=False)(BatteryLevel.LOW, 6.9)


def test_serial_actuator_serialises_a_voltage_read_with_commands():
    import threading
    import time

    from pi_pipeline.voice.actuator import SerialActuator

    order, in_send = [], threading.Lock()

    class SlowLink:
        def send(self, cmd, **kw):
            assert in_send.acquire(blocking=False), "two threads were inside the link at once"
            try:
                order.append(cmd); time.sleep(0.03)
            finally:
                in_send.release()
            return "Voltage: 7.5 V" if cmd == "P" else ""

        def drain(self, s=0.2):
            assert in_send.acquire(blocking=False), "two threads were inside the link at once"
            in_send.release(); return ""

    act = SerialActuator("x", 1, link=SlowLink())
    t = threading.Thread(target=lambda: [act.read_voltage() for _ in range(4)])
    t.start()
    for _ in range(4):
        act.send_token("b1 4")
    t.join()
    assert "P" in order and "b1 4" in order


def test_voltage_history_is_recorded_at_most_every_interval_and_never_stops_the_watch(tmp_path):
    from pi_pipeline.power.battery import BatteryWatcher, make_voltage_log

    t = [0.0]
    path = tmp_path / "v.csv"
    w = BatteryWatcher(lambda: 7.84, lambda *a: None, record=make_voltage_log(str(path)), record_every_s=300, clock=lambda: t[0])
    for step in (0, 60, 120, 300, 360, 600):
        t[0] = step
        w.poll_once()
    lines = path.read_text().splitlines()
    assert lines[0] == "time,volts" and len(lines) == 1 + 3          # at 0 s, 300 s and 600 s
    assert lines[1].endswith(",7.84")

    bad = BatteryWatcher(lambda: 7.8, lambda *a: None, record=lambda v: 1 / 0)
    assert bad.poll_once() is None and bad.last_volts == 7.8


def test_voltage_log_rotates_when_large(tmp_path):
    from pi_pipeline.power.battery import make_voltage_log

    rec = make_voltage_log(str(tmp_path / "v.csv"), max_bytes=40)
    for _ in range(5):
        rec(7.5)
    assert (tmp_path / "v.csv.1").exists()
    assert make_voltage_log("") is None


def test_load_voltage_check_asks_periodically_and_alerts_on_a_sagging_pack():
    from pi_pipeline.power.battery import BatteryLevel, BatteryMonitor, LoadVoltageCheck

    sent, lines, seen = [], [], []
    chk = LoadVoltageCheck(sent.append, lambda: [lines.pop(0)] if lines else [], BatteryMonitor(7.2, 6.8, confirm=2), every_s=5,
                           on_reading=seen.append)
    assert chk.tick(0.0) is None and sent == ["P"]
    assert chk.tick(2.0) is None and sent == ["P"]                 # not yet time to ask again
    lines.append("Voltage: 7.50 V"); assert chk.tick(5.0) is None and sent == ["P", "P"]
    lines.append("Voltage: 7.10 V"); assert chk.tick(6.0) is None            # one low reading is not enough (confirm=2)
    lines.append("Voltage: 7.05 V"); assert chk.tick(7.0) == (BatteryLevel.LOW, 7.05)
    lines.append("echo of a joint command"); assert chk.tick(8.0) is None   # non-voltage lines are ignored
    lines.append("Voltage: 6.70 V"); lines.append("Voltage: 6.60 V")
    assert chk.tick(9.0) is None
    assert chk.tick(10.0) == (BatteryLevel.CRITICAL, 6.6)
    assert seen[0] == 7.5 and 6.6 in seen
