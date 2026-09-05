"""Idle-posture staged descent -- what pose G2 holds when it has nothing to do.

The point is that it should feel *alive*: settle down in stages, not binary-flop
to the floor, keep tiny life signs while resting, and rouse (not snap) awake.

  ACTIVE   -- a command/task is running, or it just was. Standing/walking.
  SIT      -- alert idle. Entered after `sit_after_s` of quiet. LOW holding
              current, still "present" (head can track). This is the floor --
              there is deliberately no standing-idle state (a held stand is the
              servo thermal gap).
  RESTING  -- lying down (`d`), servos de-energised. Entered after `rest_after_s`
              more of quiet, IF safe_to_rest and not told to "stay". Emits an
              occasional PEEK (and optional breathing bob) so it's never inert.
  WAKING   -- rousing: head up -> stretch -> stand. Caller runs the choreography
              and calls `wake_done()`; auto-completes after `wake_timeout_s`.

Pure logic + a clock, like `link/recovery.py` / `behavior/mode_controller.py`.
The caller maps the returned PostureAction onto commands.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class Posture(Enum):
    ACTIVE = "active"
    SIT = "sit"
    RESTING = "resting"
    WAKING = "waking"


class PostureAction(Enum):
    NONE = "none"            # hold the current pose
    GO_SIT = "go_sit"        # descend to the alert sit
    GO_REST = "go_rest"      # lie down, relax servos (`d`)
    PEEK = "peek"            # small head look-around from rest -- a life sign
    LIFE_SIGN = "life_sign"  # tiny "breathing" body bob (optional)
    WAKE = "wake"            # run the rouse choreography (head up -> stretch -> stand)


@dataclass
class IdlePostureConfig:
    sit_after_s: float = 20.0           # quiet before ACTIVE -> SIT
    rest_after_s: float = 90.0          # more quiet in SIT before SIT -> RESTING
    person_rest_multiplier: float = 4.0  # person present -> hold SIT this much longer
    peek_s: float = 120.0              # life-sign PEEK interval while RESTING (caller may jitter)
    breathing: bool = False            # emit LIFE_SIGN bobs while RESTING
    breathing_period_s: float = 4.0
    wake_timeout_s: float = 4.0        # WAKING auto-finishes if wake_done() never comes


class IdlePosture:
    def __init__(self, cfg: IdlePostureConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or IdlePostureConfig()
        self._clock = clock
        self._posture = Posture.ACTIVE
        self._since = clock()
        self._last_activity = clock()
        self._stay = False
        self._wake_started: float | None = None
        self._last_peek = 0.0
        self._last_bob = 0.0
        self._reason = "init"

    @property
    def posture(self) -> Posture:
        return self._posture

    @property
    def last_reason(self) -> str:
        """Why the most recent update() returned what it did -- for diag logging."""
        return self._reason

    def _out(self, action: "PostureAction", reason: str):
        self._reason = reason
        return self._posture, action

    def _enter(self, p: Posture, now: float) -> None:
        if p is not self._posture:
            self._posture = p
            self._since = now
            if p is Posture.RESTING:
                self._last_peek = now
                self._last_bob = now
            if p is Posture.WAKING:
                self._wake_started = now

    # --- events -----------------------------------------------------------------
    def on_activity(self) -> None:
        """Command given, addressed, an explicit stop, a startling noise."""
        now = self._clock()
        self._last_activity = now
        self._stay = False
        if self._posture in (Posture.SIT, Posture.RESTING):
            self._enter(Posture.WAKING, now)

    def on_stay_command(self) -> None:
        """Told to 'stay' / 'wait here' -- sit and hold; never lie down."""
        now = self._clock()
        self._last_activity = now
        self._stay = True
        self._enter(Posture.SIT, now)

    def wake_done(self) -> None:
        if self._posture is Posture.WAKING:
            self._enter(Posture.ACTIVE, self._clock())
            self._last_activity = self._clock()

    # --- tick -----------------------------------------------------------------
    def update(self, now: float | None = None, *, exploring: bool = False,
               in_conversation: bool = False, person_present: bool = False,
               safe_to_rest: bool = True, handled: bool = False,
               nudge: bool = False) -> tuple[Posture, PostureAction]:
        now = self._clock() if now is None else now

        if handled:  # picked up / moved -- rouse to a safe pose immediately
            if self._posture is not Posture.WAKING:
                self._enter(Posture.WAKING, now)
                return self._out(PostureAction.WAKE, "handled=True (picked up / moved) -> rouse")
            return self._out(PostureAction.NONE, "handled, already waking")

        if self._posture is Posture.WAKING:
            if now - (self._wake_started or now) >= self.cfg.wake_timeout_s:
                self._enter(Posture.ACTIVE, now)
                self._last_activity = now
                return self._out(PostureAction.NONE, f"wake timed out after {self.cfg.wake_timeout_s}s -> active")
            return self._out(PostureAction.NONE, "waking, caller choreographing")

        if exploring:  # the explore layer drives walking; no descent
            self._last_activity = now
            if self._posture is not Posture.ACTIVE:
                self._enter(Posture.ACTIVE, now)
            return self._out(PostureAction.NONE, "exploring -> hold active, no descent")

        quiet = now - self._last_activity

        if in_conversation:  # attentive: hold SIT, never lie down
            if self._posture is Posture.RESTING:
                self._enter(Posture.WAKING, now)
                return self._out(PostureAction.WAKE, "conversation started while resting -> rouse to sit")
            if self._posture is Posture.ACTIVE and quiet >= self.cfg.sit_after_s:
                self._enter(Posture.SIT, now)
                return self._out(PostureAction.GO_SIT, f"in conversation, {quiet:.0f}s quiet -> attentive sit")
            return self._out(PostureAction.NONE, "in conversation, holding pose")

        # normal idle descent
        if self._posture is Posture.ACTIVE:
            if quiet >= self.cfg.sit_after_s:
                self._enter(Posture.SIT, now)
                return self._out(PostureAction.GO_SIT, f"{quiet:.0f}s quiet >= sit_after_s({self.cfg.sit_after_s:.0f})")
            return self._out(PostureAction.NONE, f"active, only {quiet:.0f}s quiet")

        if self._posture is Posture.SIT:
            rest_delay = self.cfg.rest_after_s * (
                self.cfg.person_rest_multiplier if person_present else 1.0)
            sat = now - self._since
            if self._stay:
                return self._out(PostureAction.NONE, "told to 'stay' -> hold sit")
            if not safe_to_rest:
                return self._out(PostureAction.NONE, "sit: not safe_to_rest (unlevel/held/recovering)")
            if sat >= rest_delay:
                self._enter(Posture.RESTING, now)
                why = f"{sat:.0f}s sat >= {rest_delay:.0f}s"
                if person_present:
                    why += f" (x{self.cfg.person_rest_multiplier:g} person-present)"
                return self._out(PostureAction.GO_REST, why)
            return self._out(PostureAction.NONE, f"sit, {sat:.0f}s / {rest_delay:.0f}s to rest")

        if self._posture is Posture.RESTING:
            if nudge:  # a nearby sound/motion -- look, don't get up
                self._last_peek = now
                return self._out(PostureAction.PEEK, "nudge (nearby sound/motion) -> peek, stay down")
            if now - self._last_peek >= self.cfg.peek_s:
                self._last_peek = now
                return self._out(PostureAction.PEEK, f"periodic life-sign peek ({self.cfg.peek_s:.0f}s)")
            if self.cfg.breathing and now - self._last_bob >= self.cfg.breathing_period_s:
                self._last_bob = now
                return self._out(PostureAction.LIFE_SIGN, "breathing bob")
            return self._out(PostureAction.NONE, "resting")

        return self._out(PostureAction.NONE, "no-op")


# caller maps these onto OpenCat commands (SIT/REST/STRETCH keyframes, head moves)
ACTION_HINT = {
    PostureAction.GO_SIT: "ksit",
    PostureAction.GO_REST: "d",
    PostureAction.WAKE: "str -> kup",   # stretch, then stand (caller choreographs)
    PostureAction.PEEK: "head pan sweep, then hold",
    PostureAction.LIFE_SIGN: "small body-height bob",
    PostureAction.NONE: "",
}
