import numpy as np

from pi_pipeline.voice import red_alert, star_trek_whistle


def test_one_burst_is_under_a_second_and_at_the_default_level():
    y = red_alert.render(48000, count=1)
    assert 0.8 < len(y) / 48000 < 0.9
    assert abs(np.abs(y).max() / 32767 - star_trek_whistle.DEFAULT_PEAK) < 0.002


def test_two_bursts_are_spaced_like_the_clip_with_silence_between():
    y = red_alert.render(48000, count=2)
    assert abs(len(y) / 48000 - (red_alert.PERIOD_S + red_alert.CYCLE_S)) < 0.01
    gap = y[int(0.9 * 48000):int(1.7 * 48000)]
    assert np.abs(gap).max() == 0


def test_the_burst_sweeps_upward_in_its_last_section():
    y = red_alert.render(48000).astype(float)
    def peak_hz(t0, t1):
        a, b = round(t0 * 48000), round(t1 * 48000)
        seg = y[a:b] * np.hanning(b - a)
        sp = np.abs(np.fft.rfft(seg, 1 << 16)); fr = np.fft.rfftfreq(1 << 16, 1 / 48000)
        m = (fr > 1200) & (fr < 2400)          # the loudest partial, as in the contour
        return fr[m][np.argmax(sp[m])]
    assert peak_hz(0.45, 0.50) < peak_hz(0.70, 0.75)
