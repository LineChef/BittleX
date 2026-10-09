import types

from pi_pipeline.voice.actuator import SerialActuator
from pi_pipeline.voice.cues import BuzzerCue


class _Link:
    def __init__(self):
        self.sent = []

    def send(self, cmd, read_reply=True):
        self.sent.append(cmd)
        return ""

    def close(self):
        pass


def test_by_default_only_the_claude_stage_beeps():
    sent = []
    cue = BuzzerCue(types.SimpleNamespace(send_token=sent.append))
    for stage in ("idle", "listening", "heard", "speaking", "thinking"):
        cue.set(stage)
    assert sent == []                                   # no sound for a local command or while thinking (the API has its own tone)
    cue.set("awake")
    assert sent == ["b10 4"]                            # the wake word: one beep
    cue.set("captured")
    cue.set("closed")
    assert sent == ["b10 4", "b4 3", "b8 4 4 3"]        # then the boop (your words are captured) and the falling pair (the follow-up window closed)


def test_stages_are_configurable():
    sent = []
    cue = BuzzerCue(types.SimpleNamespace(send_token=sent.append), stages=("listening", "thinking", "heard"))
    for stage in ("idle", "listening", "thinking", "heard", "speaking"):
        cue.set(stage)
    assert sent == ["b8 3 8 3", "b4 4 9 2", "b4 3 8 3"]      # listening, thinking, heard


def test_a_failing_buzzer_never_breaks_the_loop():
    def boom(_t):
        raise OSError("serial gone")
    BuzzerCue(types.SimpleNamespace(send_token=boom)).set("listening")   # must not raise


def test_actuator_without_send_token_is_fine():
    BuzzerCue(types.SimpleNamespace()).set("listening")


def test_serial_actuator_skips_beeps_while_a_gait_runs():
    lk = _Link()
    act = SerialActuator("ignored", 0, link=lk)
    act.send_token("b26 3 30 3")
    act.perform("walk_forward")
    act.send_token("b26 3 30 3")           # suppressed during the gait
    act.stop()
    act.send_token("b19 5 26 8")           # allowed again after the stop
    assert lk.sent == ["b26 3 30 3", "kwkF", "d", "b19 5 26 8"]


def test_cue_melodies_sit_in_the_audible_low_range():
    sent = []
    cue = BuzzerCue(types.SimpleNamespace(send_token=sent.append), stages=("listening", "heard"))
    cue.set("listening")
    cue.set("heard")
    assert sent == ["b8 3 8 3", "b4 3 8 3"]


def test_the_claude_cue_is_the_low_rising_pair():
    sent = []
    BuzzerCue(types.SimpleNamespace(send_token=sent.append), stages=("thinking",)).set("thinking")
    assert sent == ["b4 4 9 2"]


def test_long_melodies_are_split_into_short_tokens():
    from pi_pipeline.voice.cues import chunk_notes
    long = [(10 + i % 5, 8) for i in range(30)]
    chunks = chunk_notes(long)
    assert len(chunks) > 1 and sum(len(c) for c in chunks) == 30
    assert all(len("b" + "".join(f" {n} {d}" for n, d in c)) <= 62 for c in chunks)


def test_shift_and_length_still_adjust_the_melody():
    sent = []
    BuzzerCue(types.SimpleNamespace(send_token=sent.append), shift=3, length=2.0, stages=("heard",)).set("heard")
    assert sent == ["b7 2 11 2"]                   # +3 semitones, 1/2 s per note (a smaller divisor is longer)
    sent.clear()
    BuzzerCue(types.SimpleNamespace(send_token=sent.append), shift=-10, stages=("heard",)).set("heard")
    assert sent == ["b1 3 1 3"]                    # never below tone 1


def test_prime_sets_the_volume_once_and_zero_leaves_it_alone():
    sent = []
    BuzzerCue(types.SimpleNamespace(send_token=sent.append), volume=10).prime()
    BuzzerCue(types.SimpleNamespace(send_token=sent.append), volume=0).prime()
    assert sent == ["b10"]


def test_buzzer_volume_token_never_builds_the_mute_toggle():
    import pytest
    from pi_pipeline.link import opencat
    assert opencat.buzzer_volume(5) == "b5"
    for bad in (0, 11, -1):
        with pytest.raises(ValueError):
            opencat.buzzer_volume(bad)
