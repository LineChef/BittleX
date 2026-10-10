import numpy as np

from pi_pipeline.voice import ack_whistle
from pi_pipeline.voice.cues import SpeakerCue


def test_whistle_is_one_second_and_a_bit_at_the_requested_level():
    y = ack_whistle.render(48000, peak=0.45)
    assert 1.15 < len(y) / 48000 < 1.22
    assert abs(np.abs(y).max() / 32767 - 0.45) < 0.01


def test_default_level_is_5_percent_of_the_0_45_level():
    assert abs(ack_whistle.DEFAULT_PEAK - 0.45 * 0.05) < 1e-9


def _peak_hz(y, t0, t1, rate=48000):
    seg = y[int(t0 * rate):int(t1 * rate)].astype(float) * np.hanning(int((t1 - t0) * rate))
    sp = np.abs(np.fft.rfft(seg, 1 << 16))
    return np.fft.rfftfreq(1 << 16, 1 / rate)[np.argmax(sp)]


def test_whistle_glides_up_holds_high_and_comes_back_down():
    y = ack_whistle.render(48000)
    start, hold, end = _peak_hz(y, 0.04, 0.10), _peak_hz(y, 0.45, 0.80), _peak_hz(y, 1.08, 1.16)
    assert 1900 < start < 2000 and 2400 < hold < 2500 and 1900 < end < 2000


def test_speaker_cue_plays_only_on_its_stages_and_always_logs():
    played, seen = [], []
    inner = type("Inner", (), {"set": lambda self, s: seen.append(s)})()
    cue = SpeakerCue(inner, stages=("thinking",), player=lambda: played.append(1))
    for stage in ("listening", "thinking", "speaking", "idle"):
        cue.set(stage)
    assert seen == ["listening", "thinking", "speaking", "idle"] and played == [1]
