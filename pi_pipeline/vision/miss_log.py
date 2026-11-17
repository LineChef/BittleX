"""Far-miss evidence (2026-11-17, owner-approved): why does the finder miss a ball 4 to 5 feet away?

`note_miss(jpeg, where)` is called by every look that found no ball. It records the biggest green blob in the picture as numbers (always, kept in memory for the journal) and, when there is such a blob,
saves at most MAX_PICTURES missed-ball pictures per session to a folder of their own on the Pi (never the stream or tracking pictures, never a picture where the ball WAS found). `begin_session()` resets
the count; the goal calls it at the start of each session. The pictures stay on the Pi until the owner pulls them (`g2pics`).
"""
from __future__ import annotations

import logging
import os
import time

from . import ball_finder as bf

log = logging.getLogger("g2.miss_log")

MAX_PICTURES = 6
MIN_BLOB_AREA = 10                  # px: a green thing worth a picture (nothing green in it = an empty floor, not worth keeping)
_state = {"n": 0, "dir": None, "notes": []}


def begin_session() -> None:
    _state.update(n=0, dir=None, notes=[])


def notes() -> list:
    return list(_state["notes"])


def note_miss(jpeg: bytes | None, where: str) -> dict | None:
    """Record one miss. Returns the blob evidence (or None). Never raises."""
    try:
        if not jpeg:
            return None
        d = bf.diagnose(jpeg)
        _state["notes"].append({"where": where, "blob": d})
        del _state["notes"][:-40]
        if d is not None and d.get("area", 0) >= MIN_BLOB_AREA and _state["n"] < MAX_PICTURES:
            if _state["dir"] is None:
                _state["dir"] = os.path.expanduser(time.strftime("~/g2_claw_pics/misses_%Y%m%d_%H%M%S"))
                os.makedirs(_state["dir"], exist_ok=True)
            _state["n"] += 1
            with open(os.path.join(_state["dir"], f"miss_{_state['n']:02d}_{where}.jpg"), "wb") as f:
                f.write(jpeg)
            log.info("missed-ball picture %d of %d saved (%s): blob %s", _state["n"], MAX_PICTURES, where, d)
        return d
    except Exception:  # noqa: BLE001
        log.exception("miss log failed")
        return None
