"""shutter -- a loud camera-shutter click played when G2 saves a picture (exploration survey / naming), so you can hear that a picture was taken.
A short noise burst plus a low thump, much louder than the other signal sounds (0.5 of full scale; `G2_SHUTTER_PEAK`). `G2_SHUTTER=off` silences it."""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

log = logging.getLogger("g2.shutter")

DEFAULT_PEAK = 0.5


def render(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    rng = np.random.default_rng(7)
    t1 = np.arange(0, 0.03, 1.0 / rate)
    click = rng.standard_normal(len(t1)) * np.exp(-t1 * 160.0)             # the first click
    t2 = np.arange(0, 0.05, 1.0 / rate)
    thump = np.sin(2 * np.pi * 1800 * t2) * np.exp(-t2 * 90.0)              # the second, lower-pitched click
    y = np.concatenate([click, np.zeros(int(0.045 * rate)), thump * 0.9])
    y = y / np.abs(y).max() * peak
    return (y * 32767).astype(np.int16)


def play(peak: float = DEFAULT_PEAK, rate: int = 48000) -> None:
    def _run() -> None:
        try:
            import sounddevice as sd
            sd.play(render(rate, peak), rate)
        except Exception:  # noqa: BLE001
            log.debug("shutter sound failed", exc_info=True)
    threading.Thread(target=_run, name="shutter", daemon=True).start()


def click() -> None:
    """The double click for a picture just taken: called by both picture paths (`vision/feed.py` snapshot for exploration, `vision/snapshot.py` for the voice
    "look" and describe), so it fires for every picture in every mode. Level from `G2_SHUTTER_PEAK`, `G2_SHUTTER=off` silences it. Never raises."""
    try:
        if os.environ.get("G2_SHUTTER", "on").lower() == "off":
            return
        play(float(os.environ.get("G2_SHUTTER_PEAK", DEFAULT_PEAK)))
    except Exception:  # noqa: BLE001
        log.debug("shutter click failed", exc_info=True)
