"""Explore mode -- G2 wanders, and investigates whatever's new.

Pure logic, same shape as `vision/avoidance.py`: a detection `Frame` + a clock
in, an `ExploreDecision` out. The caller maps the decision onto skills (walk /
turn / check_around) and onto expressive cues, and runs an obstacle reflex
(`Avoider` / terrain feature) underneath -- this module only decides *intent*.

Behaviour is shaped by `BehaviorParams` (from the personality), so "curious"
makes it linger on finds, range wider, and actually approach a new object
instead of only turning to look.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..personality.traits import BehaviorParams
from ..vision.feed import Frame
from .novelty import Novelty


class ExploreAction(Enum):
    WANDER = "wander"            # keep walking the current leg
    TURN = "turn"               # start a new leg on a fresh heading
    APPROACH = "approach"       # a novel thing is off to one side -- go toward it
    INVESTIGATE = "investigate"  # hold and look at the thing
    HOLD = "hold"               # brief pause (between legs)


@dataclass
class ExploreDecision:
    action: ExploreAction
    turn: float = 0.0    # radians, desired heading change for TURN/APPROACH (+ = right)
    target: str = ""     # label being investigated / approached, if any
    reason: str = ""


@dataclass
class ExploreConfig:
    fov_half_rad: float = 0.55    # camera half-FOV -> detection bearing from center_x
    centered_rad: float = 0.15    # |bearing| under this = "close enough, just look"
    near_area: float = 0.16       # detection box area at/above which it's close enough to investigate
    min_area: float = 0.004       # ignore specks
    min_conf: float = 0.35
    hold_secs: float = 0.6        # pause between legs


class Explorer:
    def __init__(self, params: BehaviorParams, novelty: Novelty,
                 cfg: ExploreConfig | None = None):
        self.p = params
        self.nov = novelty
        self.cfg = cfg or ExploreConfig()
        self._leg_start: float | None = None
        self._investigate_until: float = 0.0
        self._hold_until: float = 0.0
        self._target = ""

    def reset(self) -> None:
        self._leg_start = None
        self._investigate_until = 0.0
        self._hold_until = 0.0
        self._target = ""

    def _bearing(self, det) -> float:
        return (det.center_x - 0.5) * 2.0 * self.cfg.fov_half_rad

    def _most_novel(self, frame: Frame, now: float):
        best, best_area = None, 0.0
        for d in frame:
            if d.confidence < self.cfg.min_conf or d.area < self.cfg.min_area:
                continue
            if not self.nov.is_novel_object(d.label, now):
                continue
            if d.area > best_area:
                best, best_area = d, d.area
        return best

    def decide(self, frame: Frame, now: float) -> ExploreDecision:
        # 1. mid-investigation: hold until the dwell timer runs out
        if now < self._investigate_until:
            return ExploreDecision(ExploreAction.INVESTIGATE, target=self._target,
                                   reason="dwelling")
        if self._target:                       # dwell just ended
            self.nov.see_object(self._target, now)
            self._target = ""
            self._hold_until = now + self.cfg.hold_secs
            self._leg_start = None              # force a fresh heading after a find

        # 2. brief pause between legs
        if now < self._hold_until:
            return ExploreDecision(ExploreAction.HOLD, reason="pause")

        # 3. something new in view?
        det = self._most_novel(frame, now)
        if det is not None:
            bearing = self._bearing(det)
            close = det.area >= self.cfg.near_area
            centered = abs(bearing) <= self.cfg.centered_rad
            if self.p.approach_novelty and not (close and centered):
                return ExploreDecision(ExploreAction.APPROACH, turn=bearing,
                                       target=det.label, reason="approach novelty")
            # just look: orient if needed, then start the dwell
            self._target = det.label
            self._investigate_until = now + self.p.investigate_secs
            return ExploreDecision(ExploreAction.INVESTIGATE, turn=bearing,
                                   target=det.label, reason="found novelty")

        # 4. nothing new -- wander. New leg when the current one is spent.
        if self._leg_start is None:
            self._leg_start = now
            heading = self.nov.stalest_heading(now)
            self.nov.see_heading(heading, now)
            turn = heading * self.p.wander_turn_bias
            return ExploreDecision(ExploreAction.TURN, turn=turn, reason="new leg")
        if now - self._leg_start >= self.p.explore_leg_secs:
            self._leg_start = None
            return ExploreDecision(ExploreAction.HOLD, reason="leg done")
        return ExploreDecision(ExploreAction.WANDER, reason="on leg")
