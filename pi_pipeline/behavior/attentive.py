"""Tier 0 explore -- the "attentive" layer. Stationary; no locomotion, ever.

This is what "explore mode" means when G2 is *not* armed to roam: it stays put
(sitting or resting) and expresses curiosity through attention --

  * gaze-follows the nearest person with its head/body
  * reacts to something new in view -- a look, a peer bow, a curious chirp
  * every so often, a periodic head pan-scan as a life sign

It runs as a life-signs layer on top of `IdlePosture` (the driver calls it when
posture is holding steady), so G2 still settles down normally; this just keeps
it from looking switched-off while it does. Pure logic, same shape as
`explore.py` -- a frame + a clock in, a list of `Effect`s out, none of them
`WALK` / `TURN`.

`vision_available=False` -> only the periodic scan runs (it needs no camera).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .chirps import ChirpMood
from .gestures import GESTURE_TOKEN, Gesture
from .novelty import Novelty


@dataclass
class AttentiveConfig:
    fov_half_rad: float = 0.55        # camera half-FOV -> bearing from center_x
    follow_cooldown_s: float = 0.5    # min gap between gaze-follow head moves
    follow_deadband_rad: float = 0.08  # ignore tiny bearing changes
    react_cooldown_s: float = 6.0     # min gap between novelty reactions
    scan_every_s: float = 45.0        # periodic look-around interval
    person_labels: tuple = ("person", "face")
    min_conf: float = 0.35
    min_area: float = 0.004


class AttentiveLook:
    def __init__(self, novelty: Novelty, cfg: AttentiveConfig | None = None, *,
                 clock=time.monotonic, vision_available: bool = True):
        self.nov = novelty
        self.cfg = cfg or AttentiveConfig()
        self._clock = clock
        self._vision = bool(vision_available)
        self._last_follow = -1e9
        self._last_react = -1e9
        self._last_scan = clock()      # first scan waits a full interval
        self._reason = "init"

    @property
    def last_reason(self) -> str:
        return self._reason

    def reset(self) -> None:
        self._last_follow = self._last_react = -1e9
        self._last_scan = self._clock()
        self._reason = "reset"

    def _bearing(self, det) -> float:
        return (det.center_x - 0.5) * 2.0 * self.cfg.fov_half_rad

    def _nearest_person(self, frame):
        best, best_area = None, 0.0
        for d in frame:
            if getattr(d, "label", "") not in self.cfg.person_labels:
                continue
            if d.confidence < self.cfg.min_conf or d.area < self.cfg.min_area:
                continue
            if d.area > best_area:
                best, best_area = d, d.area
        return best

    def _novel_object(self, frame, now: float):
        best, best_area = None, 0.0
        for d in frame:
            lab = getattr(d, "label", "")
            if not lab or lab in self.cfg.person_labels:
                continue
            if d.confidence < self.cfg.min_conf or d.area < self.cfg.min_area:
                continue
            if not self.nov.is_novel_object(lab, now):
                continue
            if d.area > best_area:
                best, best_area = d, d.area
        return best

    def decide(self, frame, *, resting: bool, now: float | None = None,
               person_present: bool = False) -> list:
        """Effects for one idle tick. `resting` -> head-only, no body moves."""
        from .driver import Effect, EffectKind   # lazy: driver imports us
        now = self._clock() if now is None else now
        frame = list(frame or [])

        # 1. gaze-follow the nearest person (takes precedence)
        if self._vision and frame and now - self._last_follow >= self.cfg.follow_cooldown_s:
            p = self._nearest_person(frame)
            if p is not None:
                b = self._bearing(p)
                if abs(b) >= self.cfg.follow_deadband_rad:
                    self._last_follow = now
                    self._reason = "gaze-follow a person"
                    return [Effect(EffectKind.HEAD, float(b), "follow person")]

        # 2. react to something new in view
        if self._vision and frame and now - self._last_react >= self.cfg.react_cooldown_s:
            d = self._novel_object(frame, now)
            if d is not None:
                self._last_react = now
                self.nov.see_object(d.label, now)
                self._reason = f"noticed {d.label}"
                fx = [Effect(EffectKind.HEAD, float(self._bearing(d)), f"look at {d.label}")]
                if not resting:
                    fx.append(Effect(EffectKind.SKILL, GESTURE_TOKEN[Gesture.PLAY_BOW],
                                     f"peer at {d.label}"))
                fx.append(Effect(EffectKind.CHIRP, ChirpMood.QUESTION, f"curious: {d.label}"))
                return fx

        # 3. periodic look-around -- a life sign even with nothing happening
        if now - self._last_scan >= self.cfg.scan_every_s:
            self._last_scan = now
            self._reason = "periodic look-around"
            return [Effect(EffectKind.HEAD, "pan_sweep", "look-around")]

        self._reason = "attentive, nothing to do"
        return []
