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


def test_stages_map_to_buzzer_tokens_and_idle_is_silent():
    sent = []
    cue = BuzzerCue(types.SimpleNamespace(send_token=sent.append))
    for stage in ("idle", "listening", "thinking", "heard", "speaking"):
        cue.set(stage)
    assert len(sent) == 3 and all(t.startswith("b") for t in sent)   # listening, thinking, heard


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
    cue = BuzzerCue(types.SimpleNamespace(send_token=sent.append))
    for stage in ("listening", "thinking", "heard"):
        cue.set(stage)
    assert sent == ["b8 3 8 3", "b4 4 9 2", "b4 3 8 3"]


def test_shift_and_length_still_adjust_the_melody():
    sent = []
    BuzzerCue(types.SimpleNamespace(send_token=sent.append), shift=3, length=2.0).set("heard")
    assert sent == ["b7 2 11 2"]                   # +3 semitones, 1/2 s per note (a smaller divisor is longer)
    sent.clear()
    BuzzerCue(types.SimpleNamespace(send_token=sent.append), shift=-10).set("heard")
    assert sent == ["b1 3 1 3"]                    # never below tone 1
