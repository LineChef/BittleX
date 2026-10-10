import numpy as np

from pi_pipeline.voice import red_alert_siren as ra
from pi_pipeline.voice import ack_whistle


def _peak_hz(y, t0, t1, rate=48000):
    a, b = round(t0 * rate), round(t1 * rate)
    seg = y[a:b].astype(float) * np.hanning(b - a)
    sp = np.abs(np.fft.rfft(seg, 1 << 16))
    return np.fft.rfftfreq(1 << 16, 1 / rate)[np.argmax(sp)]


def test_one_burst_is_under_a_second_at_the_default_level():
    y = ra.render(48000)
    assert 0.8 < len(y) / 48000 < 0.9
    assert abs(np.abs(y).max() / 32767 - ack_whistle.DEFAULT_PEAK) < 0.002


def test_pitch_climbs_from_about_390_to_about_875_hz_as_it_plays():
    y = ra.render(48000)
    def fundamental(t0, t1):                       # the lowest strong partial, below the 2nd harmonic
        a, b = round(t0 * 48000), round(t1 * 48000)
        seg = y[a:b].astype(float) * np.hanning(b - a)
        sp = np.abs(np.fft.rfft(seg, 1 << 16)); fr = np.fft.rfftfreq(1 << 16, 1 / 48000)
        m = (fr > 250) & (fr < 1100)
        return fr[m][np.argmax(sp[m])]
    early, mid, late = fundamental(0.05, 0.15), fundamental(0.35, 0.45), fundamental(0.68, 0.78)
    assert early < mid < late and 350 < early < 520 and 780 < late < 950


def test_two_bursts_are_spaced_like_the_clip_with_silence_between():
    y = ra.render(48000, count=2)
    assert abs(len(y) / 48000 - (ra.PERIOD_S + ra.CYCLE_S)) < 0.01
    assert np.abs(y[int(0.9 * 48000):int(1.75 * 48000)]).max() == 0
