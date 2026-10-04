"""G2's acknowledgement tone: one continuous whistle (about 1.2 s) that glides up from ~1950 Hz to ~2450 Hz, holds with a slight
wobble, and glides back down. Chosen by ear on 2026-10-04 (rebuilt from the measured pitch and loudness contour of a reference clip).

The buzzer can't make this sound (its notes are separate semitone steps, so it beeps), so it is synthesised and played through the
Pi's speaker instead. `render()` returns int16 mono PCM; `play()` plays it without blocking."""
from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger("g2.ack")

# (seconds, Hz, relative loudness 0..1), linearly interpolated
CONTOUR = [
    (0.00, 1951, 0.09), (0.04, 1958, 0.33), (0.08, 1952, 0.56), (0.12, 2028, 0.73), (0.16, 2193, 0.83),
    (0.20, 2259, 0.79), (0.24, 2321, 0.79), (0.28, 2395, 0.78), (0.32, 2440, 0.70), (0.36, 2427, 0.71),
    (0.40, 2445, 0.83), (0.44, 2450, 0.82), (0.48, 2437, 0.79), (0.52, 2455, 0.76), (0.56, 2450, 0.68),
    (0.60, 2449, 0.57), (0.64, 2470, 0.64), (0.68, 2461, 0.72), (0.72, 2466, 0.72), (0.76, 2460, 0.64),
    (0.80, 2468, 0.59), (0.84, 2460, 0.64), (0.88, 2409, 0.79), (0.92, 2263, 0.84), (0.96, 2102, 0.75),
    (1.00, 2056, 0.91), (1.04, 1988, 0.62), (1.08, 1953, 0.36), (1.12, 1950, 0.24), (1.16, 1944, 0.10),
    (1.18, 1947, 0.06),
]

# Peak level as a fraction of full scale. 0.6 was the level chosen first; turned down 25% on 2026-10-04.
DEFAULT_PEAK = 0.45


def render(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    t_pts, f_pts, a_pts = (np.array(c) for c in zip(*CONTOUR))
    t = np.arange(0, t_pts[-1], 1.0 / rate)
    freq = np.interp(t, t_pts, f_pts)
    amp = np.interp(t, t_pts, a_pts)
    phase = 2 * np.pi * np.cumsum(freq) / rate
    y = (np.sin(phase) + 0.08 * np.sin(2 * phase)) * amp
    y = y / np.abs(y).max() * peak
    return (y * 32767).astype(np.int16)


def play(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    """Play the tone on the default output. Never raises: a speaker problem is logged and ignored."""
    def _run() -> None:
        try:
            import sounddevice as sd
            sd.play(render(rate, peak), rate)
            if wait:
                sd.wait()
        except Exception:  # noqa: BLE001 -- an acknowledgement must never take the loop down
            log.debug("acknowledgement tone failed", exc_info=True)
    if wait:
        _run()
    else:
        threading.Thread(target=_run, name="ack-tone", daemon=True).start()
