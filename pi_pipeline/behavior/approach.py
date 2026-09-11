"""'Come here' -- a directed, finite walk toward a person.

Distinct from Tier 1 roam (`explore.py`, which wanders) and from Tier 0 attention
(`attentive.py`, which never walks). `ApproachTarget` is armed by the voice
command "come here", walks toward the largest matching detection, and **stops
when close** (or gives up if it loses sight for a while). One-shot: it disarms
itself when it arrives or gives up.

Pure logic -- a frame + a clock in, a list of `Effect`s out
(`WALK` / `STOP` / `HEAD` / `CHIRP`). Same floor-only / supervised contract as
Tier 1: the operator only says "come here" when G2 is on the floor.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .chirps import ChirpMood


@dataclass
class ApproachConfig:
    fov_half_rad: float = 0.55       # camera half-FOV -> bearing from center_x
    close_area: float = 0.22       # detection box area at/above which "close enough" -> stop
    min_conf: float = 0.35
    min_area: float = 0.004
    give_up_s: float = 6.0         # no sighting for this long -> stop + give up
    labels: tuple = ("person", "face")


class ApproachTarget:
    def __init__(self, cfg: ApproachConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or ApproachConfig()
        self._clock = clock
        self._active = False
        self._last_seen = 0.0
        self._reason = "idle"

    @property
    def active(self) -> bool:
        return self._active

    @property
    def last_reason(self) -> str:
        return self._reason

    def start(self, now: float | None = None) -> None:
        self._active = True
        self._last_seen = self._clock() if now is None else now
        self._reason = "coming"

    def cancel(self) -> None:
        self._active = False
        self._reason = "cancelled"

    def _target(self, frame):
        best, best_area = None, 0.0
        for d in frame:
            if getattr(d, "label", "") not in self.cfg.labels:
                continue
            if d.confidence < self.cfg.min_conf or d.area < self.cfg.min_area:
                continue
            if d.area > best_area:
                best, best_area = d, d.area
        return best

    def decide(self, frame, now: float | None = None) -> list:
        """One tick while active. Emits WALK toward the target, STOP + a happy
        chirp on arrival, or STOP + a confused chirp on give-up (then disarms)."""
        from .driver import Effect, EffectKind   # lazy: driver imports us
        if not self._active:
            return []
        now = self._clock() if now is None else now
        t = self._target(list(frame or []))

        if t is None:
            if now - self._last_seen >= self.cfg.give_up_s:
                self._active = False
                self._reason = "gave up -- lost sight"
                return [Effect(EffectKind.STOP, None, "come here: lost you"),
                        Effect(EffectKind.CHIRP, ChirpMood.CONFUSED, "where'd you go?")]
            self._reason = "looking for you"
            return [Effect(EffectKind.STOP, None, "come here: scanning"),
                    Effect(EffectKind.HEAD, "pan_sweep", "look for you")]

        self._last_seen = now
        if t.area >= self.cfg.close_area:
            self._active = False
            self._reason = "arrived"
            return [Effect(EffectKind.STOP, None, "come here: arrived"),
                    Effect(EffectKind.CHIRP, ChirpMood.HAPPY, "here I am")]

        bearing = (t.center_x - 0.5) * 2.0 * self.cfg.fov_half_rad
        self._reason = "walking to you"
        return [Effect(EffectKind.WALK, float(bearing), "come here: approach")]
