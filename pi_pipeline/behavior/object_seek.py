"""ObjectSeek -- *when* it's appropriate to grab a candidate frame for the
object recognition gallery (`vision/object_gallery.py`, B20) while G2 is
exploring. Pure logic, injectable clock, same shape as `idle_posture.py` /
`gesture_picker.py` -- no I/O, no camera, no model.

Priority is enforced structurally, not by re-checking flags here: this is
only ever called from `BehaviorDriver._from_explore()`, which the driver only
reaches after emergency stop, sleep, enrollment, choreography/safety,
"come here", and conversation have all already had first claim on the tick
(`driver.py`'s priority order). By the time this module sees a call, every
"primary system" this session discussed has already taken precedence --
`ObjectSeek` has nothing left to defer to except locomotion itself, which it
defers to directly (see below).

Two more layers of "don't get in the way", specific to this behaviour:

  * **Never during actual movement.** `Explorer.decide()` this tick has
    already been computed by the time `ObjectSeek.update()` runs; a scan is
    only ever proposed when that decision was `HOLD` or `INVESTIGATE` --
    the two moments Explorer is already stationary for its own reasons.
    `WANDER` / `TURN` / `APPROACH` never get a scan request layered on top --
    this never asks G2 to stop walking just to take a photo, and a photo
    taken while walking would be motion-blurred and useless anyway.
  * **Rate-limited and capacity-aware.** A cooldown between scans (default
    20s) even when stationary a while, and `gallery_has_capacity=False`
    (the gallery is full and nothing's evictable) stops requests outright --
    no point spending camera time capturing something with nowhere to go.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from .explore import ExploreAction


class ObjectSeekAction(Enum):
    NONE = "none"
    SCAN = "scan"       # grab a candidate frame now


@dataclass
class ObjectSeekConfig:
    scan_cooldown_s: float = 20.0   # minimum gap between scan requests


@dataclass
class ObjectSeekTick:
    action: ObjectSeekAction
    reason: str = ""


_STATIONARY = (ExploreAction.HOLD, ExploreAction.INVESTIGATE)


class ObjectSeek:
    def __init__(self, cfg: ObjectSeekConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or ObjectSeekConfig()
        self._clock = clock
        self._last_scan: float | None = None

    def update(self, now: float | None = None, *, explore_action: ExploreAction,
              gallery_has_capacity: bool = True) -> ObjectSeekTick:
        now = self._clock() if now is None else now

        if explore_action not in _STATIONARY:
            return ObjectSeekTick(ObjectSeekAction.NONE,
                                  "moving -- never interrupt locomotion for a scan")
        if not gallery_has_capacity:
            return ObjectSeekTick(ObjectSeekAction.NONE, "gallery at capacity")
        if self._last_scan is not None and now - self._last_scan < self.cfg.scan_cooldown_s:
            return ObjectSeekTick(ObjectSeekAction.NONE, "cooldown")

        self._last_scan = now
        return ObjectSeekTick(ObjectSeekAction.SCAN,
                              f"stationary during explore ({explore_action.value})")

    def reset(self) -> None:
        """Forget the cooldown -- called when explore mode is (re)armed, so a
        fresh roam bout doesn't inherit a stale cooldown from hours ago."""
        self._last_scan = None
