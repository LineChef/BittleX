"""Tier 0 explore -- the "attentive" layer. Stationary; no locomotion, ever.

This is what "explore mode" means when G2 is *not* armed to roam: it stays put
(sitting or resting) and expresses curiosity through attention --

  * turns toward a sound ("what was that?") -- vision or not
  * gaze-follows the nearest person, then *satiates*: after a while it drops to
    occasional glances instead of locking on, so it doesn't stare
  * reacts to something new in view -- a look, a peer bow, a curious chirp
  * every so often, a periodic head pan-scan as a life sign

It runs as a life-signs layer on top of `IdlePosture` (the driver calls it when
posture is holding steady), so G2 still settles down normally; this just keeps
it from looking switched-off while it does. Pure logic, same shape as
`explore.py` -- a frame + a clock in, a list of `Effect`s out, none of them
`WALK` / `TURN`.

`vision_available=False` -> only the sound reaction and the periodic scan run.
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
    follow_satiate_s: float = 8.0    # continuous follow past this -> glance mode
    follow_glance_cooldown_s: float = 4.0  # gap between glances once satiated
    follow_reengage_rad: float = 0.30  # person moves this far -> re-engage (reset satiation)
    sound_cooldown_s: float = 3.0    # min gap between sound reactions
    react_cooldown_s: float = 6.0    # min gap between novelty reactions
    scan_every_s: float = 45.0       # periodic look-around interval
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
        self._last_sound = -1e9
        self._last_scan = clock()       # first scan waits a full interval
        self._follow_since: float | None = None  # continuous-follow start (satiation)
        self._follow_bearing = 0.0
        self._reason = "init"

    @property
    def last_reason(self) -> str:
        return self._reason

    @property
    def satiated(self) -> bool:
        return (self._follow_since is not None
                and self._clock() - self._follow_since >= self.cfg.follow_satiate_s)

    def reset(self) -> None:
        self._last_follow = self._last_react = self._last_sound = -1e9
        self._last_scan = self._clock()
        self._follow_since = None
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
               person_present: bool = False, sound: bool = False,
               loud: bool = False, sound_bearing: float | None = None) -> list:
        """Effects for one idle tick. `resting` -> head-only, no body moves.
        `sound` = a nearby sound/motion cue; `loud` = a startling one;
        `sound_bearing` = where it came from (rad, + = right), or None."""
        from .driver import Effect, EffectKind   # lazy: driver imports us
        now = self._clock() if now is None else now
        frame = list(frame or [])

        # 1. a sound -- turn toward it. A loud one interrupts anything; a soft
        #    one loses to an active (un-satiated) gaze-follow.
        if (sound or loud) and (loud or now - self._last_sound >= self.cfg.sound_cooldown_s):
            following = self._follow_since is not None and not self.satiated
            if loud or not following:
                self._last_sound = now
                self._reason = "toward a " + ("loud sound" if loud else "sound")
                if sound_bearing is not None:
                    return [Effect(EffectKind.HEAD, float(sound_bearing),
                                   "toward a sound")]
                return [Effect(EffectKind.HEAD, "pan_sweep", "what was that?")]

        # 2. gaze-follow the nearest person -- with satiation
        if self._vision and frame:
            p = self._nearest_person(frame)
            if p is not None:
                b = self._bearing(p)
                # re-engage if they moved a lot, or start the follow timer
                if self._follow_since is None or \
                        abs(b - self._follow_bearing) >= self.cfg.follow_reengage_rad:
                    self._follow_since = now
                self._follow_bearing = b
                gap = (self.cfg.follow_glance_cooldown_s if self.satiated
                       else self.cfg.follow_cooldown_s)
                if abs(b) >= self.cfg.follow_deadband_rad and now - self._last_follow >= gap:
                    self._last_follow = now
                    self._reason = "glance at a person" if self.satiated else "gaze-follow a person"
                    return [Effect(EffectKind.HEAD, float(b), "follow person")]
            else:
                self._follow_since = None      # person left view -> reset satiation
        else:
            self._follow_since = None

        # 3. react to something new in view
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

        # 4. periodic look-around -- a life sign even with nothing happening
        if now - self._last_scan >= self.cfg.scan_every_s:
            self._last_scan = now
            self._reason = "periodic look-around"
            return [Effect(EffectKind.HEAD, "pan_sweep", "look-around")]

        self._reason = "attentive, nothing to do"
        return []
