import pytest

from pi_pipeline.voice.commands import match_local_command


@pytest.mark.parametrize("text", [
    "forget that",
    "Forget that.",
    "forget that please",
    "hey G2, forget that",
    "okay G2 forget that",
    "scratch that",
    "don't remember that",
    "forget what I just said",
    "forget this conversation",
    "forget that last part",          # trailing cruft after the phrase
])
def test_forget_variants(text):
    assert match_local_command(text) == "forget"


@pytest.mark.parametrize("text", [
    "go to sleep",
    "Go to sleep, G2.",
    "hey G2 go to sleep now",
])
def test_sleep_variants(text):
    assert match_local_command(text) == "sleep"


@pytest.mark.parametrize("text", [
    "",
    "   ",
    "what's the weather",
    "I always forget things",
    "can you forget how to walk",
    "let's go for a walk",
    "tell me a story about going to sleep",
    "do you ever sleep",
    "I need to forget my ex",
])
def test_no_false_positives(text):
    assert match_local_command(text) is None


# ------------------------------------------------------------------ rebuff (B6)
import pytest
from pi_pipeline.voice.commands import looks_like_rebuff


@pytest.mark.parametrize("text", [
    "leave me alone", "G2, stop it", "be quiet please", "shut up",
    "okay that's enough", "knock it off", "stop talking", "you're annoying",
])
def test_rebuff_phrases_match(text):
    assert looks_like_rebuff(text)


@pytest.mark.parametrize("text", [
    "what's the weather", "tell me a story about a quiet forest",
    "can you stop the timer at noon", "I left my keys somewhere",
])
def test_ordinary_sentences_are_not_rebuffs(text):
    assert not looks_like_rebuff(text)


# ------------------------------------------------- explore / shutdown commands
from pi_pipeline.voice.commands import match_local_command as _mlc


def test_explore_and_unexplore_phrases():
    for p in ("go ahead and look around", "exploration mode", "look around",
              "go explore", "wander around"):
        assert _mlc(p) == "explore", p
    for p in ("that's enough", "stop exploring", "come back", "stop looking around"):
        assert _mlc(p) == "unexplore", p


def test_shutdown_is_its_own_command_not_a_halt():
    for p in ("shut down", "shutdown", "power down", "go dormant", "G2 shut down"):
        assert _mlc(p) == "shutdown", p
    # and the emergency phrases still halt
    assert _mlc("emergency stop") == "halt"
    assert _mlc("freeze") == "halt"


def test_come_here_vs_come_back():
    assert _mlc("come here") == "come"
    assert _mlc("come to me") == "come"
    assert _mlc("come over here") == "come"
    assert _mlc("come back") == "unexplore"          # ending the roam, not approach
    assert _mlc("that's enough") == "unexplore"


# ------------------------------------------------------ chirps / narration
def test_chirps_on_and_off_phrases():
    for p in ("turn off your chirps", "disable chirps", "chirps off",
              "stop chirping", "hey G2 turn off chirps"):
        assert _mlc(p) == "chirps_off", p
    for p in ("turn on your chirps", "enable chirps", "chirps on", "start chirping"):
        assert _mlc(p) == "chirps_on", p


def test_narration_level_phrases():
    from pi_pipeline.voice.commands import parse_narration_command as _pnc
    for p in ("narration level 1", "set verbosity to level 5", "narration level 3"):
        assert _mlc(p) == "narration_level", p
    assert _pnc("narration level 1") == 1
    assert _pnc("verbosity level 5") == 5
    assert _pnc("set narration to level 9") is None      # out of 1-5 range
    assert _pnc("level 3") is None                        # no narration/verbosity name at all


def test_chirps_and_narration_dont_collide_with_rebuff():
    # "be quiet" / "stop talking" nudge mood (looks_like_rebuff), they are
    # NOT the chirps/narration toggle -- different mechanism, different words.
    assert _mlc("be quiet") is None
    assert _mlc("stop talking") is None
    assert looks_like_rebuff("be quiet")
    assert not looks_like_rebuff("turn off your chirps")
    assert not looks_like_rebuff("narrate less")


def test_voice_language_reset_phrases():
    from pi_pipeline.voice.commands import match_local_command
    for t in ("switch to english", "gee two switch to english", "please switch to english", "fix your language", "reset your language", "set your language to english"):
        assert match_local_command(t) == "voice_language", t
    assert match_local_command("I like english muffins") is None
    assert match_local_command("the floor is tile") == "floor"


def test_grunt_and_oof_render_short_audible_pcm():
    import numpy as np
    from pi_pipeline.voice import prompt_tones as pt
    for fn, lo, hi in ((pt.render_grunt, 0.3, 0.5), (pt.render_oof, 0.4, 0.6)):
        y = fn()
        assert y.dtype == np.int16 and lo < y.size / 48000 < hi and np.abs(y).max() > 300


def test_refuse_horn_renders_the_measured_five_pieces_and_ends_on_a_falling_long_note():
    import numpy as np
    from pi_pipeline.voice import prompt_tones as pt
    pcm = pt.render_refuse(48000, pt.DEFAULT_PEAK)
    assert 3.6 < len(pcm) / 48000 < 3.9 and 300 < np.abs(pcm).max() < 1500
    assert len(pt.HORN) == 5 and pt.HORN[-1][1] - pt.HORN[-1][0] > 2.0
    assert pt.HORN_LAST_BREAKS[0][1] > pt.HORN_LAST_BREAKS[-1][1]      # the long note sags in pitch


def test_complete_sting_is_a_ta_da_chord_stab_then_the_held_chord():
    import numpy as np
    from pi_pipeline.voice import prompt_tones as pt
    pcm = pt.render_complete(48000, pt.DEFAULT_PEAK)
    r = 48000
    assert 1.2 < len(pcm) / r < 1.5 and abs(np.abs(pcm).max() / (pt.DEFAULT_PEAK * 32767) - 1.5) < 0.15      # 50% louder than a normal-level sound
    seg = pcm[int(0.6 * r):int(1.0 * r)].astype(float) * np.hanning(int(0.4 * r))
    sp = np.abs(np.fft.rfft(seg, 1 << 16)); fr = np.fft.rfftfreq(1 << 16, 1 / r)
    for hz in (523.3, 659.3, 784.0):                       # the held chord's notes stand clear of their neighbours
        near = (np.abs(fr - hz) < 8)
        away = (np.abs(fr - hz * 1.12) < 8)
        assert sp[near].max() > 5 * sp[away].max()


def test_horn_switches_are_per_situation(monkeypatch):
    from pi_pipeline.voice import prompt_tones as pt
    played = []
    monkeypatch.setattr(pt, "play_refuse", lambda wait=False: played.append(wait))
    pt.play_horn_if_enabled("G2_FALL_HORN")
    monkeypatch.setenv("G2_FALL_HORN", "0")
    pt.play_horn_if_enabled("G2_FALL_HORN")
    pt.play_horn_if_enabled("G2_REFUSE_SOUND", wait=True)
    assert played == [False, True]                       # the fall horn off leaves the refusal horn on


def test_the_robots_name_is_spelled_out_for_the_voice_but_other_words_are_left_alone():
    from pi_pipeline.voice.tts import pronounce
    assert pronounce("G2 online.") == "gee two online."
    assert pronounce("This is G2's floor, not a G20 summit or BG2.") == "This is gee two's floor, not a G20 summit or BG2."
