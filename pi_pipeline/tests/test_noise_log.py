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
