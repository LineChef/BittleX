"""api_tone -- the sound G2 makes every time he calls the Claude API: three quick, sharp ticks at 1320 Hz (about 0.25 s), unlike anything else he plays (the
wake chime is two soft rising notes, the acknowledgement a single 880 Hz blip). Whenever you hear it, a billed call is being made. It waits for his own speech to
finish first (`tts.SPEAKING`), because the speaker plays one sound at a time and a new sound would cut the speech off. `render()` returns int16 mono PCM."""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from .star_trek_whistle import DEFAULT_PEAK

log = logging.getLogger("g2.api_tone")

FREQ_HZ = 1320.0
PULSE_S, GAP_S, PULSES = 0.045, 0.04, 3
HARMONICS = (1.0, 0.45, 0.30)       # a hard edge so it cannot be mistaken for the soft chime
WAIT_FOR_SPEECH_S = 6.0


def render(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    pulse_t = np.arange(0, PULSE_S, 1.0 / rate)
    pulse = sum(w * np.sin(2 * np.pi * (k + 1) * FREQ_HZ * pulse_t) for k, w in enumerate(HARMONICS))
    pulse = pulse * np.minimum(1.0, np.minimum(pulse_t / 0.004, (PULSE_S - pulse_t) / 0.012))
    gap = np.zeros(int(GAP_S * rate))
    y = np.concatenate([np.concatenate([pulse, gap]) for _ in range(PULSES)])[: -len(gap)]
    y = y / np.abs(y).max() * peak
    return (y * 32767).astype(np.int16)


def play(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    """Play the tone without blocking the caller, after any speech in progress has finished. Never raises."""
    def _run() -> None:
        try:
            from . import tts
            deadline = time.monotonic() + WAIT_FOR_SPEECH_S
            while tts.SPEAKING.is_set() and time.monotonic() < deadline:
                time.sleep(0.05)
            import sounddevice as sd
            sd.play(render(rate, peak), rate)
            if wait:
                sd.wait()
        except Exception:  # noqa: BLE001 -- a signal must never take a conversation down
            log.debug("api tone failed", exc_info=True)
    if wait:
        _run()
    else:
        threading.Thread(target=_run, name="api-tone", daemon=True).start()
