"""The "G2, punt" command: the phrases, the voice loop's hand-over event, and the unit that runs one attempt (2026-10-26)."""
from pi_pipeline.punt_launch import command, launch
from pi_pipeline.voice.commands import match_local_command as _mlc


def test_the_punt_phrases_start_a_punt_and_a_longer_sentence_does_not():
    for p in ("punt", "punt it", "punt the ball", "go punt", "do a punt", "punt test", "punt please"):
        assert _mlc(p) == "punt", p
    assert _mlc("what is a punt in football and how far can you kick one") != "punt"
    assert _mlc("go ahead and look around") == "explore" and _mlc("emergency stop") == "halt"          # the other commands are untouched


def test_the_voice_loop_says_punting_and_asks_for_the_hand_over():
    from pi_pipeline.tests.test_voice_loop import _loop, _run
    events = []
    lp, w, stt, conv, tts = _loop(["punt"], on_event=lambda **kw: events.append(kw))
    _run(lp, 1)
    assert tts.said[0] == "Punting." and any(e.get("arm_punt") for e in events)


def test_the_unit_stops_voice_first_runs_one_attempt_and_always_rests_then_restarts_voice():
    c = command(python="/py", workdir="/w", user="u")
    s = " ".join(c)
    assert c[:5] == ["sudo", "-n", "systemd-run", "--no-block", "--unit=g2-punt"]
    assert "ExecStartPre=+/bin/systemctl stop g2-voice" in s and "ExecStopPost=+/bin/systemctl --no-block start g2-voice" in s
    assert "check_serial send krest" in s and s.index("check_serial send krest") < s.index("start g2-voice")       # rest first, then the voice service
    assert s.endswith("-m pi_pipeline.behavior.ball_chase --punts 1")                                           # one attempt; every value comes from the settings file


def test_launch_skips_off_a_pi_and_when_an_attempt_is_already_running():
    calls = []
    assert launch(platform="darwin", run=lambda *a, **k: calls.append(a)) is False and calls == []

    class R:
        def __init__(self, rc): self.returncode = rc
    assert launch(platform="linux", run=lambda *a, **k: R(0)) is False                                           # is-active succeeded: already running
    ran = []
    def run(cmd, **k):
        ran.append(cmd)
        return R(3)
    assert launch(platform="linux", run=run) is True and ran[1][:3] == ["sudo", "-n", "systemd-run"]
    def boom(cmd, **k):
        raise OSError("no sudo")
    assert launch(platform="linux", run=boom) is False
