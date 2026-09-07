"""Local, fast obstacle-avoidance reflex.

Pure logic: a `Frame` in, an `AvoidanceAction` out. No Claude, no network -- this
is the safety layer that has to react in a few frames. The caller maps the
action onto the actuator (kept separate so `vision` doesn't import the robot
link).

Heuristic: box `area` is the closeness proxy (bigger = nearer). An obstacle
`ahead` and near enough -> stop; near on one side only -> turn away from it.
A short consecutive-frame requirement debounces a flickery detector; a cooldown
stops it from spamming turns.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from .feed import Frame

log = logging.getLogger("g2.vision.avoid")


class AvoidanceAction(Enum):
    NONE = "none"          # clear -- carry on
    SLOW = "slow"          # something ahead, not near yet -- ease off the throttle
    STOP = "stop"          # something close, dead ahead
    BACK_UP = "back_up"    # very close, dead ahead
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"


# higher = more urgent; an urgent action preempts a cooldown
_URGENCY = {
    AvoidanceAction.NONE: 0,
    AvoidanceAction.SLOW: 1,
    AvoidanceAction.TURN_LEFT: 2,
    AvoidanceAction.TURN_RIGHT: 2,
    AvoidanceAction.STOP: 3,
    AvoidanceAction.BACK_UP: 4,
}


@dataclass
class AvoiderConfig:
    slow_area: float = 0.07     # box area (ahead) that triggers an anticipatory SLOW
    near_area: float = 0.14      # box area that counts as "near"
    stop_area: float = 0.22      # near + ahead past this -> STOP
    backup_area: float = 0.38    # ...past this -> BACK_UP
    min_confidence: float = 0.45
    consecutive: int = 2         # frames a hazard must persist before acting
    cooldown_frames: int = 4     # frames to hold an action / not re-decide


class Avoider:
    def __init__(self, cfg: AvoiderConfig | None = None):
        self._cfg = cfg or AvoiderConfig()
        self._streak = 0
        self._last: AvoidanceAction = AvoidanceAction.NONE
        self._cooldown = 0

    def decide(self, frame: Frame) -> AvoidanceAction:
        raw = self._raw_decision(frame)

        if self._cooldown > 0:
            self._cooldown -= 1
            # a more urgent hazard preempts the hold (e.g. turn -> back up)
            if _URGENCY[raw] > _URGENCY[self._last]:
                self._cooldown = self._cfg.cooldown_frames
                self._last = raw
                log.info("avoid -> %s (preempt)", raw.value)
                return raw
            return self._last

        if raw is AvoidanceAction.NONE:
            self._streak = 0
            self._last = AvoidanceAction.NONE
            return AvoidanceAction.NONE

        self._streak += 1
        # SLOW is cheap + reversible -- act on it immediately (anticipatory);
        # an immediate danger (stop / back up) also skips the debounce
        if raw in (AvoidanceAction.SLOW, AvoidanceAction.STOP, AvoidanceAction.BACK_UP) \
                or self._streak >= self._cfg.consecutive:
            self._streak = 0
            self._cooldown = self._cfg.cooldown_frames
            self._last = raw
            log.info("avoid -> %s", raw.value)
            return raw
        return AvoidanceAction.NONE  # not confirmed yet

    def _raw_decision(self, frame: Frame) -> AvoidanceAction:
        c = self._cfg
        seen = [d for d in frame if d.confidence >= c.min_confidence]
        hazards = [d for d in seen if d.area >= c.near_area]
        if not hazards:
            # nothing near yet -- but an obstacle coming up dead ahead -> SLOW
            far_ahead = [d for d in seen if d.bearing == "ahead" and d.area >= c.slow_area]
            return AvoidanceAction.SLOW if far_ahead else AvoidanceAction.NONE

        ahead = [d for d in hazards if d.bearing == "ahead"]
        if ahead:
            biggest = max(d.area for d in ahead)
            if biggest >= c.backup_area:
                return AvoidanceAction.BACK_UP
            if biggest >= c.stop_area:
                return AvoidanceAction.STOP
            # near but not stop-close, dead ahead -> ease around the side with
            # more room
            left_load = sum(d.area for d in hazards if d.bearing == "left")
            right_load = sum(d.area for d in hazards if d.bearing == "right")
            return AvoidanceAction.TURN_RIGHT if left_load >= right_load else AvoidanceAction.TURN_LEFT

        # nothing dead ahead; steer away from whichever side is loaded
        left_load = sum(d.area for d in hazards if d.bearing == "left")
        right_load = sum(d.area for d in hazards if d.bearing == "right")
        if max(left_load, right_load) < c.near_area:
            return AvoidanceAction.NONE
        return AvoidanceAction.TURN_RIGHT if left_load > right_load else AvoidanceAction.TURN_LEFT


# How the reflex maps to robot skills (the caller wires this to the actuator).
# SLOW has no skill -- the caller should instead scale the forward speed command
# down (e.g. to ~40%) while it's active, since the RL walk policy tracks a speed
# command directly. TURN_* trigger the firmware scripted turn gaits (RL turning
# is not available -- see docs/rl-runs/vision-goal-locomotion-plan.md).
ACTION_SKILL = {
    AvoidanceAction.STOP: "stand",
    AvoidanceAction.BACK_UP: "walk_backward",
    AvoidanceAction.TURN_LEFT: "walk_left",
    AvoidanceAction.TURN_RIGHT: "walk_right",
}

# Forward-speed multiplier the caller should apply for each action (for the ones
# that stay walking). Actions absent here are handled via ACTION_SKILL.
ACTION_SPEED_SCALE = {
    AvoidanceAction.NONE: 1.0,
    AvoidanceAction.SLOW: 0.4,
}
