"""Find a MOVING blob in the camera's pictures, whatever its colour (2026-11-17, owner-approved: a pale ball in poor light is missed by the colour finder but still moves).

The claw pans while it follows, so the whole picture shifts between two pictures. `MotionDetector.update(jpeg, pan_deg)` shifts the previous picture by the pan between them (about 2.7 px per
degree: the measured field of view is about 89 degrees across 240 px), subtracts it from the new one, and returns the compact blobs that remain. Numpy only.

A frame difference shows a mover twice (where it was and where it is), and a change of exposure lights up the whole picture, so the result is a CANDIDATE list, never a decision: a tracker accepts one
only near where its tracking filter expects the target (`behavior/ball_tracker.py`), and a picture where most of the frame changed (the exposure swung) gives no candidates at all.
"""
from __future__ import annotations

import numpy as np

from . import ball_finder as bf

PX_PER_DEG = 240.0 / 89.0         # the measured field of view (full about 89 degrees) over the 240 px frame
DIFF_THRESHOLD = 18               # grey levels a pixel must change to count as moving
MAX_CHANGED_SHARE = 0.20          # more of the frame than this changed: an exposure swing or a bump, not a mover
MIN_AREA, MAX_AREA = 20, 2500     # px, a blob's size
MIN_FILL = 0.35                   # blob pixels over its bounding box: a compact blob, not a streak


class MotionDetector:
    def __init__(self, pan_sign: str = "left", *, px_per_deg: float = PX_PER_DEG, threshold: int = DIFF_THRESHOLD):
        self.sign = pan_sign              # which way a positive pan turns the camera: "left" (G2) = the scene shifts RIGHT in the picture when the pan increases
        self.ppd, self.thr = px_per_deg, threshold
        self._prev: np.ndarray | None = None
        self._pan: float | None = None
        self.last_changed_share = 0.0

    def reset(self) -> None:
        self._prev, self._pan = None, None

    def update(self, jpeg: bytes, pan_deg: float) -> list:
        """Candidates as (label, score, cx, cy, w, h) in frame fractions (label "motion"), the larger first; [] when there is no earlier picture, the exposure swung, or nothing moved."""
        rgb = bf._decode(jpeg)
        if rgb is None or rgb.ndim != 3:
            return []
        gray = rgb.mean(axis=2)
        prev, prev_pan = self._prev, self._pan
        self._prev, self._pan = gray, float(pan_deg)
        if prev is None or prev.shape != gray.shape:
            return []
        h, w = gray.shape
        dx = int(round((pan_deg - prev_pan) * self.ppd * (1 if self.sign == "left" else -1)))      # pixels the scene moved sideways between the two pictures
        dx = max(-w // 3, min(w // 3, dx))
        shifted = np.roll(prev, dx, axis=1)
        diff = np.abs(gray - shifted) > self.thr
        if dx > 0:
            diff[:, :dx] = False                                      # columns that wrapped around have no earlier picture
        elif dx < 0:
            diff[:, dx:] = False
        diff[h - bf.IGNORE_BOTTOM_PX:, :] = False
        self.last_changed_share = float(diff.mean())
        if self.last_changed_share > MAX_CHANGED_SHARE:
            return []
        out = []
        for ys, xs in bf._blobs(bf._shift_and(diff)):                 # one erosion step first: single changed pixels are noise
            n = len(xs)
            if not MIN_AREA <= n <= MAX_AREA:
                continue
            bw, bh = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
            if n / float(bw * bh) < MIN_FILL or not 0.3 <= bw / bh <= 3.3:
                continue
            out.append(("motion", min(1.0, n / 200.0), float(xs.mean()) / w, float(ys.mean()) / h, bw / w, bh / h, n))
        out.sort(key=lambda d: -d[6])
        return [d[:6] for d in out]
