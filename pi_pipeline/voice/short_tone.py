"""short_tone -- G2's acknowledgement signal: one short, soft tone (~0.12 s, 880 Hz) meaning "got it". Chosen 2026-10-04 to replace the
longer `ack_whistle` as the acknowledgement (the whistle became the battery alert instead). `render()` returns int16 mono PCM;
`play()` plays it without blocking, at the same quiet level as the other sounds."""
from __future__ import annotations

import logging
import threading

import numpy as np

from .ack_whistle import DEFAULT_PEAK

log = logging.getLogger("g2.short_tone")

FREQ_HZ = 880.0
DURATION_S = 0.12
HARMONICS = (1.0, 0.15)        # a little edge so it is clear at a low level


def render(rate: int = 48000, peak: float = DEFAULT_PEAK, freq: float = FREQ_HZ) -> np.ndarray:
    t = np.arange(0, DURATION_S, 1.0 / rate)
    y = sum(w * np.sin(2 * np.pi * (k + 1) * freq * t) for k, w in enumerate(HARMONICS))
    y = y * np.minimum(1.0, np.minimum(t / 0.01, (DURATION_S - t) / 0.04))     # 10 ms attack, 40 ms release: no clicks
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
            log.debug("short tone failed", exc_info=True)
    if wait:
        _run()
    else:
        threading.Thread(target=_run, name="short-tone", daemon=True).start()
