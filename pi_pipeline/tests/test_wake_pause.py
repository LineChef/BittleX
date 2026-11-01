"""voice/wake_pause.py and its parts: "G2, mic off" turns the wake word off for a while (user, 2026-11-01)."""
import json

import pytest

from pi_pipeline.voice import wake_pause as wp
from pi_pipeline.voice import wake_word as ww
from pi_pipeline.voice.commands import match_local_command, parse_mic_minutes


@pytest.fixture(autouse=True)
def _pause_file(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_WAKE_PAUSE_FILE", str(tmp_path / "wake_paused.json"))


def test_pause_resume_and_status():
    assert not wp.is_paused() and wp.status() == {"paused": False, "minutes_left": 0.0}
    assert wp.pause(None, now=1000.0) == 10.0                          # 10 minutes by default
    assert wp.is_paused(now=1000.0 + 599) and not wp.is_paused(now=1000.0 + 601)
    assert wp.pause(500) == 120.0                                       # capped at two hours
    assert wp.resume() is True and not wp.is_paused() and wp.resume() is False


def test_the_cli_turns_it_off_and_on(capsys):
    assert wp.main(["off", "15", "--json"]) == 0
    s = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert s["paused"] and 14.9 < s["minutes_left"] <= 15.0
    assert wp.main(["on"]) == 0 and "back on" in capsys.readouterr().out and not wp.is_paused()


def test_the_voice_commands_and_lengths():
    assert match_local_command("gee two mic off") == "mic_off" and parse_mic_minutes("mic off") is None
    assert parse_mic_minutes("mike off for twenty minutes") == 20 and parse_mic_minutes("mic off for 45 minutes") == 45
    assert parse_mic_minutes("mic off for half an hour") == 30 and parse_mic_minutes("mic off for an hour") == 60
    assert match_local_command("mic on") == "mic_on" and match_local_command("is your mic on") == "mic_status"
    assert match_local_command("emergency stop") == "halt"


def test_only_the_stop_words_count_while_paused():
    assert ww.stop_hit("emergency stop") == "emergency stop" and ww.stop_hit("freeze") == "freeze"
    assert ww.stop_hit("gee two") is None and ww.stop_hit("hey buddy") is None


def test_the_voice_loop_turns_it_off_and_says_when_it_is_back(monkeypatch):
    from pi_pipeline.tests.test_voice_loop import _loop, _run
    lp, w, stt, conv, tts = _loop(["mic off for 20 minutes", "this is never heard"])
    _run(lp, 1)
    assert wp.is_paused() and 19.9 < wp.status()["minutes_left"] <= 20.0 and tts.said[-1] == "Mic off for 20 minutes."
    assert not lp._in_session and conv.sent == []                      # no follow-up window after it
    w.take_pending = lambda: ww.MIC_BACK_ON                             # the wake listener says the pause is over
    _run(lp, 1)
    assert tts.said[-1] == "Mic back on." and conv.sent == []
    w.take_pending = lambda: "emergency stop"                           # a stop word said during a pause: handled without listening for more
    _run(lp, 1)
    assert conv.sent == [] and stt._script == ["this is never heard"]
