"""The lob (behavior/lob.py): the one definition of the stand, pick-up, lob sequence, and the three ways to ask for it (shell command, voice phrase, the unit the voice command starts)."""
from pi_pipeline.behavior import lob, scripted_skill
from pi_pipeline.lob_launch import command, launch
from pi_pipeline.voice.commands import match_local_command as _mlc


def test_the_lob_is_lob_soft_after_the_pick_up_with_the_tested_pause_and_the_gyro_off():
    assert lob.args() == ["lob_soft", "--amount", "1.0", "--pick", "--pick-gap", "0.5", "--gyro-off"]
    assert lob.args(["--dry-run"])[-1] == "--dry-run"


def test_the_lob_runs_through_the_scripted_skill_player_and_its_dry_run_touches_nothing(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(scripted_skill, "main", lambda argv=None: seen.append(argv))
    lob.main(["--dry-run"])
    assert seen == [lob.args(["--dry-run"])]
    monkeypatch.undo()
    scripted_skill.main(lob.args(["--dry-run"]))                                                     # the real player, dry: frames printed, nothing sent
    out = capsys.readouterr().out
    assert "bow" in out and "lunge" in out and "settle" in out


def test_the_lob_phrases_start_a_lob_and_a_longer_sentence_does_not():
    for p in ("lob", "lob it", "do a lob", "do the lob", "lob please"):
        assert _mlc(p) == "lob", p
    assert _mlc("that was a nice lob over the net yesterday afternoon") != "lob"
    assert _mlc("punt") == "punt" and _mlc("emergency stop") == "halt"                              # the other commands are untouched


def test_the_voice_loop_says_lobbing_and_asks_for_the_hand_over():
    from pi_pipeline.tests.test_voice_loop import _loop, _run
    events = []
    lp, w, stt, conv, tts = _loop(["lob"], on_event=lambda **kw: events.append(kw))
    _run(lp, 1)
    assert tts.said[0] == "Lobbing." and any(e.get("arm_lob") for e in events)


def test_the_unit_stops_voice_first_runs_the_lob_and_always_rests_then_restarts_voice():
    c = command(python="/py", workdir="/w", user="u")
    s = " ".join(c)
    assert c[:5] == ["sudo", "-n", "systemd-run", "--no-block", "--unit=g2-lob"]
    assert "ExecStartPre=+/bin/systemctl stop g2-voice" in s and "ExecStopPost=+/bin/systemctl --no-block start g2-voice" in s
    assert s.index("check_serial send krest") < s.index("start g2-voice")                            # rest first, then the voice service
    assert s.endswith("-m pi_pipeline.behavior.lob")


def test_launch_skips_off_a_pi_and_when_a_lob_is_already_running():
    calls = []
    assert launch(platform="darwin", run=lambda *a, **k: calls.append(a)) is False and calls == []

    class R:
        def __init__(self, rc):
            self.returncode = rc
    assert launch(platform="linux", run=lambda *a, **k: R(0)) is False                               # is-active succeeded: already running
