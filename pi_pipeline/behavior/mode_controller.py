"""Top-level behaviour mode: what G2 is doing when nobody's talking to it.

    CONVERSE  -- a conversation is active (wake word heard, mid-exchange).
                 Preempts everything; no autonomous movement.
    IDLE      -- awake, still. G2 holds a posture and expresses curiosity
                 *without walking* (the Tier 0 "attentive" layer -- see
                 `attentive.py`).
    EXPLORE   -- Tier 1: walking exploration. **Voice-armed only** -- entered
                 solely when `arm_explore()` has been called ("G2, go ahead and
                 look around"). Ends after `explore_max_secs`, on any activity,
                 or on `disarm_explore()` -- and disarms, so it must be
                 re-armed by voice each bout. There is deliberately no
                 time-based entry: G2 never starts roaming on its own.

Pure logic + a clock, like `link/recovery.py`. The caller drives it:
`on_conversation_start/end`, `on_activity` (picked up, spoken to, told to stop),
`arm_explore` / `disarm_explore` (the voice command), and `update()` once per
tick to get the current mode.
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
    explore_max_secs: float = 90.0   # cap on one armed explore bout
    settle_secs: float = 3.0         # quiet grace after a conversation before EXPLORE can arm
    allow_explore: bool = True       # False -> EXPLORE can never be entered even if armed
                                     #   (no vision hardware to wander safely; the Tier 0
                                     #   attentive layer + CONVERSE + IDLE still work)


class ModeController:
    def __init__(self, params: BehaviorParams, cfg: ModeConfig | None = None,
                 *, clock=time.monotonic):
        self.p = params
        self.cfg = cfg or ModeConfig()
        self._clock = clock
        self._mode = Mode.IDLE
        self._since = clock()          # when the current mode started
        self._last_activity = clock()  # last time something happened
        self._explore_armed = False    # set by arm_explore() (a voice command)
        self._reason = "init"

    @property
    def explore_armed(self) -> bool:
        return self._explore_armed

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
        self._explore_armed = False   # a fresh interaction supersedes an old roam intent
        self._enter(Mode.CONVERSE, now, "conversation started (wake word / addressed)")

    def on_conversation_end(self) -> None:
        now = self._clock()
        self._last_activity = now
        self._enter(Mode.IDLE, now, "conversation ended")

    def on_activity(self) -> None:
        """Anything that should stop autonomous roaming: picked up, addressed,
        an explicit 'stop', a loud noise. Also disarms EXPLORE."""
        now = self._clock()
        self._last_activity = now
        self._explore_armed = False
        if self._mode is Mode.EXPLORE:
            self._enter(Mode.IDLE, now, "activity during explore (picked up / addressed / stop / noise)")

    def arm_explore(self) -> None:
        """Voice command 'go ahead and look around' -- lets IDLE advance to
        EXPLORE (Tier 1 roam) once the post-conversation settle grace passes."""
        self._explore_armed = True
        self._reason = "explore armed by voice"

    def disarm_explore(self) -> None:
        """'That's enough' / end the roam bout; back to IDLE + attentive."""
        now = self._clock()
        self._explore_armed = False
        if self._mode is Mode.EXPLORE:
            self._enter(Mode.IDLE, now, "explore disarmed by voice")

    # --- tick ---

    def update(self, now: float | None = None) -> Mode:
        now = self._clock() if now is None else now
        if self._mode is Mode.CONVERSE:
            return self._mode
        if self._mode is Mode.EXPLORE:
            if now - self._since >= self.cfg.explore_max_secs:
                self._explore_armed = False
                self._enter(Mode.IDLE, now, f"explore bout hit cap ({self.cfg.explore_max_secs:.0f}s)")
            return self._mode
        # IDLE -> EXPLORE only when armed by voice (never time-based).
        if not self._explore_armed:
            self._reason = "idle (explore not armed)"
            return self._mode
        if not self.cfg.allow_explore:
            self._reason = "explore armed but disabled (allow_explore=False -- no vision hardware)"
            return self._mode
        if now - self._last_activity >= self.cfg.settle_secs:
            self._enter(Mode.EXPLORE, now, "armed by voice, settle grace passed")
        return self._mode
