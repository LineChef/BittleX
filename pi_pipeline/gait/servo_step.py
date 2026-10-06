"""Fit a servo's speed from sparse position-feedback samples of repeated step moves.

The firmware's `f` feedback stream runs at only ~5 rows/s, too slow to see one 40-60 deg step (a few hundred ms). So the step is
repeated many times and the first feedback query is sent a different delay after the move command each time (tools/servo_step_test.py):
pooled, the samples trace the move at a finer spacing than any single run. This module fits that pooled trace to a rate-limited ramp:

    position(t) = start + sign * min(rate * max(0, t - lag), |end - start|)

`t` is seconds since the move command was written; `lag` lumps the command's travel through the firmware, the servo's dead time and the
reading's own latency (they can't be separated, and don't need to be: the rate is what the sim's SERVO_RATE_LIMIT_DEG_S models). The
firmware itself eases an `i` move at 2 deg per 8 ms = 250 deg/s, so a fitted rate near 250 means the servo keeps up and a clearly lower
rate is the servo's own limit (backlog H13; the sim assumes 137 deg/s, borrowed from another project).
"""
from __future__ import annotations

import numpy as np

FIRMWARE_EASE_DEG_S = 250.0


def ramp(t, start, end, rate, lag):
    """Modelled position at times `t` (s since the move command)."""
    t = np.asarray(t, dtype=float)
    span = abs(end - start)
    return start + np.sign(end - start) * np.minimum(rate * np.maximum(0.0, t - lag), span)


def fit_rate(samples, start, end, rates=None, lags=None):
    """samples: iterable of (t_s, position_deg). Returns dict(rate_deg_s, lag_s, rms_deg, n).

    Grid search (the model has two parameters and a few dozen samples); rms is the residual after the fit.
    Samples taken after the move should have finished still count: they pin the end value."""
    s = np.asarray(list(samples), dtype=float)
    if s.ndim != 2 or len(s) < 6:
        raise ValueError("need at least 6 (t, position) samples")
    rates = np.arange(20.0, 800.0, 5.0) if rates is None else np.asarray(rates, dtype=float)
    lags = np.arange(0.0, 0.60, 0.01) if lags is None else np.asarray(lags, dtype=float)
    best = None
    for r in rates:
        for g in lags:
            err = ramp(s[:, 0], start, end, r, g) - s[:, 1]
            rms = float(np.sqrt(np.mean(err ** 2)))
            if best is None or rms < best[0]:
                best = (rms, float(r), float(g))
    return dict(rate_deg_s=best[1], lag_s=best[2], rms_deg=best[0], n=len(s))


def pool(trials):
    """trials: iterable of lists of (t_s, position). Flattens, sorted by time."""
    out = [p for tr in trials for p in tr]
    return sorted(out)
