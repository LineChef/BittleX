"""star_trek_red_alert -- a siren whose pitch climbs as it plays, repeated. Measured from a reference clip (2026-10-04), averaged over
13 bursts: each burst lasts ~0.85 s; its fundamental rises from ~390 Hz to ~875 Hz (about 14 semitones, quickly at first, then
flattening) and carries strong harmonics (the 1st to 3rd about equal, the 4th less, the 5th faint); then silence until the next
burst, 1.83 s after the last began. Earlier versions (a ~1450-2100 Hz single sweep, then lower copies of it) were too high and too
narrow in range; this one is fitted to the clip's measured fundamental, harmonic weights and loudness.

G2 plays two bursts by default, at the same level as `star_trek_whistle`. `render()` returns int16 mono PCM; `play()` plays it
without blocking."""
from __future__ import annotations

import logging
import threading

import numpy as np

from .star_trek_whistle import DEFAULT_PEAK

log = logging.getLogger("g2.red_alert")

# (seconds, fundamental Hz, relative loudness 0..1), linearly interpolated
CONTOUR = [(0.00, 398, 0.35), (0.06, 455, 0.50), (0.12, 509, 0.62), (0.18, 558, 0.63), (0.24, 603, 0.62), (0.30, 645, 0.73), (0.36, 684, 0.72), (0.42, 719, 0.88), (0.48, 750, 0.87), (0.54, 779, 0.73), (0.60, 806, 0.79), (0.66, 829, 0.65), (0.72, 851, 0.50), (0.78, 870, 0.49), (0.83, 884, 0.15)]
CYCLE_S = 0.85          # sound length of one burst
PERIOD_S = 1.83         # start-to-start spacing of bursts in the clip
PITCH = 1.0             # multiplier on the fundamental; <1 is lower
HARMONICS = (1.00, 1.08, 0.93, 0.40, 0.14, 0.08,)   # weights of the fundamental, 2x, 3x ... measured from the clip


def render(rate: int = 48000, peak: float = DEFAULT_PEAK, count: int = 1, pitch: float = PITCH) -> np.ndarray:
    """`count` bursts spaced PERIOD_S apart (start to start). Peak is a fraction of full scale; `pitch` multiplies the pitch."""
    t_pts, f_pts, a_pts = (np.array(c) for c in zip(*CONTOUR))
    t = np.arange(0, CYCLE_S, 1.0 / rate)
    f0 = pitch * np.interp(t, t_pts, f_pts)
    amp = np.interp(t, t_pts, a_pts)
    amp = amp * np.minimum(1.0, np.minimum(t / 0.02, (CYCLE_S - t) / 0.05))        # short fade in/out, no clicks
    phase = 2 * np.pi * np.cumsum(f0) / rate
    y = sum(w * np.sin((k + 1) * phase) for k, w in enumerate(HARMONICS)) * amp
    y = y / np.abs(y).max() * peak
    burst = (y * 32767).astype(np.int16)
    gap = np.zeros(int((PERIOD_S - CYCLE_S) * rate), dtype=np.int16)
    return np.concatenate([np.concatenate([burst, gap]) for _ in range(count - 1)] + [burst])


def play(peak: float = DEFAULT_PEAK, count: int = 2, rate: int = 48000, wait: bool = False, pitch: float = PITCH) -> None:
    """Play the siren `count` times on the default output. Never raises: a speaker problem is logged and ignored."""
    def _run() -> None:
        try:
            import sounddevice as sd
            sd.play(render(rate, peak, count, pitch), rate)
            if wait:
                sd.wait()
        except Exception:  # noqa: BLE001 -- an alert sound must never take the loop down
            log.debug("red alert sound failed", exc_info=True)
    if wait:
        _run()
    else:
        threading.Thread(target=_run, name="red-alert", daemon=True).start()
