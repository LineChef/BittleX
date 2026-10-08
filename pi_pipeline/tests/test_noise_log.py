"""link/noise_log.py and the chirp logging: every noisy command is logged and written to a JSON line file; quiet commands are not."""
import json
import logging

from pi_pipeline.link import noise_log
from pi_pipeline.behavior.bindings import DriverBindings
from pi_pipeline.behavior.chirps import ChirpMood
from pi_pipeline.behavior.driver import Effect, EffectKind


def test_noisy_commands_are_classified():
    assert noise_log.classify("b24 6 27 6 31 8") == "beep"
    assert noise_log.classify("b-1 4") == "beep"
    assert noise_log.classify("XAc") == "voice-module"
    for quiet in ("kwkF", "d", "gb", "P", "m0 45", "i 0 20", "gP", "", "balance"):
        assert noise_log.classify(quiet) is None, quiet


def test_record_logs_noises_and_appends_a_json_line(tmp_path, monkeypatch, caplog):
    f = tmp_path / "noise.jsonl"
    monkeypatch.setenv("G2_NOISE_LOG", str(f))
    with caplog.at_level(logging.INFO, logger="g2.noise"):
        noise_log.record("b20 6 24 6", "behavior.test")
        noise_log.record("kwkF", "behavior.test")                  # quiet: nothing
    rows = [json.loads(x) for x in f.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["kind"] == "beep" and rows[0]["source"] == "behavior.test" and rows[0]["sent"] is True
    assert any("BiBoard noise: beep" in r.message for r in caplog.records)
    monkeypatch.setenv("G2_NOISE_LOG", "off")
    noise_log.record("b20 6", "x")                                  # off: still logged, no file write
    assert len(f.read_text().splitlines()) == 1


def test_a_chirp_effect_is_logged_with_its_tone_when_it_reaches_the_actuator(caplog):
    sent = []
    b = DriverBindings(actuator=type("A", (), {"perform": staticmethod(lambda c: sent.append(c))})())
    with caplog.at_level(logging.INFO, logger="g2.chirp"):
        b.dispatch([Effect(EffectKind.CHIRP, ChirpMood.HAPPY, "test")])
    assert sent and sent[0].startswith("b") and any("chirp happy sent to the BiBoard" in r.message for r in caplog.records)


def test_every_chirp_tone_is_in_the_buzzers_range_and_in_the_lower_register():
    from pi_pipeline.behavior.chirps import CHIRP
    notes = [n for seq in CHIRP.values() for n, _ in seq]
    assert min(notes) >= 1 and max(notes) <= 22          # 1-35 is the range the buzzer plays; the lower register keeps every note under 23 (the first cut went up to 30)


def test_quiet_commands_are_logged_only_when_asked_and_never_the_joint_stream(tmp_path, monkeypatch):
    f = tmp_path / "noise.jsonl"
    monkeypatch.setenv("G2_NOISE_LOG", str(f))
    monkeypatch.delenv("G2_NOISE_LOG_ALL", raising=False)
    noise_log.record("P", "a")
    assert not f.exists()
    monkeypatch.setenv("G2_NOISE_LOG_ALL", "1")
    for c in ("P", "gb", "kwkF", "i 10 20 30", "m0 45"):
        noise_log.record(c, "a")
    rows = [json.loads(x) for x in f.read_text().splitlines()]
    assert [r["command"] for r in rows] == ["P", "gb", "kwkF"] and all(r["kind"] == "quiet" for r in rows)


def test_the_two_idle_commands_that_make_the_board_tick_are_sent_rarely(monkeypatch):
    from pi_pipeline.config import Settings
    monkeypatch.delenv("G2_BATTERY_POLL_S", raising=False)
    monkeypatch.delenv("G2_STAND_REASSERT_S", raising=False)
    s = Settings()
    poll, reassert = s.battery_poll_s, s.stand_reassert_s          # plain numbers only: an assertion on the Settings object would print the API key in a failure
    del s
    assert poll == 1800.0 and reassert == 600.0                    # were 60 s each: the `P` battery read and the `gb` re-assert each made the BiBoard tick (measured 2026-10-08); the battery is read at start, wake and before a walk, plus a 30 min idle backstop
    monkeypatch.setenv("G2_STAND_REASSERT_S", "120")
    again = Settings().stand_reassert_s
    assert again == 120.0


def test_the_battery_watcher_reads_on_demand_only_when_the_timer_is_off():
    import time
    from pi_pipeline.power.battery import BatteryWatcher
    reads = []
    t = [100.0]
    w = BatteryWatcher(lambda: reads.append(1) or 8.0, lambda lvl, v: None, poll_s=0.0, clock=lambda: t[0])
    w._min_gap_s = 20.0
    w.start()
    time.sleep(0.4)
    assert len(reads) == 1                                  # one read at start, then nothing on a timer
    time.sleep(1.5)
    assert len(reads) == 1
    w.check_now()
    time.sleep(1.3)
    assert len(reads) == 1                                  # asked again 0 s later: inside the minimum gap, skipped
    t[0] += 30.0
    w.check_now()
    time.sleep(1.5)
    assert len(reads) == 2                                  # past the gap: read
    t[0] += 30.0
    w.read_before()
    assert len(reads) == 3                                  # before a gait: read on the caller's thread
    w.read_before()
    assert len(reads) == 3                                  # twice in a row: once
    w.stop()


def test_the_battery_watcher_idle_backstop_timer_fires_after_its_interval():
    import time
    from pi_pipeline.power.battery import BatteryWatcher
    reads, t = [], [100.0]
    w = BatteryWatcher(lambda: reads.append(1) or 8.0, lambda lvl, v: None, poll_s=1800.0, clock=lambda: t[0])
    w.start()
    time.sleep(0.4)
    assert len(reads) == 1
    t[0] += 1000.0
    time.sleep(1.4)
    assert len(reads) == 1                                  # 1000 s in: not due yet
    t[0] += 900.0
    time.sleep(1.4)
    assert len(reads) == 2                                  # past 1800 s: the backstop read
    w.stop()
