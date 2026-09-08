"""CliffGuard -- the hard "don't walk off the desk" reflex.

Pure logic, same shape as `avoidance.py` (Avoider) and `link/recovery.py`
(RecoveryFSM): an `EdgeReading` in, a `CliffAction` out, no I/O. The caller maps
the action onto commands (`ACTION_COMMANDS`) and speed scaling
(`ACTION_SPEED_SCALE`).

Why it's above the gait, not in it (behaviour-ideas B16): the walk policy has no
forward perception and the real Bittle has no foot-force sensing, so it cannot
feel "no ground" reactively the way it feels a stumble -- by the time an edge
reaches the policy's senses it has already committed. So the edge decision lives
here, deciding whether forward motion is commanded at all.

This module is the DECISION LOGIC only. Its two hardware halves are stubbed:

  * THE DETECTOR -- what produces an `EdgeReading` (a floor-vs-edge classifier on
    the mounted-camera POV, per B16). Not built: it has to be trained on real
    mounted frames. `MockEdgeFeed` stands in for tests.
  * THE TUNABLES -- every value marked HARDWARE-GATED in `CliffGuardConfig`
    (turn token, pivot safety margin, whether the rear can be sensed, ...).
    Safe, paranoid defaults; confirm on the real desk.

Design rules (B16): zero debounce on stopping (one confident not-floor read =
stop, bias entirely to false stops); resuming forward needs several consecutive
clear reads; a pivot sweeps the body toward whatever it's turning past, so near a
close edge prefer FREEZE over a risky turn; edge on more than one side, or the
floor lost entirely -> FREEZE and call a human.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from ..link import opencat

log = logging.getLogger("g2.vision.cliff")


@dataclass
class EdgeReading:
    """One scan frame. Matches the sim CLIFF feature layout
    [edge_present, edge_dist_norm, edge_bearing_norm] plus a detector confidence.
    On hardware this comes from the floor-vs-edge classifier (STUBBED -- see
    module docstring / MockEdgeFeed)."""
    present: bool            # an edge / drop is visible ahead
    dist_norm: float         # nearest edge distance, 0.0 (at it) .. 1.0 (far / none)
    bearing_norm: float      # where it is: -1.0 hard-left .. 0.0 ahead .. +1.0 hard-right
    confidence: float = 1.0  # detector confidence in this read, 0..1


class CliffAction(Enum):
    NONE = "none"                    # clear floor -- carry on
    SLOW = "slow"                    # edge visible but far -- creep (buy reaction margin)
    STOP = "stop"                    # edge close ahead -- hard stop, hold
    TURN_AWAY_LEFT = "turn_away_left"
    TURN_AWAY_RIGHT = "turn_away_right"
    BACK_UP = "back_up"             # close dead-ahead AND the rear is known clear
    FREEZE = "freeze"               # boxed in / floor lost -- stop, beep, wait for a human


@dataclass
class CliffGuardConfig:
    slow_dist: float = 0.55       # dist_norm below this (edge in view, not near) -> SLOW
    stop_dist: float = 0.30       # below this -> STOP / turn away
    ahead_bearing: float = 0.35   # |bearing_norm| within this = "dead ahead"
    clear_scans_to_resume: int = 3  # consecutive clear reads before releasing a hold
    min_confidence: float = 0.60  # a not-present read below this = "unsure" -> STOP anyway
    max_turn_attempts: int = 3    # turn-aways issued without clearing -> FREEZE
    creep_speed_scale: float = 0.30  # forward-speed multiplier for SLOW

    # --- HARDWARE-GATED (paranoid defaults; confirm/tune on the real desk) ------
    rear_sensing: bool = False    # False: cannot see behind -> never BACK_UP; turn or FREEZE
    pivot_safe_dist: float = 0.15  # do NOT pivot if the edge is closer than this
                                   #   (a turn sweeps the body/legs toward it) -> FREEZE.
                                   #   Must be < stop_dist so a turn-away band exists.
                                   #   Tune to the real turn's body-sweep radius.
    turn_left_token: str = opencat.WALK_LEFT    # or "kang <deg>" once IMU-closed-loop
    turn_right_token: str = opencat.WALK_RIGHT  #   turning is tuned on hardware
    backup_token: str = opencat.WALK_BACKWARD


class CliffGuard:
    """Feed it an `EdgeReading` every scan; act on the returned `CliffAction`.
    STOP/turn is immediate (zero debounce); NONE only returns after
    `clear_scans_to_resume` consecutive clear reads once a hold has started."""

    def __init__(self, cfg: CliffGuardConfig | None = None):
        self._cfg = cfg or CliffGuardConfig()
        self._holding = False        # currently stopped/turning for an edge
        self._clear_streak = 0
        self._turn_attempts = 0
        self._frozen = False
        self._last_reason = ""

    @property
    def holding(self) -> bool:
        return self._holding

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def last_reason(self) -> str:
        return self._last_reason

    def reset(self) -> None:
        self.__init__(self._cfg)

    # -- decision ------------------------------------------------------

    def update(self, r: EdgeReading) -> CliffAction:
        c = self._cfg
        if self._frozen:
            return CliffAction.FREEZE

        # unsure read (detector not confident it's floor) -> treat as a hazard
        unsure = (not r.present) and r.confidence < c.min_confidence
        clear = (not r.present) and not unsure

        if clear:
            if not self._holding:
                self._clear_streak = 0
                return self._say(CliffAction.NONE, "clear floor")
            self._clear_streak += 1
            if self._clear_streak >= c.clear_scans_to_resume:
                self._holding = False
                self._turn_attempts = 0
                return self._say(CliffAction.NONE,
                                 f"clear x{self._clear_streak} -- resume")
            return self._say(CliffAction.STOP,
                             f"clearing ({self._clear_streak}/{c.clear_scans_to_resume})")

        # a hazard (edge present, or unsure) -------------------------------
        self._clear_streak = 0
        self._holding = True

        if unsure:
            return self._say(CliffAction.STOP, "detector unsure -- hold")

        # edge present: distance gates
        if r.dist_norm >= c.slow_dist:
            return self._say(CliffAction.SLOW, f"edge far ({r.dist_norm:.2f}) -- creep")
        if r.dist_norm >= c.stop_dist:
            return self._say(CliffAction.STOP, f"edge near ({r.dist_norm:.2f}) -- hold")

        # edge is CLOSE -> must move away from it
        too_close_to_pivot = r.dist_norm < c.pivot_safe_dist
        dead_ahead = abs(r.bearing_norm) <= c.ahead_bearing

        if dead_ahead and c.rear_sensing:
            return self._say(CliffAction.BACK_UP, "close dead-ahead -- back up (rear clear)")

        if too_close_to_pivot:
            self._frozen = True
            return self._say(CliffAction.FREEZE,
                             f"edge too close to pivot safely ({r.dist_norm:.2f})")

        self._turn_attempts += 1
        if self._turn_attempts > c.max_turn_attempts:
            self._frozen = True
            return self._say(CliffAction.FREEZE,
                             f"{self._turn_attempts - 1} turn-aways, still not clear")

        # turn away from the edge. bearing > 0 = edge on the right -> turn left.
        # dead-ahead (bearing ~0): default to turning left, consistently.
        if r.bearing_norm > c.ahead_bearing:
            act = CliffAction.TURN_AWAY_LEFT
        elif r.bearing_norm < -c.ahead_bearing:
            act = CliffAction.TURN_AWAY_RIGHT
        else:
            act = CliffAction.TURN_AWAY_LEFT   # dead-ahead: consistent default
        return self._say(act, f"turn away (attempt {self._turn_attempts}, bearing {r.bearing_norm:+.2f})")

    # -- helpers -----------------------------------------------------

    def _say(self, action: CliffAction, reason: str) -> CliffAction:
        self._last_reason = f"{action.value}: {reason}"
        log.info("cliff: %s", self._last_reason)
        return action


class MockEdgeFeed:
    """Stand-in for the (unbuilt) floor-vs-edge detector. Feed it a list of
    `EdgeReading`s (or (present, dist, bearing[, conf]) tuples); `read()` returns
    the next, repeating the last once exhausted."""

    def __init__(self, readings):
        self._r = [x if isinstance(x, EdgeReading) else EdgeReading(*x) for x in readings]
        self._i = 0

    def read(self) -> EdgeReading:
        r = self._r[min(self._i, len(self._r) - 1)]
        self._i += 1
        return r


# action -> ordered OpenCat serial commands (caller waits between; a keyframe
# skill takes ~1-2 s). Turn / back-up tokens come from the HARDWARE-GATED config.
def action_commands(action: CliffAction, cfg: CliffGuardConfig | None = None) -> list[str]:
    cfg = cfg or CliffGuardConfig()
    return {
        CliffAction.NONE: [],
        CliffAction.SLOW: [],                       # caller scales the fwd speed cmd
        CliffAction.STOP: [opencat.BALANCE],
        CliffAction.TURN_AWAY_LEFT: [cfg.turn_left_token],
        CliffAction.TURN_AWAY_RIGHT: [cfg.turn_right_token],
        CliffAction.BACK_UP: [cfg.backup_token],
        CliffAction.FREEZE: [opencat.BALANCE],      # caller also: beep, notify, stop the loop
    }[action]


ACTION_SPEED_SCALE = {
    CliffAction.NONE: 1.0,
    CliffAction.SLOW: CliffGuardConfig.creep_speed_scale,
    CliffAction.STOP: 0.0,
    CliffAction.TURN_AWAY_LEFT: 0.0,
    CliffAction.TURN_AWAY_RIGHT: 0.0,
    CliffAction.BACK_UP: 0.0,
    CliffAction.FREEZE: 0.0,
}
