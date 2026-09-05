"""Top-level behaviour mode: what G2 is doing when nobody's talking to it.

    CONVERSE  -- a conversation is active (wake word heard, mid-exchange).
                 Preempts everything; no autonomous movement.
    IDLE      -- awake, still. After `idle_secs_before_explore` of quiet -> EXPLORE.
    EXPLORE   -- wandering / investigating (see `explore.py`). Ends after
                 `explore_max_secs`, or immediately on any activity.

Pure logic + a clock, like `link/recovery.py`. The caller drives it:
`on_conversation_start/end`, `on_activity` (picked up, spoken to, told to stop),
and `update()` once per tick to get the current mode.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from ..personality.traits import BehaviorParams


class Mode(Enum):
    CONVERSE = "converse"
    IDLE = "idle"
    EXPLORE = "explore"


@dataclass
class ModeConfig:
    explore_max_secs: float = 90.0   # cap on one explore bout
    settle_secs: float = 3.0         # quiet grace after a conversation before wandering


class ModeController:
    def __init__(self, params: BehaviorParams, cfg: ModeConfig | None = None,
                 *, clock=time.monotonic):
        self.p = params
        self.cfg = cfg or ModeConfig()
        self._clock = clock
        self._mode = Mode.IDLE
        self._since = clock()          # when the current mode started
        self._last_activity = clock()  # last time something happened
        self._reason = "init"

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def last_reason(self) -> str:
        """Why the mode is what it is -- for diag logging."""
        return self._reason

    def _enter(self, m: Mode, now: float, reason: str) -> None:
        if m is not self._mode:
            self._mode = m
            self._since = now
        self._reason = reason

    # --- events ---

    def on_conversation_start(self) -> None:
        now = self._clock()
        self._last_activity = now
        self._enter(Mode.CONVERSE, now, "conversation started (wake word / addressed)")

    def on_conversation_end(self) -> None:
        now = self._clock()
        self._last_activity = now
        self._enter(Mode.IDLE, now, "conversation ended")

    def on_activity(self) -> None:
        """Anything that should stop autonomous roaming: picked up, addressed,
        an explicit 'stop', a loud noise."""
        now = self._clock()
        self._last_activity = now
        if self._mode is Mode.EXPLORE:
            self._enter(Mode.IDLE, now, "activity during explore (picked up / addressed / stop / noise)")

    # --- tick ---

    def update(self, now: float | None = None) -> Mode:
        now = self._clock() if now is None else now
        if self._mode is Mode.CONVERSE:
            return self._mode
        if self._mode is Mode.EXPLORE:
            if now - self._since >= self.cfg.explore_max_secs:
                self._enter(Mode.IDLE, now, f"explore bout hit cap ({self.cfg.explore_max_secs:.0f}s)")
            return self._mode
        # IDLE -> EXPLORE once it's been quiet long enough
        quiet = now - self._last_activity
        if quiet >= self.cfg.settle_secs and quiet >= self.p.idle_secs_before_explore:
            self._enter(Mode.EXPLORE, now,
                        f"{quiet:.0f}s quiet >= idle_secs_before_explore({self.p.idle_secs_before_explore:.0f})")
        return self._mode
