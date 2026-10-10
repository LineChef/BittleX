"""wake_chime -- the sound G2 makes right after he hears the wake word, so you know he is listening: two soft bell-like notes rising (E5 then A5, about 0.3 s).
Distinct from `short_tone` (a single 880 Hz blip) and from `api_tone` (the sound of an API call). `render()` returns int16 mono PCM; `play()` plays it without blocking."""
from __future__ import annotations

import logging
import threading

import numpy as np

from .ack_whistle import DEFAULT_PEAK

log = logging.getLogger("g2.wake_chime")

NOTES_HZ = (659.3, 880.0)          # E5 -> A5: a rising "I'm listening"
NOTE_S = 0.14
HARMONICS = (1.0, 0.28, 0.10)      # a soft bell timbre


def render(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    parts = []
    for f in NOTES_HZ:
        t = np.arange(0, NOTE_S, 1.0 / rate)
        y = sum(w * np.sin(2 * np.pi * (k + 1) * f * t) for k, w in enumerate(HARMONICS))
        y = y * np.minimum(1.0, t / 0.008) * np.exp(-t * 11.0)               # 8 ms attack, then a bell-like decay
        parts.append(y)
    y = np.concatenate(parts)
    y = y / np.abs(y).max() * peak
    return (y * 32767).astype(np.int16)


def play(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    """Play the chime on the default output. Never raises: a speaker problem is logged and ignored."""
    def _run() -> None:
        try:
            import sounddevice as sd
            sd.play(render(rate, peak), rate)
            if wait:
                sd.wait()
        except Exception:  # noqa: BLE001
            log.debug("wake chime failed", exc_info=True)
    if wait:
        _run()
    else:
        threading.Thread(target=_run, name="wake-chime", daemon=True).start()
