"""The ball's tracking method for the active look (2026-11-17): the colour finder, the ball's own colour when the fixed rules miss it, and a motion fallback.

`BallTracker(color)` is a tracker in the sense of behavior/active_look.py: `tracker(jpeg, t_capture)` returns detections `(label, score, cx, cy, w, h)` in frame fractions.

1. The ball by the colour finder (`gallery_target.BallTarget`: the fixed green rules, then the ball's own colour sampled by the chase from close up when those find nothing).
2. Only if that finds nothing, and the follow's tracking filter has a recent track (two sightings or more), a MOTION candidate (vision/motion_detector.py) counts as a sighting when its bearing is within
   `MOTION_GATE_DEG` of where the filter expects the ball. With no track yet a moving blob is never accepted: motion alone is too noisy to start a track.

The tracker is bound to the follow (`bind`) so it can ask the claw's pan at the picture's capture time and the filter's prediction. No new library: numpy only.
"""
from __future__ import annotations

import logging

from ..vision.motion_detector import MotionDetector
from .gallery_target import BallTarget

log = logging.getLogger("g2.ball_tracker")

MOTION_GATE_DEG = 12.0            # a motion candidate this close to the predicted bearing may stand in for a missed colour sighting
MOTION_MIN_TRACK_N = 2            # the filter must have this many sightings before motion is trusted


class BallTracker:
    name = "ball"
    wants_capture_time = True

    def __init__(self, color=None, *, motion: bool = True, pan_sign: str = "left"):
        self.colour = BallTarget(color)
        self.motion = MotionDetector(pan_sign) if motion else None
        self.pan_log = None
        self.follower = None
        self.fov_half_deg = 44.0
        self.motion_sightings = 0         # colour misses that a motion candidate stood in for (for the journal)

    def bind(self, pan_log, follower, clock) -> None:
        self.pan_log, self.follower = pan_log, follower
        self.fov_half_deg = follower.cfg.fov_half_deg
        if self.motion is not None:
            self.motion.reset()

    def __call__(self, jpeg: bytes, t_capture: float | None = None) -> list:
        dets = self.colour.detections(jpeg)
        pan = self.pan_log.at(t_capture) if (self.pan_log is not None and t_capture is not None) else 0.0
        cand = self.motion.update(jpeg, pan) if self.motion is not None else []          # (always updated: it needs every picture to have the one before)
        if dets or not cand or self.follower is None or t_capture is None:
            return dets
        f = self.follower.filter
        if f.n < MOTION_MIN_TRACK_N:
            return dets
        pred = f.predict(t_capture)
        if pred is None:
            return dets
        best, best_err = None, MOTION_GATE_DEG
        for d in cand:
            err = abs(self.follower.world_bearing(t_capture, d) - pred)
            if err <= best_err:
                best, best_err = d, err
        if best is None:
            return dets
        self.motion_sightings += 1
        return [("ball", 0.3, best[2], best[3], best[4], best[5])]                       # a weaker sighting: label "ball", the follower treats it like any other
