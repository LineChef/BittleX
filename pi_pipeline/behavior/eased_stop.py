"""An eased stop out of a stride (user, 2026-11-06: "yes, we can try the eased stop"; a TEST variant of the 2026-10-10 rule that a stop out of a stride stays immediate).

The firmware's stop (`kbalance`) is one fast jump from the mid-stride pose to the balance pose. Here, at the NORMAL end of a timed firmware turn or back-up, the Pi first freezes the legs
where the gait is (an `i` pose estimated from the gait's frames and how long it has run) and then eases them to the balance pose at the usual 80 deg/s cap, and only then sends `kbalance`
(which has nothing left to jump). Never used for an emergency stop, a freeze, a halt or after a fall: those stay immediate.

The estimate: phase = run time / measured gait period; pose = that frame of the gait (link/gait_frames.json, decoded from the firmware header; a right turn is the left one mirrored). It is only
as good as the period and the start latency, and it is NOT known whether an `i` command cancels a running firmware gait cleanly on this board: the drill prints what happened. With no period,
no frames or no raw writer, nothing is done and the stop stays immediate.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

FRAMES_PATH = Path(__file__).resolve().parent.parent / "link" / "gait_frames.json"
MAX_RAMP_S = 0.8


@functools.lru_cache(maxsize=1)
def frames() -> dict:
    try:
        return json.loads(FRAMES_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _mirror(f):
    return [f[1], f[0], f[3], f[2], f[5], f[4], f[7], f[6]]


def gait_frames(token: str, arm: bool):
    """(frames, mirrored) for `kwkL` / `kwkR` / `kwkF` / `kbkF`, or (None, False)."""
    name = token.strip()[1:]
    base, side = name[:-1], name[-1:]
    rows = frames()
    cands = [(base + "Arm" + side, False), (base + "ArmL", True)] if arm else []
    cands += [(name, False), (base + "L", True)]
    for n, mir in cands:
        if mir and side != "R":
            continue
        if n in rows:
            return rows[n], mir
    return None, False


def pose_at(token: str, run_s: float, period_s: float, arm: bool = False):
    """The estimated leg pose (Petoi order) `run_s` into the gait, or None."""
    rows, mir = gait_frames(token, arm)
    if not rows or period_s <= 0:
        return None
    k = int(((run_s / period_s) % 1.0) * len(rows)) % len(rows)
    f = [float(x) for x in rows[k]]
    return _mirror(f) if mir else f
