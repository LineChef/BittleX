"""Find the basket in a claw-camera picture: its bearing and its distance (the basket goal, docs/plan-detail/basket-goal-plan.md).

The basket is a clear shallow tub with a band of red tape along its rim (owner, 2026-11-24; the old pale orange cup is gone: its finder read nothing on the tub). The tape is the cue: a wide, thin, strongly red blob (about 10 to 1 at 8 inches, 15 to 1 at 22). The pictures that fitted this are the `tub` recognition set
(16 and 8 inch series; docs/vision/picture-library.md), taken in the attention pose with the claw at lift 120:
- the seed is the biggest strictly red blob of that shape (TAPE_STRICT); the tape's ends are then found with a looser red test (TAPE_LOOSE) on the rows around the seed, because the strict colour thins out on the far side of the tape (its width read 41, 37, 34, 27 and 31 pixels at 17 to 22 inches, the loose test 55, 52, 47, 47 and 43);
- the bearing from the tape's centre column (a horizontal focal length of about 140 pixels);
- the distance: LENS distance = TUB_K / the tape's width in pixels (width times lens distance was 1034 to 1148 from 12 to 22 inches and 890 at 8: TUB_K 1050 reads within about 2 inches over the whole range, 1.8 long at 8, 1.2 short at 12, and within 0.6 from 14 to 22; PROVISIONAL, refit when more pictures exist). The claw tip distance is the lens distance minus LENS_OFFSET_IN (the lens sits that far behind the tip).
- the tub's footprint for the puck finders: the tape's left and right columns, the rim row (the tape's bottom row) and the base row, BASE_RATIO times the tape's width under it (the tub's base sat 24 to 26 rows under the rim at 8 inches, a width of 89 pixels).
Valid from 8 to about 22 inches in that pose; the pose after a pick-up was not measured. Nothing here moves G2, calls an API or needs a download.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .ball_finder import IGNORE_BOTTOM_PX, _blobs, _decode

TAPE_STRICT = (140, 70, 60)          # a pixel is tape when red is above the first and above green and blue by the others (the tape's core)
TAPE_LOOSE = (110, 40, 30)           # the same test for finding the tape's ends along its rows
MIN_SEED_PX = 30                     # the seed blob's size (50 pixels at 22 inches, about 300 at 8)
MIN_WIDTH_PX, MAX_WIDTH_PX = 20, 200
MIN_ASPECT = 3.5                     # width / height of the seed (the tape is 10 to 1 or thinner; the puck's red is about 1 to 2)
HORIZON_Y = 50                       # blobs above this row are not on the floor
BAND_UP, BAND_DOWN = 4, 3            # the loose test looks on these rows around the seed's rows
MIN_COL_PX = 2                       # a column is tape when the loose test holds on this many of the band's rows
BASKET_IN = 5.0                      # the tub's width across (an estimate; the tape's width carries the distance)
LENS_OFFSET_IN = 2.0                 # the lens sits this far behind the claw tip (owner, 2026-11-22)
BEARING_FOCAL_PX = 140.0             # horizontal focal length in pixels
TUB_K = 1050.0                       # lens distance in inches = TUB_K / the tape's width in pixels (fitted 2026-11-24, see the module docstring)
BASE_RATIO = 0.27                    # the base row sits this fraction of the tape's width under the rim row
FOOT_MARGIN_X = 10                   # the footprint starts this many columns inside the tape's ends: a puck touching the tub's outer wall sits on the tape's end column (80 against the tape's 80 at 8 inches), one inside against the wall 15 to 20 columns in
FOOT_TOP, FOOT_BOTTOM = 3, 3         # and from this many rows under the rim to this many above the base row: a puck on the floor against the near wall sat at row 131.7 against a base of 131, one inside against it at 122


@dataclass(frozen=True)
class BasketReading:
    x: float                    # the tape's centre column
    y: float                    # its centre row
    width_px: int               # the tape's width
    height_px: int              # the seed's height
    bearing_deg: float          # + = to G2's right
    lens_in: float              # distance from the lens
    claw_in: float              # distance from the claw tip (lens distance minus the lens offset): what the throw is measured from
    touches_edge: bool          # cut off by the frame: width and distance are low
    left: int = 0               # the tape's first and last column
    right: int = 0
    rim_row: float = 0.0        # the tape's bottom row
    base_row: float = 0.0       # where the tub's base is expected (rim row plus BASE_RATIO times the width)


def distance_from_width(width_px: float) -> float:
    """Lens distance in inches from the tape's width: TUB_K / width (inf for a width of zero or less). The claw tip distance is this minus LENS_OFFSET_IN."""
    return TUB_K / width_px if width_px > 0 else float("inf")


def _tape_mask(rgb: np.ndarray, thr: tuple) -> np.ndarray:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (r > thr[0]) & (r - g > thr[1]) & (r - b > thr[2])


def find_basket_array(rgb: np.ndarray) -> BasketReading | None:
    h, w_img = rgb.shape[:2]
    m = _tape_mask(rgb, TAPE_STRICT)
    m[h - IGNORE_BOTTOM_PX:, :] = False
    m[:HORIZON_Y, :] = False
    best = None
    for ys, xs in _blobs(m):
        n = len(xs)
        if n < MIN_SEED_PX:
            continue
        bw, bh = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        if bw < MIN_WIDTH_PX or bw / bh < MIN_ASPECT:
            continue
        if best is None or n > best[0]:
            best = (n, xs, ys, bw, bh)
    if best is None:
        return None
    _, xs, ys, bw, bh = best
    top, bottom = int(ys.min()), int(ys.max())
    loose = _tape_mask(rgb, TAPE_LOOSE)
    band = np.zeros_like(loose)
    r0, r1 = max(top - BAND_UP, 0), min(bottom + BAND_DOWN + 1, h)
    band[r0:r1, :] = loose[r0:r1, :]
    cols = set(np.nonzero(band.sum(0) >= MIN_COL_PX)[0].tolist())
    left, right = int(xs.min()), int(xs.max())
    while (left - 1) in cols or (left - 2) in cols:                      # a one column gap does not end the tape
        left -= 1
    while (right + 1) in cols or (right + 2) in cols:
        right += 1
    width = right - left + 1
    if not MIN_WIDTH_PX <= width <= MAX_WIDTH_PX:
        return None
    cx, cy = (left + right) / 2.0, (top + bottom) / 2.0
    lens = distance_from_width(width)
    edge = bool(left <= 0 or right >= w_img - 1)
    return BasketReading(cx, cy, width, bh, math.degrees(math.atan2(cx - w_img / 2, BEARING_FOCAL_PX)), lens, lens - LENS_OFFSET_IN, edge,
                         left, right, float(bottom), float(bottom + BASE_RATIO * width))


def in_footprint(basket: BasketReading | None, x: float, y: float) -> bool:
    """Is the point (a blob's centre) inside the tub, between the tape's ends (less FOOT_MARGIN_X) and between the rim and the base (less FOOT_TOP and FOOT_BOTTOM)? One test for both puck finders: the floor puck finder ignores what is inside it, the in-tub finder reads only what is."""
    if basket is None or basket.right <= basket.left:
        return False
    return (basket.left + FOOT_MARGIN_X <= x <= basket.right - FOOT_MARGIN_X) and (basket.rim_row + FOOT_TOP <= y <= basket.base_row - FOOT_BOTTOM)


def find_basket(jpeg: bytes) -> BasketReading | None:
    rgb = _decode(jpeg)
    return None if rgb is None else find_basket_array(rgb)
