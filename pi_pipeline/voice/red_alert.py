"""red_alert -- a siren-style alert sound, mimicked from a reference clip (2026-10-04): a ~0.9 s burst of rising sweeps with a
rich, buzzy tone, then silence, repeated. The clip repeats it ~15 times; G2 plays it `count` times (default 2).

Built from the clip's measured contour: the loudest partial's pitch and the loudness every 25 ms, median over 13 cycles, with the
buzzy timbre made by adding harmonics of a fundamental one third of that pitch. Played through the Pi's speaker at the same level as
`star_trek_whistle`. `render()` returns int16 mono PCM; `play()` plays it without blocking."""
from __future__ import annotations

import logging
import threading

import numpy as np

from .star_trek_whistle import DEFAULT_PEAK

log = logging.getLogger("g2.red_alert")

# (seconds, Hz of the loudest partial, relative loudness 0..1), linearly interpolated
CONTOUR = [
    (0.000, 1579, 0.37),
    (0.025, 1686, 0.38),
    (0.050, 1791, 0.45),
    (0.075, 1875, 0.54),
    (0.100, 1457, 0.71),
    (0.125, 1521, 0.57),
    (0.150, 1596, 0.62),
    (0.175, 1673, 0.63),
    (0.200, 1686, 0.59),
    (0.225, 1788, 0.58),
    (0.250, 1859, 0.60),
    (0.275, 1884, 0.83),
    (0.300, 1921, 0.76),
    (0.325, 1947, 0.62),
    (0.350, 2046, 0.62),
    (0.375, 2087, 0.84),
    (0.400, 1423, 0.82),
    (0.425, 1439, 0.92),
    (0.450, 1474, 1.00),
    (0.475, 1505, 0.87),
    (0.500, 1523, 0.94),
    (0.525, 1514, 0.83),
    (0.550, 1580, 0.72),
    (0.575, 1602, 0.78),
    (0.600, 1610, 0.79),
    (0.625, 1612, 0.59),
    (0.650, 1673, 0.66),
    (0.675, 1683, 0.68),
    (0.700, 1717, 0.62),
    (0.725, 1713, 0.48),
    (0.750, 1739, 0.48),
    (0.775, 1750, 0.49),
    (0.800, 1780, 0.41),
    (0.825, 1776, 0.20),
    (0.850, 1751, 0.04),
    (0.875, 1751, 0.04),
]
CYCLE_S = 0.85          # sound length of one burst
PERIOD_S = 1.83         # start-to-start spacing of bursts in the clip
HARMONICS = (0.9, 0.3, 1.0, 0.65, 0.3, 0.15)   # weights of f0, 2*f0, ... where f0 = loudest partial / 3


def render(rate: int = 48000, peak: float = DEFAULT_PEAK, count: int = 1) -> np.ndarray:
    """`count` bursts, spaced like the clip (PERIOD_S start to start). Peak is a fraction of full scale."""
    t_pts, f_pts, a_pts = (np.array(c) for c in zip(*CONTOUR))
    t = np.arange(0, CYCLE_S, 1.0 / rate)
    f0 = np.interp(t, t_pts, f_pts) / 3.0
    amp = np.interp(t, t_pts, a_pts)
    amp = amp * np.minimum(1.0, np.minimum(t, CYCLE_S - t) / 0.01)          # 10 ms fade in/out
    phase = 2 * np.pi * np.cumsum(f0) / rate
    y = sum(w * np.sin((k + 1) * phase) for k, w in enumerate(HARMONICS)) * amp
    y = y / np.abs(y).max() * peak
    burst = (y * 32767).astype(np.int16)
    gap = np.zeros(int((PERIOD_S - CYCLE_S) * rate), dtype=np.int16)
    return np.concatenate([np.concatenate([burst, gap]) for _ in range(count - 1)] + [burst])


def play(peak: float = DEFAULT_PEAK, count: int = 2, rate: int = 48000, wait: bool = False) -> None:
    """Play the alert `count` times on the default output. Never raises: a speaker problem is logged and ignored."""
    def _run() -> None:
        try:
            import sounddevice as sd
            sd.play(render(rate, peak, count), rate)
            if wait:
                sd.wait()
        except Exception:  # noqa: BLE001 -- an alert sound must never take the loop down
            log.debug("red alert sound failed", exc_info=True)
    if wait:
        _run()
    else:
        threading.Thread(target=_run, name="red-alert", daemon=True).start()
