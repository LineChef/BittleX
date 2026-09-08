"""Fall-recovery state machine -- the 'switch' in a walk / catch / get-up split.

Pure logic, mirroring `vision/avoidance.py`: body orientation in (roll & pitch,
radians, from the BiBoard IMU), a `RecoveryAction` out. No serial I/O here -- the
caller maps the action onto commands (see `ACTION_COMMANDS`) so this module stays
testable against a synthetic orientation trace.

Why a state machine and not one policy: the learned residual gait handles staying
upright *while walking* (its reactive catch). Getting up *after a fall* uses
OpenCat's scripted `rc` / `rl` / `dropRec` keyframe skills. This layer watches the
IMU and, once the robot is actually down: classifies WHICH fall pose it's in
(nose-down / tail-down / left side / right side / on its back), fires the maneuver
for that pose, waits, and on failure ESCALATES through a ladder
(pose skill -> roll+recover -> dropRec) before giving up and asking for a human.

  UPRIGHT  --tilt > wobble, < fall--> STUMBLING  (NONE: the gait's own catch runs)
           --tilt >= fall----------> FALLEN_*    (debounced) -> pose-specific action
  GETTING_UP  --stable again-------> SETTLE -> UPRIGHT
              --timeout-----------> escalate (up to max_attempts) -> GIVE_UP

Firmware relationship (docs/research/petoi-firmware-reference.md): OpenCatEsp32
auto-fires `rc` ONCE PER IMU TICK on `|roll| > 85deg` when gyro assist is on, with
no give-up. This FSM fires a touch earlier (fall_rad 1.3 rad = 74deg) so it can
pick the pose-specific maneuver before a full flip, and it DOES give up. If the
firmware's own auto-recover is left on, set `firmware_autorecover_on=True` so this
FSM defers the simple cases to firmware and only escalates when firmware's `rc`
has failed.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum

from . import opencat

log = logging.getLogger("g2.link.recovery")


class BodyState(Enum):
    UPRIGHT = "upright"
    STUMBLING = "stumbling"        # tilted past a wobble but not down -- gait handles it
    FALLEN_FRONT = "fallen_front"  # pitched past the fall line (nose-down / tail-down)
    FALLEN_SIDE = "fallen_side"    # rolled onto a side
    FALLEN_BACK = "fallen_back"    # rolled/pitched onto its back (supine)
    GETTING_UP = "getting_up"      # a recovery skill is running


class FallPose(Enum):
    """Finer classification within a FALLEN_* state -- picks the maneuver and is
    exposed for telemetry. NONE while upright/stumbling."""
    NONE = "none"
    NOSE_DOWN = "nose_down"        # face-plant: pitch strongly negative
    TAIL_DOWN = "tail_down"        # sat back on its rear: pitch strongly positive
    SIDE_LEFT = "side_left"        # rolled onto its left: roll strongly negative
    SIDE_RIGHT = "side_right"      # rolled onto its right: roll strongly positive
    BACK = "back"                  # supine


class RecoveryAction(Enum):
    NONE = "none"                          # leave control with the walking policy
    RECOVER = "recover"                    # send the `rc` get-up skill
    ROLL_THEN_RECOVER = "roll_then_recover"  # `rl` (roll off the back) then `rc`
    DROP_RECOVER = "drop_recover"          # `dropRec` -- the last-ditch scripted flail
    SETTLE = "settle"                      # get-up finished -> balanced stand
    GIVE_UP = "give_up"                    # too many failed attempts -- needs a human


@dataclass
class RecoveryConfig:
    wobble_rad: float = 0.6      # |roll| or |pitch| above this = STUMBLING
    fall_rad: float = 1.3        # at/above this = down. Deliberately below the
                                #   firmware's 85deg (1.48 rad) FLIPPED line so a
                                #   pose-specific maneuver can start before a full flip.
    supine_rad: float = 2.0     # |roll| or |pitch| past this = on its back (~114deg).
                                #   HARDWARE-GATED: tune against real IMU reads of a
                                #   resting-on-back pose (roll magnitude nears pi).
    stable_rad: float = 0.5     # back below this = upright again
    pose_deadband_rad: float = 0.35  # |axis| must exceed this to commit to a
                                     #   nose/tail or L/R sign; inside it, fall back
                                     #   to the dominant-axis rule
    fall_debounce: int = 3      # consecutive down-reads before firing a get-up
    stable_hold: int = 4        # consecutive stable reads before declaring recovered
    getup_timeout_s: float = 6.0  # a get-up skill should finish within this
    max_attempts: int = 3       # give up after this many failed get-ups

    # --- HARDWARE-GATED knobs (safe defaults; confirm/tune on the real robot) ---
    assume_symmetric_rc: bool = True   # True: one `rc` self-rights from either side.
                                       #   If HW shows `rc` is one-sided, set False and
                                       #   add krcL / krcR mirrored skills + wire them
                                       #   into ACTION_COMMANDS / _fire.
    firmware_autorecover_on: bool = False  # True: OpenCat gyro-assist auto-`rc` is
                                       #   left enabled -> defer NOSE/SIDE attempt 1 to
                                       #   firmware, only escalate on timeout. BACK still
                                       #   fires ROLL_THEN_RECOVER here (firmware never rolls).


class RecoveryFSM:
    """Feed it IMU roll/pitch every control tick; act on the returned action."""

    def __init__(self, cfg: RecoveryConfig | None = None, *, clock=time.monotonic):
        self._cfg = cfg or RecoveryConfig()
        self._clock = clock
        self._state = BodyState.UPRIGHT
        self._pose = FallPose.NONE
        self._fall_streak = 0        # consecutive down-reads (debounce)
        self._stable_streak = 0      # consecutive stable-reads during GETTING_UP
        self._attempts = 0
        self._getup_started: float | None = None
        self._gave_up = False
        self._last_reason = ""

    @property
    def state(self) -> BodyState:
        return self._state

    @property
    def pose(self) -> FallPose:
        """The fall pose being recovered from (or last recovered from)."""
        return self._pose

    @property
    def last_reason(self) -> str:
        """Human-readable note on the most recent decision (for diag)."""
        return self._last_reason

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

    def _classify_pose(self, state: BodyState, roll: float, pitch: float) -> FallPose:
        """Refine a FALLEN_* state into the specific pose that selects the maneuver."""
        if state is BodyState.FALLEN_BACK:
            return FallPose.BACK
        if state is BodyState.FALLEN_SIDE:
            # roll sign: +ve = onto the right, -ve = onto the left (BiBoard convention;
            # HARDWARE-GATED -- verify the sign on the real IMU, flip here if reversed).
            return FallPose.SIDE_RIGHT if roll >= 0 else FallPose.SIDE_LEFT
        if state is BodyState.FALLEN_FRONT:
            # pitch sign (BiBoard convention: +ve = pitched forward = nose-down
            # face-plant, -ve = sat back on the rear). HARDWARE-GATED -- verify the
            # sign on the real IMU and flip this comparison if reversed.
            if abs(pitch) < self._cfg.pose_deadband_rad:
                return FallPose.NOSE_DOWN   # ambiguous small pitch -> treat as face-plant
            return FallPose.NOSE_DOWN if pitch > 0 else FallPose.TAIL_DOWN
        return FallPose.NONE

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
                    log.info("recovery: back upright after %d attempt(s) from %s",
                             self._attempts, self._pose.value)
                    self._last_reason = f"recovered from {self._pose.value} in {self._attempts} attempt(s)"
                    self._state = BodyState.UPRIGHT
                    self._reset_getup()
                    return RecoveryAction.SETTLE
                return RecoveryAction.NONE
            self._stable_streak = 0
            if self._clock() - (self._getup_started or 0) >= self._cfg.getup_timeout_s:
                self._attempts += 1
                if self._attempts > self._cfg.max_attempts:
                    log.warning("recovery: gave up after %d attempts from %s -- needs a human",
                                self._cfg.max_attempts, self._pose.value)
                    self._last_reason = f"gave up ({self._pose.value}, {self._cfg.max_attempts} attempts)"
                    self._gave_up = True
                    self._state = obs
                    return RecoveryAction.GIVE_UP
                log.info("recovery: get-up timed out, escalating (attempt %d/%d)",
                         self._attempts, self._cfg.max_attempts)
                self._getup_started = self._clock()
                return self._fire(self._pose, self._attempts)
            return RecoveryAction.NONE

        # --- not currently recovering --------------------------------
        if obs in (BodyState.UPRIGHT, BodyState.STUMBLING):
            self._state = obs
            self._pose = FallPose.NONE
            self._fall_streak = 0
            return RecoveryAction.NONE

        # obs is a FALLEN_* state -- debounce a transient IMU spike
        self._fall_streak += 1
        self._state = obs
        if self._fall_streak < self._cfg.fall_debounce:
            return RecoveryAction.NONE

        # confirmed down -> start the get-up ladder (this is attempt 1)
        self._pose = self._classify_pose(obs, roll, pitch)
        self._attempts = 1
        self._getup_started = self._clock()
        self._state = BodyState.GETTING_UP
        return self._fire(self._pose, 1)

    # -- maneuver selection -------------------------------------------

    def _fire(self, pose: FallPose, attempt: int) -> RecoveryAction:
        """The escalation ladder. attempt 1 = pose-specific; 2 = roll+recover
        (the strong general one); 3 = dropRec; anything past max_attempts in the
        caller becomes GIVE_UP."""
        c = self._cfg

        if attempt >= 3:
            self._log_fire(pose, attempt, "dropRec (last-ditch)")
            return RecoveryAction.DROP_RECOVER

        if attempt == 2:
            # roll off whatever it's on, then push up -- works from side or back
            self._log_fire(pose, attempt, "roll + recover")
            return RecoveryAction.ROLL_THEN_RECOVER

        # attempt 1 -- pose-specific
        if pose is FallPose.BACK:
            # firmware never rolls; always do it here even if firmware auto-recover is on
            self._log_fire(pose, attempt, "supine -> roll then recover")
            return RecoveryAction.ROLL_THEN_RECOVER

        if c.firmware_autorecover_on and pose in (FallPose.NOSE_DOWN, FallPose.SIDE_LEFT,
                                                  FallPose.SIDE_RIGHT):
            # let the firmware's own auto-`rc` take the first shot; we time it and escalate
            self._log_fire(pose, attempt, "defer to firmware auto-rc")
            return RecoveryAction.NONE

        if pose in (FallPose.SIDE_LEFT, FallPose.SIDE_RIGHT):
            # HARDWARE-GATED: if assume_symmetric_rc is False, dispatch a mirrored
            # krcL / krcR here instead of the single RECOVER.
            self._log_fire(pose, attempt, "side -> recover"
                           + ("" if c.assume_symmetric_rc else " (NOTE: mirrored rc not wired)"))
            return RecoveryAction.RECOVER

        if pose is FallPose.TAIL_DOWN:
            # HARDWARE-GATED: sitting back on the rear may need custom keyframes;
            # `rc` is the best available default.
            self._log_fire(pose, attempt, "tail-down -> recover (may need custom keyframes)")
            return RecoveryAction.RECOVER

        # NOSE_DOWN and the fallback
        self._log_fire(pose, attempt, "nose-down -> recover")
        return RecoveryAction.RECOVER

    def _log_fire(self, pose: FallPose, attempt: int, note: str) -> None:
        self._last_reason = f"attempt {attempt} [{pose.value}]: {note}"
        log.info("recovery: %s", self._last_reason)

    def _reset_getup(self) -> None:
        self._fall_streak = 0
        self._stable_streak = 0
        self._attempts = 0
        self._getup_started = None


# How each action maps to OpenCat serial commands. The caller sends these in
# order (with a wait between -- a keyframe skill takes ~1-2 s).
ACTION_COMMANDS = {
    RecoveryAction.NONE: [],
    RecoveryAction.RECOVER: [opencat.RECOVER],                       # ["krc"]
    RecoveryAction.ROLL_THEN_RECOVER: [opencat.ROLL_OVER, opencat.RECOVER],  # ["krl","krc"]
    RecoveryAction.DROP_RECOVER: [opencat.DROP_RECOVER],             # ["kdropRec"]
    RecoveryAction.SETTLE: [opencat.BALANCE],                        # ["kbalance"]
    RecoveryAction.GIVE_UP: [],  # caller decides: beep, notify, stop the loop
}
