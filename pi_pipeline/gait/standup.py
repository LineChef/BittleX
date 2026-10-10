"""Eased stand-up before a walk.

The walk loops used to send the policy's stand pose (one `i` command) straight from the rest pose. That moves every leg servo at top speed and jerks G2's heading
before the first step (2026-10-10: a 20 s run started at 12:30 instead of 12). The firmware's own `kbalance` skill interpolates from the current pose, so it is sent first;
the policy stand pose that follows is a small move from there. `G2_STAND_EASE=off` skips it (the old behaviour).
"""
from __future__ import annotations

import os
import time

BALANCE = "kbalance"       # the firmware skill that settles into a balanced stand (link/opencat.py BALANCE)

EASE_SETTLE_S = 1.5          # time given to the firmware to finish the eased stand-up (first guess, tune on G2)


def ease_enabled() -> bool:
    return os.environ.get("G2_STAND_EASE", "on").strip().lower() not in ("off", "0", "false", "no")


def ease_to_stand(send, sleep=time.sleep, settle_s: float = EASE_SETTLE_S) -> bool:
    """Send `kbalance` and wait for it to finish. `send(cmd)` is the caller's fire-and-forget serial send. Returns True if the ease ran."""
    if not ease_enabled():
        return False
    send(BALANCE)
    sleep(settle_s)
    return True
