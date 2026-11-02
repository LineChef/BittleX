"""shutter -- a loud camera-shutter click played when G2 saves a picture (exploration survey / naming), so you can hear that a picture was taken.
A short noise burst plus a low thump, at the global volume (`sound_levels`). `G2_SHUTTER=off` silences it."""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

from .. import sound_levels

log = logging.getLogger("g2.shutter")


def render(rate: int = 48000) -> np.ndarray:
    rng = np.random.default_rng(7)
    t1 = np.arange(0, 0.03, 1.0 / rate)
    click = rng.standard_normal(len(t1)) * np.exp(-t1 * 160.0)             # the first click
    t2 = np.arange(0, 0.05, 1.0 / rate)
    thump = np.sin(2 * np.pi * 1800 * t2) * np.exp(-t2 * 90.0)              # the second, lower-pitched click
    y = np.concatenate([click, np.zeros(int(0.045 * rate)), thump * 0.9])
    return sound_levels.level(y)


def play(rate: int = 48000, wait: bool = False) -> None:
    """`wait=True` plays it to the end before returning: a short-lived command (g2look) would otherwise end its process, and the sound, before it was heard."""
    def _run() -> None:
        try:
            import sounddevice as sd
            sd.play(render(rate), rate)
            if wait:
                sd.wait()
        except Exception:  # noqa: BLE001
            log.debug("shutter sound failed", exc_info=True)
    if wait:
        _run()
    else:
        threading.Thread(target=_run, name="shutter", daemon=True).start()


def click() -> None:
    """The double click for a picture just taken: called by both picture paths (`vision/feed.py` snapshot for exploration, `vision/snapshot.py` for the voice
    "look" and describe), so it fires for every picture in every mode. At the global volume; `G2_SHUTTER=off` silences it. Never raises."""
    try:
        if os.environ.get("G2_SHUTTER", "on").lower() == "off":
            return
        play()
    except Exception:  # noqa: BLE001
        log.debug("shutter click failed", exc_info=True)
