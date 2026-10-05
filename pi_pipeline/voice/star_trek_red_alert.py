"""star_trek_red_alert -- a siren whose pitch rises as it plays, repeated. Measured from a reference clip (2026-10-04): each burst
lasts ~0.85 s and climbs from roughly 1450 Hz to 2100 Hz, then goes silent until the next burst 1.83 s after the last began.
(A first version, built around a sub-harmonic and a sawtooth-like contour, didn't sound right and was replaced by this plain rising siren.)

G2 plays two bursts by default, at the same level as `star_trek_whistle`. `render()` returns int16 mono PCM; `play()` plays it
without blocking."""
from __future__ import annotations

import logging
import threading

import numpy as np

from .star_trek_whistle import DEFAULT_PEAK

log = logging.getLogger("g2.red_alert")

START_HZ = 1450.0
END_HZ = 2100.0
CYCLE_S = 0.85          # sound length of one burst
PERIOD_S = 1.83         # start-to-start spacing of bursts in the clip
PITCH = 1.0            # multiplier on START_HZ/END_HZ; <1 is lower
HARMONICS = (1.0, 0.2, 0.1)   # a siren is mostly the fundamental with a little edge


def render(rate: int = 48000, peak: float = DEFAULT_PEAK, count: int = 1, pitch: float = PITCH) -> np.ndarray:
    """`count` bursts spaced PERIOD_S apart (start to start). Peak is a fraction of full scale; `pitch` multiplies every frequency."""
    t = np.arange(0, CYCLE_S, 1.0 / rate)
    freq = pitch * START_HZ * (END_HZ / START_HZ) ** (t / CYCLE_S)           # exponential climb = an even rise in musical pitch
    phase = 2 * np.pi * np.cumsum(freq) / rate
    y = sum(w * np.sin((k + 1) * phase) for k, w in enumerate(HARMONICS))
    env = np.minimum(1.0, np.minimum(t / 0.03, (CYCLE_S - t) / 0.06))  # 30 ms attack, 60 ms release
    y = y * env
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
