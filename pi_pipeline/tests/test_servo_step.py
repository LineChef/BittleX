"""servo_step.fit_rate recovers a known ramp from sparse, noisy, staggered samples."""
import numpy as np
import pytest

from pi_pipeline.gait import servo_step as ss


def _samples(rate, lag, start, end, noise=0.8, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for d in np.arange(0, 0.2, 0.01):                  # first-query delays, as the tool uses
        for k in range(6):                             # ~5 Hz rows after the first
            t = d + 0.11 + k * 0.2 + rng.normal(0, 0.01)
            out.append((t, float(ss.ramp(t, start, end, rate, lag)) + rng.normal(0, noise)))
    return out


@pytest.mark.parametrize("rate", [90.0, 137.0, 250.0])
def test_fit_recovers_rate_up_and_down(rate):
    for start, end in ((30, 70), (70, 30)):
        r = ss.fit_rate(_samples(rate, 0.05, start, end), start, end)
        assert r["rate_deg_s"] == pytest.approx(rate, rel=0.2)
        assert r["lag_s"] == pytest.approx(0.05, abs=0.06)


def test_too_few_samples_is_an_error():
    with pytest.raises(ValueError):
        ss.fit_rate([(0.1, 30), (0.2, 31)], 30, 70)


def test_pool_sorts_by_time():
    assert ss.pool([[(0.3, 1), (0.1, 2)], [(0.2, 3)]]) == [(0.1, 2), (0.2, 3), (0.3, 1)]
