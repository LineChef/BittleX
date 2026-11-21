"""Find the cylinder and the basket in a camera picture by their own colours (the basket goal, docs/plan-detail/basket-goal-plan.md, steps 2 to 4).

The same idea as the ball finder's colour pass (`ball_finder.find_ball_color`), without its round-shape and green-dominance rules, so it works for a flat-sided basket and a banded cylinder: pixels whose red and green share of the light is close to
the reference colour's, bright enough, in the biggest blob. Distance comes from the blob's width and the object's real width (inches), through the focal length the ball's size constants give (`FOCAL_PX`, the camera sees a thing W inches
across as FOCAL_PX x W / D pixels at D inches); that number is a first guess to be calibrated with known-size placements at measured distances, like the wall calibration. Nothing here moves G2, calls an API or needs a download.
The colours and sizes are settings of the objects (`ObjectSpec`), not constants: the basket is the owner's choice and its colour is sampled from a picture of it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .ball_finder import BALL_IN, DIST_K, FRAME_PX, IGNORE_BOTTOM_PX, _blobs, _decode, _shift_and, _shift_or

FOCAL_PX = DIST_K / BALL_IN          # pixels per inch at one inch, from the ball's measured constant (330 px x in for a 3 in ball): 110
COLOR_TOL = 0.05                     # how far (normalized red and green share) a pixel may be from the reference colour
MIN_SUM = 120                        # r + g + b: darker pixels have no reliable colour
MIN_AREA = 40                        # px
HORIZON_Y = 60                       # a blob centred above this row is on the wall or beyond, not on the floor


@dataclass(frozen=True)
class ObjectSpec:
    """What to look for: `color` is the reference (r, g, b), `width_in` the object's real width across the picture, `min_area` the smallest blob that counts."""
    name: str
    color: tuple
    width_in: float
    min_area: int = MIN_AREA
    tol: float = COLOR_TOL


@dataclass(frozen=True)
class ObjectReading:
    name: str
    x: float                  # blob centre, px from the left (0..240)
    y: float
    left: int
    right: int
    top: int
    bottom: int
    area: int
    width_px: int
    distance_in: float        # from the camera, by the blob's width
    bearing_deg: float        # + = to G2's right, - = left (0 = straight ahead)
    touches_edge: bool        # cut off by the frame: width and distance are low estimates

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


def _color_mask(rgb: np.ndarray, ref: tuple, tol: float) -> np.ndarray:
    s = np.maximum(rgb.sum(axis=2), 1)
    t = max(sum(ref), 1)
    rs, gs = ref[0] / t, ref[1] / t
    return (np.abs(rgb[..., 0] / s - rs) <= tol) & (np.abs(rgb[..., 1] / s - gs) <= tol) & (s >= MIN_SUM)


def find_object_array(rgb: np.ndarray, spec: ObjectSpec) -> ObjectReading | None:
    """The biggest blob of the spec's colour in a decoded picture, or None. The bottom rows (the jaws, a foot, the frame's edge) and blobs centred above the horizon are ignored."""
    mask = _color_mask(rgb, spec.color, spec.tol)
    mask[rgb.shape[0] - IGNORE_BOTTOM_PX:, :] = False
    for _ in range(2):
        mask = _shift_or(mask)
    for _ in range(2):
        mask = _shift_and(mask)
    best = None
    for ys, xs in _blobs(mask):
        if len(xs) < spec.min_area:
            continue
        cy = float(ys.mean())
        if cy < HORIZON_Y:
            continue
        left, right, top, bottom = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        width = right - left + 1
        edge = left == 0 or right == rgb.shape[1] - 1
        dist = FOCAL_PX * spec.width_in / max(width, 1)
        cx = float(xs.mean())
        side_in = (cx - rgb.shape[1] / 2) * spec.width_in / max(width, 1)
        reading = ObjectReading(spec.name, cx, cy, left, right, top, bottom, int(len(xs)), width, dist, math.degrees(math.atan2(side_in, dist)), edge)
        if best is None or reading.area > best.area:
            best = reading
    return best


def find_object(jpeg: bytes, spec: ObjectSpec) -> ObjectReading | None:
    rgb = _decode(jpeg)
    return None if rgb is None else find_object_array(rgb, spec)


def find_cylinder_array(rgb: np.ndarray, bands: list, length_in: float, *, max_gap_px: float = 1.6) -> ObjectReading | None:
    """The banded cylinder: at least two of its band colours (`bands`, a list of ObjectSpec whose width_in is the band's) found in blobs that touch or nearly touch (their centres within `max_gap_px` times the bigger
    blob's size of each other). The reading is the group's bounding box, sized against the cylinder's whole `length_in`. A single band alone is not enough: a red cup is not the cylinder."""
    found = [r for r in (find_object_array(rgb, b) for b in bands) if r is not None]
    best = None
    for i, a in enumerate(found):
        group = [a]
        for b in found[i + 1:]:
            size = max(a.width_px, b.width_px, a.bottom - a.top + 1, b.bottom - b.top + 1)
            if math.hypot(a.x - b.x, a.y - b.y) <= max_gap_px * size:
                group.append(b)
        if len(group) < 2:
            continue
        left, right = min(g.left for g in group), max(g.right for g in group)
        top, bottom = min(g.top for g in group), max(g.bottom for g in group)
        width = max(right - left + 1, bottom - top + 1)                    # the long side: the cylinder lies either way
        cx, cy = (left + right) / 2, (top + bottom) / 2
        dist = FOCAL_PX * length_in / max(width, 1)
        side_in = (cx - rgb.shape[1] / 2) * length_in / max(width, 1)
        edge = left == 0 or right == rgb.shape[1] - 1
        area = sum(g.area for g in group)
        reading = ObjectReading("cylinder", cx, cy, left, right, top, bottom, area, width, dist, math.degrees(math.atan2(side_in, dist)), edge)
        if best is None or reading.area > best.area:
            best = reading
    return best


def find_cylinder(jpeg: bytes, bands: list, length_in: float) -> ObjectReading | None:
    rgb = _decode(jpeg)
    return None if rgb is None else find_cylinder_array(rgb, bands, length_in)


__all__ = ["FOCAL_PX", "FRAME_PX", "ObjectSpec", "ObjectReading", "find_object", "find_object_array", "find_cylinder", "find_cylinder_array"]
