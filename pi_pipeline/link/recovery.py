"""Fall-recovery state machine -- the 'switch' in a walk / catch / get-up split.

Pure logic, mirroring `vision/avoidance.py`: body orientation in (roll & pitch,
radians, from the BiBoard IMU), a `RecoveryAction` out. No serial I/O here -- the
caller maps the action onto commands (see `ACTION_COMMANDS`) so this module stays
testable against a synthetic orientation trace.

Why a state machine and not one policy: the learned residual gait handles staying
upright *while walking* (its reactive catch). Getting up *after a fall* is a
different problem that a flat quadruped with no roll-axis joint can't learn --
but OpenCat ships scripted `rc` / `rl` keyframe skills that do it. This layer
watches the IMU and, once the robot is actually down, fires the right script,
waits for it, retries a bounded number of times, and gives up (asks for a human)
rather than thrashing forever.

  UPRIGHT  --tilt > wobble, < fall--> STUMBLING  (NONE: the gait's own catch runs)
           --tilt >= fall----------> FALLEN_*    (debounced) -> RECOVER / ROLL_THEN_RECOVER
  GETTING_UP  --stable again-------> SETTLE -> UPRIGHT
              --timeout-----------> retry (up to max_attempts) -> GIVE_UP
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger("g2.link.recovery")


class BodyState(Enum):
    UPRIGHT = "upright"
    STUMBLING = "stumbling"        # tilted past a wobble but not down -- gait handles it
    FALLEN_FRONT = "fallen_front"  # pitched past the fall line (nose-down / tail-down)
    FALLEN_SIDE = "fallen_side"    # rolled onto a side
    FALLEN_BACK = "fallen_back"    # rolled/pitched onto its back (supine)
    GETTING_UP = "getting_up"      # a recovery skill is running


class RecoveryAction(Enum):
    NONE = "none"                          # leave control with the walking policy
    RECOVER = "recover"                    # send the `rc` get-up skill
    ROLL_THEN_RECOVER = "roll_then_recover"  # `rl` (roll off the back) then `rc`
    SETTLE = "settle"                      # get-up finished -> balanced stand
    GIVE_UP = "give_up"                    # too many failed attempts -- needs a human


@dataclass
class RecoveryConfig:
    wobble_rad: float = 0.6      # |roll| or |pitch| above this = STUMBLING
    fall_rad: float = 1.3        # at/above this = down (matches is_fallen() in sim)
    supine_rad: float = 2.0      # |roll| or |pitch| past this = on its back
    stable_rad: float = 0.5      # back below this = upright again
    fall_debounce: int = 3       # consecutive down-reads before firing a get-up
    stable_hold: int = 4         # consecutive stable reads before declaring recovered
    getup_timeout_s: float = 6.0  # a get-up skill should finish within this
    max_attempts: int = 3        # give up after this many failed get-ups


class RecoveryFSM:
    """Feed it IMU roll/pitch every control tick; act on the returned action."""

    def __init__(self, cfg: RecoveryConfig | None = None, *, clock=time.monotonic):
        self._cfg = cfg or RecoveryConfig()
        self._clock = clock
        self._state = BodyState.UPRIGHT
        self._fall_streak = 0        # consecutive down-reads (debounce)
        self._stable_streak = 0      # consecutive stable-reads during GETTING_UP
        self._attempts = 0
        self._getup_started: float | None = None
        self._gave_up = False

    @property
    def state(self) -> BodyState:
        return self._state

    def reset(self) -> None:
        self.__init__(self._cfg, clock=self._clock)

    # -- classification ---------------------------------------------------

    def _classify(self, roll: float, pitch: float) -> BodyState:
        c = self._cfg
        tilt = max(abs(roll), abs(pitch))
        if tilt < c.wobble_rad:
            return BodyState.UPRIGHT
        if tilt < c.fall_rad:
            return BodyState.STUMBLING
        if abs(roll) >= c.supine_rad or abs(pitch) >= c.supine_rad:
            return BodyState.FALLEN_BACK
        if abs(roll) >= abs(pitch):
            return BodyState.FALLEN_SIDE
        return BodyState.FALLEN_FRONT

    # -- tick -----------------------------------------------------------

    def update(self, roll: float, pitch: float) -> RecoveryAction:
        if self._gave_up:
            return RecoveryAction.NONE

        obs = self._classify(roll, pitch)

        # --- a get-up is in progress -----------------------------------
        if self._state is BodyState.GETTING_UP:
            if max(abs(roll), abs(pitch)) < self._cfg.stable_rad:
                self._stable_streak += 1
                if self._stable_streak >= self._cfg.stable_hold:
                    log.info("recovery: back upright after %d attempt(s)", self._attempts)
                    self._state = BodyState.UPRIGHT
                    self._reset_getup()
                    return RecoveryAction.SETTLE
                return RecoveryAction.NONE
            self._stable_streak = 0
            if self._clock() - (self._getup_started or 0) >= self._cfg.getup_timeout_s:
                self._attempts += 1
                if self._attempts >= self._cfg.max_attempts:
                    log.warning("recovery: gave up after %d attempts -- needs a human",
                                self._attempts)
                    self._gave_up = True
                    self._state = obs
                    return RecoveryAction.GIVE_UP
                log.info("recovery: get-up timed out, retry %d/%d",
                         self._attempts, self._cfg.max_attempts)
                self._getup_started = self._clock()
                return self._fire(obs)
            return RecoveryAction.NONE

        # --- not currently recovering --------------------------------
        if obs in (BodyState.UPRIGHT, BodyState.STUMBLING):
            self._state = obs
            self._fall_streak = 0
            return RecoveryAction.NONE

        # obs is a FALLEN_* state -- debounce a transient IMU spike
        self._fall_streak += 1
        self._state = obs
        if self._fall_streak < self._cfg.fall_debounce:
            return RecoveryAction.NONE

        # confirmed down -> start a get-up (this is attempt 1 of max_attempts)
        self._attempts = 1
        self._getup_started = self._clock()
        self._state = BodyState.GETTING_UP
        return self._fire(obs)

    # -- helpers ------------------------------------------------------

    def _fire(self, fallen_state: BodyState) -> RecoveryAction:
        if fallen_state is BodyState.FALLEN_BACK:
            log.info("recovery: supine -> roll then recover")
            return RecoveryAction.ROLL_THEN_RECOVER
        log.info("recovery: %s -> recover", fallen_state.value)
        return RecoveryAction.RECOVER

    def _reset_getup(self) -> None:
        self._fall_streak = 0
        self._stable_streak = 0
        self._attempts = 0
        self._getup_started = None


# How each action maps to OpenCat serial commands. The caller sends these in
# order (with a wait between -- a keyframe skill takes ~1-2 s).
ACTION_COMMANDS = {
    RecoveryAction.NONE: [],
    RecoveryAction.RECOVER: ["krc"],
    RecoveryAction.ROLL_THEN_RECOVER: ["krl", "krc"],
    RecoveryAction.SETTLE: ["kbalance"],
    RecoveryAction.GIVE_UP: [],  # caller decides: beep, notify, stop the loop
}
