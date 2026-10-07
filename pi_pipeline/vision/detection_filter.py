"""Fewer false cats and dogs: a filter between the camera's detections and everything that reacts to them (the narrator, the explorer).

The camera model is small and has no score cutoff of its own. In the kitchen it read floor texture as a cat (a box over the whole floor view, score 0.9) and a dog
(a low flat box, 0.54). Animal classes (`cat`, `dog` by default) are therefore dropped unless ALL of these hold; every other class (people, faces) passes untouched:
  1. score at least `min_score` (0.60);
  2. a plausible shape: the box is not most of the frame (area, width) and not a flat wide strip (width / height), which is what a patch of floor looks like;
  3. the same label is seen in `confirm_frames` (3) consecutive frames, so a one-frame flicker never counts.
Every animal detection that is kept or dropped can be logged (throttled, JSON lines, `~/g2_runs/detections/<date>.jsonl`) so the rules can be tuned on real data."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("g2.detection_filter")


@dataclass
class FilterConfig:
    animal_labels: tuple = ("cat", "dog")
    min_score: float = 0.60
    confirm_frames: int = 3
    max_area: float = 0.55           # share of the frame; a real animal this close would be a few centimetres from the lens
    max_width: float = 0.90
    max_aspect: float = 2.6          # width / height; a floor strip is far wider than an animal is long


class DetectionLog:
    """Append-only JSON lines of animal detections, at most one line per second per (label, outcome). Never raises."""

    def __init__(self, folder=None, clock=time.time, per_s: float = 1.0):
        self._dir = Path(os.path.expanduser(folder or os.environ.get("G2_DETECTION_LOG_DIR", "~/g2_runs/detections")))
        self._clock, self._per_s = clock, per_s
        self._last: dict = {}
        self.enabled = os.environ.get("G2_DETECTION_LOG", "on").strip().lower() not in ("off", "0", "false", "no")

    def __call__(self, outcome: str, det, reason: str) -> None:
        if not self.enabled:
            return
        now = self._clock()
        key = (det.label, outcome)
        if now - self._last.get(key, -1e9) < self._per_s:
            return
        self._last[key] = now
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "label": det.label, "score": round(det.confidence, 3), "outcome": outcome, "reason": reason,
                   "x": round(det.x, 3), "y": round(det.y, 3), "w": round(det.w, 3), "h": round(det.h, 3)}
            with open(self._dir / (time.strftime("%Y%m%d", time.localtime(now)) + ".jsonl"), "a") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            log.debug("could not write the detection log", exc_info=True)


class AnimalDetectionFilter:
    def __init__(self, cfg: FilterConfig | None = None, *, on_event=None):
        self.cfg = cfg or FilterConfig()
        self._animals = {a.lower() for a in self.cfg.animal_labels}
        self._run: dict[str, int] = {}                      # label -> consecutive frames it has passed the shape and score rules
        self._on_event = on_event                           # (outcome, detection, reason); a DetectionLog

    @classmethod
    def from_settings(cls, s, *, on_event=None):
        labels = tuple(x.strip().lower() for x in str(s.vision_animal_labels).split(",") if x.strip())
        return cls(FilterConfig(animal_labels=labels, min_score=s.vision_animal_min_score / 100.0, confirm_frames=int(s.vision_animal_confirm_frames)), on_event=on_event)

    def reject_reason(self, d) -> str:
        c = self.cfg
        if d.confidence < c.min_score:
            return f"score {d.confidence:.2f} below {c.min_score:.2f}"
        if d.w * d.h > c.max_area or d.w > c.max_width:
            return "box covers most of the frame (floor or a wall, not an animal)"
        if d.h > 0 and d.w / d.h > c.max_aspect:
            return "flat wide box (a strip of floor)"
        return ""

    def __call__(self, frame):
        out, candidates = [], []
        for d in frame:
            if d.label.lower() not in self._animals:
                out.append(d)                                # people, faces and anything else: untouched
                continue
            why = self.reject_reason(d)
            if why:
                self._note("dropped", d, why)
            else:
                candidates.append(d)
        present = {d.label.lower() for d in candidates}
        for label in present:
            self._run[label] = self._run.get(label, 0) + 1   # one more frame in a row (however many boxes of it this frame has)
        for label in list(self._run):
            if label not in present:
                self._run[label] = 0                         # a frame without it breaks the run
        for d in candidates:
            n = self._run[d.label.lower()]
            if n >= self.cfg.confirm_frames:
                out.append(d)
                self._note("kept", d, f"seen in {n} frames in a row")
            else:
                self._note("dropped", d, f"seen in {n} of {self.cfg.confirm_frames} frames so far")
        return out

    def _note(self, outcome, det, reason) -> None:
        if self._on_event is not None:
            try:
                self._on_event(outcome, det, reason)
            except Exception:  # noqa: BLE001
                log.debug("detection log failed", exc_info=True)
