import numpy as np

from pi_pipeline.voice import star_trek_red_alert as ra
from pi_pipeline.voice import star_trek_whistle


def _peak_hz(y, t0, t1, rate=48000):
    a, b = round(t0 * rate), round(t1 * rate)
    seg = y[a:b].astype(float) * np.hanning(b - a)
    sp = np.abs(np.fft.rfft(seg, 1 << 16))
    return np.fft.rfftfreq(1 << 16, 1 / rate)[np.argmax(sp)]


def test_one_burst_is_under_a_second_at_the_default_level():
    y = ra.render(48000)
    assert 0.8 < len(y) / 48000 < 0.9
    assert abs(np.abs(y).max() / 32767 - star_trek_whistle.DEFAULT_PEAK) < 0.002


def test_pitch_rises_steadily_as_it_plays():
    y = ra.render(48000)
    early, mid, late = _peak_hz(y, 0.05, 0.15), _peak_hz(y, 0.35, 0.45), _peak_hz(y, 0.65, 0.75)
    assert early < mid < late and early < 1700 and late > 1900


def test_two_bursts_are_spaced_like_the_clip_with_silence_between():
    y = ra.render(48000, count=2)
    assert abs(len(y) / 48000 - (ra.PERIOD_S + ra.CYCLE_S)) < 0.01
    assert np.abs(y[int(0.9 * 48000):int(1.75 * 48000)]).max() == 0
