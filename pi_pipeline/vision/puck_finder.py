"""Find the puck (the cylinder the basket goal throws) on the floor in a claw-camera picture: its bearing and a distance from the claw tip (the basket goal, docs/plan-detail/basket-goal-plan.md).

Why not by its band colours (`object_finder.find_cylinder`): tried on the 16 recognition pictures of the puck on the hardwood (2026-11-23) the two-band colour rule found it in only 7, with false hits on the cluttered wall (a bearing of -22 degrees every time) and missed it at 6 and 9 inches.
The floor is grey and the puck is the one strongly coloured thing on it, so this finds the biggest SATURATED blob on the floor part of the picture (below the wall's base, above the jaws, away from the side edges), the right size and shape for a puck, and not inside the basket's box.
- bearing: from the blob's centre column (the basket finder's horizontal focal length);
- distance from the claw tip: from the blob's centre ROW, as ROW_K / (row - ROW_HORIZON_PX): on the floor plane the row falls steadily with distance, which the puck's width (about 18 pixels at 6 inches, 4 at 24) cannot give. Fitted to the six face-on pictures at 6 to 24 inches with the claw at lift 120 in the attention pose; it is within about 15 percent there and is only valid in that pose.
Seen only out to about 24 inches, and reliably only inside about 15 (a 4 to 8 pixel speck beyond). Nothing here moves G2, calls an API or needs a download.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .ball_finder import _blobs, _decode

SAT_MIN, VALUE_MIN = 0.30, 100            # a pixel counts when its saturation and brightest channel are at least this (the floor and the wall are grey)
TOP_ROW, BOTTOM_ROW, EDGE_COLS = 94, 200, 12   # the floor part of a 240 x 240 picture: below the wall's base, above the jaws, away from the side edges
MIN_PX, MAX_SIDE_PX, MAX_ASPECT = 12, 26, 2.6  # the puck's blob: at least this many pixels, no side longer than this, not a long sliver
ROW_HORIZON_PX, ROW_K = 90.0, 275.0       # distance from the claw tip = ROW_K / (row - ROW_HORIZON_PX)
BEARING_FOCAL_PX = 140.0                   # the basket finder's horizontal focal length


@dataclass(frozen=True)
class PuckReading:
    x: float
    y: float
    width_px: int
    height_px: int
    area: int
    bearing_deg: float          # + = to G2's right
    claw_in: float              # distance from the claw tip along the floor (by the blob's row)


def distance_from_row(row: float) -> float:
    return ROW_K / (row - ROW_HORIZON_PX) if row > ROW_HORIZON_PX + 1 else float("inf")


def _inside(basket, x: float, y: float, margin: float = 6.0) -> bool:
    if basket is None:
        return False
    return abs(x - basket.x) <= basket.width_px / 2 + margin and abs(y - basket.y) <= basket.height_px / 2 + margin


def find_puck_array(rgb: np.ndarray, basket=None) -> PuckReading | None:
    """The puck in a decoded picture, or None. `basket`: the basket finder's reading in the same picture (a BasketReading or None); blobs inside its box are the basket, not the puck."""
    a = rgb.astype(float)
    mx, mn = a.max(2), a.min(2)
    m = ((mx - mn) / (mx + 1) > SAT_MIN) & (mx > VALUE_MIN)
    m[:TOP_ROW, :] = False
    m[BOTTOM_ROW:, :] = False
    m[:, :EDGE_COLS] = False
    m[:, -EDGE_COLS:] = False
    best = None
    for ys, xs in _blobs(m):
        n = len(xs)
        if n < MIN_PX:
            continue
        w, h = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        if max(w, h) > MAX_SIDE_PX or max(w / h, h / w) > MAX_ASPECT:
            continue
        cx, cy = float(xs.mean()), float(ys.mean())
        if _inside(basket, cx, cy):
            continue
        if best is None or n > best[0]:
            best = (n, cx, cy, w, h)
    if best is None:
        return None
    n, cx, cy, w, h = best
    return PuckReading(cx, cy, w, h, n, math.degrees(math.atan2(cx - rgb.shape[1] / 2, BEARING_FOCAL_PX)), distance_from_row(cy))


def find_puck(jpeg: bytes, basket=None) -> PuckReading | None:
    rgb = _decode(jpeg)
    return None if rgb is None else find_puck_array(rgb, basket)
