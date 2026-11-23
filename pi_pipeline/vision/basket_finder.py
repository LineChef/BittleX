"""Find the basket in a claw-camera picture: its bearing and its distance (the basket goal, docs/plan-detail/basket-goal-plan.md).

The basket is a pale orange circular cup 5 inches across. It is found by colour (`object_finder`, a tight colour tolerance, the biggest blob that is the right size and shape), then:
- the bearing from the blob's centre column (a horizontal focal length of about 140 pixels, measured from the pictures with the basket 6 inches left and right);
- the distance from the blob's width: distance from the claw tip = CLAW_K / width in pixels, fitted (2026-11-23) to eight pictures with the claw at lift 120 and the basket 12, 14, 15, 16, 17, 18, 20 and 22 inches from the claw tip (the tape started at the tip). It lands within 0.6 inch of the measured distance at all eight; a second constant did not improve it. The lens sits LENS_OFFSET_IN behind the claw tip, so the lens distance is the tip distance plus that.
The fit covers 12 to 22 inches in the attention pose with the claw at 120 and has no pictures beyond it (the earlier pictures at 24, 30 and 36 inches were not part of this fit: expect it to read long out there). The pose after a pick-up was not measured. Nothing here moves G2, calls an API or needs a download.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .object_finder import ObjectSpec, _color_mask
from .ball_finder import IGNORE_BOTTOM_PX, _blobs, _decode, _shift_and, _shift_or

BASKET_RGB = (223, 164, 141)         # the cup's pale orange, the median of its colour over the five distance pictures
BASKET_TOL = 0.03                    # normalized red and green share
BASKET_IN = 5.0                      # its width across
LENS_OFFSET_IN = 2.0                 # the lens sits this far behind the claw tip (owner, 2026-11-22)
BEARING_FOCAL_PX = 140.0             # horizontal focal length in pixels
CLAW_K = 731.0                       # distance from the claw tip in inches = CLAW_K / width in pixels (fitted 2026-11-23, see the module docstring)
MIN_BLOB_PX, MIN_WIDTH_PX, MAX_WIDTH_PX = 60, 15, 150      # 150 px is about 5 inches from the claw tip: a closer basket still reads (2026-11-23: past 90 px it was dropped and the retrieval walked into it)
HORIZON_Y = 50                       # blobs above this row are not on the floor
ASPECT = (0.45, 1.9)                 # height / width of the blob (the cup, its shadow and its reflection on the floor)
SPEC = ObjectSpec("basket", BASKET_RGB, BASKET_IN, min_area=MIN_BLOB_PX, tol=BASKET_TOL)


@dataclass(frozen=True)
class BasketReading:
    x: float
    y: float
    width_px: int
    height_px: int
    bearing_deg: float          # + = to G2's right
    lens_in: float              # distance from the lens
    claw_in: float              # distance from the claw tip (lens distance minus the 2 in offset): what the throw is measured from
    touches_edge: bool          # cut off by the frame: width and distance are low


def distance_from_width(width_px: float) -> float:
    """Lens distance in inches from the blob's width: the fitted distance from the claw tip plus the lens offset (inf for a width of zero or less)."""
    return CLAW_K / width_px + LENS_OFFSET_IN if width_px > 0 else float("inf")


def find_basket_array(rgb: np.ndarray) -> BasketReading | None:
    m = _color_mask(rgb, SPEC.color, SPEC.tol)
    m[rgb.shape[0] - IGNORE_BOTTOM_PX:, :] = False
    m[:HORIZON_Y, :] = False
    for _ in range(2):
        m = _shift_or(m)
    for _ in range(2):
        m = _shift_and(m)
    best = None
    for ys, xs in _blobs(m):
        if len(xs) < MIN_BLOB_PX:
            continue
        w, h = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        if not MIN_WIDTH_PX <= w <= MAX_WIDTH_PX or not ASPECT[0] <= h / w <= ASPECT[1]:
            continue
        if best is None or len(xs) > best[0]:
            best = (len(xs), xs, ys, w, h)
    if best is None:
        return None
    _, xs, ys, w, h = best
    cx, cy = float(xs.mean()), float(ys.mean())
    lens = distance_from_width(w)
    edge = bool(xs.min() == 0 or xs.max() == rgb.shape[1] - 1)
    return BasketReading(cx, cy, w, h, math.degrees(math.atan2(cx - rgb.shape[1] / 2, BEARING_FOCAL_PX)), lens, lens - LENS_OFFSET_IN, edge)


def find_basket(jpeg: bytes) -> BasketReading | None:
    rgb = _decode(jpeg)
    return None if rgb is None else find_basket_array(rgb)
