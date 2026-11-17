"""The ball's own colour, remembered between sessions (2026-11-17, owner-approved after far balls were missed).

The colour pass of the finder (`ball_finder.find_ball_color`) finds a small pale ball 4 to 5 feet away that the fixed rules miss, but it needs the ball's own (r, g, b), which the chase samples only from a reading
within COLOR_SAMPLE_IN, so a session's first looks had none. This keeps the median of the latest close samples in a small file (`~/.local/share/g2/ball_color.json`) and loads it at the start of a chase, so the
colour pass works from the first look. It is switched on only by the real entry points (`enable()`), so tests and tools never write it. Nothing personal: three numbers.
"""
from __future__ import annotations

import json
import logging
import os
import statistics

log = logging.getLogger("g2.ball_color")

PATH = "~/.local/share/g2/ball_color.json"
ENABLED = False
KEEP = 9                      # the median of this many latest samples
SAVE_IF_OFF_BY = 6            # a new median this far from the saved one in any channel is saved
_samples: list = []


def enable() -> None:
    global ENABLED
    ENABLED = True


def load() -> tuple | None:
    """The saved colour as (r, g, b), or None (no file, unreadable, or not enabled)."""
    if not ENABLED:
        return None
    try:
        c = json.load(open(os.path.expanduser(PATH))).get("color")
        return tuple(int(x) for x in c) if c and len(c) == 3 else None
    except Exception:  # noqa: BLE001
        return None


def note(color: tuple | None) -> None:
    """One close sample of the ball's colour. Saves the running median when it has moved."""
    if not ENABLED or color is None:
        return
    _samples.append(tuple(int(x) for x in color))
    del _samples[:-KEEP]
    med = tuple(round(statistics.median(s[i] for s in _samples)) for i in range(3))
    saved = load()
    if saved is None or max(abs(a - b) for a, b in zip(med, saved)) > SAVE_IF_OFF_BY:
        try:
            path = os.path.expanduser(PATH)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"color": list(med), "samples": len(_samples)}, f)
            log.info("the ball's colour is remembered: %s", med)
        except Exception:  # noqa: BLE001
            log.exception("could not save the ball's colour")
