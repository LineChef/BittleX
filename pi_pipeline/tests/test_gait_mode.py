"""The shared gait switch: spoken commands, the shared state file, the blend, policies that do not support a gait, and reaching it from the voice loop's command table."""
import json

from pi_pipeline.gait import gait_mode as gm
from pi_pipeline.voice.commands import match_local_command


def test_the_spoken_phrases_pick_the_right_gait_and_off_phrases_win():
    for t in ("hi step", "Hi step!", "high step", "G2, hi step", "hi step mode", "step mode"):
        assert gm.parse_gait_command(t) == "hi_step", t
    for t in ("walk normally", "Walk normally.", "normal walk", "hi step off", "high step off", "step mode off"):
        assert gm.parse_gait_command(t) == "normal", t
    for t in ("walk forward", "walk for ten seconds", "what is a high step", "I want you to take a long walk normally around the house tonight", "hello"):
        assert gm.parse_gait_command(t) is None, t


def test_the_command_table_returns_gait_before_walk():
    assert match_local_command("hi step") == "gait" and match_local_command("walk normally") == "gait"
    assert match_local_command("walk for ten seconds") == "walk" and match_local_command("walk forward") == "walk"


def test_state_is_shared_through_the_file_and_the_blend_runs_over_a_cycle(tmp_path):
    f = str(tmp_path / "mode.json")
    assert gm.current(f) == "normal" and gm.blend(f)[2] == 1.0
    gm.set_mode("hi_step", f, now=100.0)
    assert gm.current(f) == "hi_step"
    frm, to, a = gm.blend(f, now=100.0 + gm.BLEND_S / 2)
    assert (frm, to) == ("normal", "hi_step") and 0.45 < a < 0.55
    assert gm.blend(f, now=100.0 + 5 * gm.BLEND_S)[2] == 1.0
    gm.set_mode("normal", f, now=200.0)
    assert gm.blend(f, now=200.1)[:2] == ("hi_step", "normal")
    (tmp_path / "mode.json").write_text("not json")
    assert gm.current(f) == "normal"                                     # a damaged file means the normal gait, never a crash


def test_a_policy_without_the_mode_refuses_and_changes_nothing(tmp_path):
    f = str(tmp_path / "mode.json")
    onnx = tmp_path / "p.onnx"
    (tmp_path / "p.onnx.json").write_text(json.dumps({"residual_scale_deg": 30.0}))
    gait, said = gm.request("hi step", str(onnx), f)
    assert gait is None and "doesn't have hi step" in said and gm.current(f) == "normal"
    assert gm.request("walk normally", str(onnx), f)[0] == "normal"      # the normal gait is always supported
    (tmp_path / "p.onnx.json").write_text(json.dumps({"modes": ["normal", "hi_step"]}))
    gait, said = gm.request("high step", str(onnx), f)
    assert gait == "hi_step" and said == "Hi step on." and gm.current(f) == "hi_step"
    assert gm.request("walk normally", str(onnx), f) == ("normal", "Walking normally.")


def test_the_double_beep_is_two_short_notes_and_speaker_sounds_are_off_in_tests(monkeypatch):
    from pi_pipeline.voice import prompt_tones as pt
    from pi_pipeline.voice.cues import LOW_CUES, SpeakerCue
    pcm = pt.render_double()
    assert 0.2 < pcm.size / 48000 < 0.4
    assert LOW_CUES["gait_switch"] == [(10, 8), (10, 8)]
    played = []
    SpeakerCue(player=lambda: played.append(1), stages=("gait_switch",)).set("gait_switch")
    assert played == [1]
    monkeypatch.setenv("G2_SPEAKER_SOUNDS", "0")
    assert pt.speaker_enabled() is False                      # conftest sets this for every test: no horn from the Mac
    monkeypatch.setenv("G2_SPEAKER_SOUNDS", "1")
    assert pt.speaker_enabled() is True
