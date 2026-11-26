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
TAPE_DIM = (130, 50, 45)             # the second try, when the strict seed finds no tape: the tape is paler in dim or washed light (it read 169, 103, 87 at 22 inches on 2026-11-25, red minus green 66, against 240, 115, 105 at calibration). On the 34 tub pictures it reads the same 34; on 163 pictures with no tub it added 2 false tubs to the strict test's 39 (mostly pictures of the old cup); on the 10 morning pictures it found the tub in 7
TAPE_LOOSE = (110, 40, 30)           # the same test for finding the tape's ends along its rows
BLUE_STRICT = (14, 55, 16)           # the new basket's BLUE tape (owner, 2026-11-26: red is too close to the puck's colour; the puck is red, green and yellow, never blue). A pixel is tape when blue exceeds the mean of red and green by the first, blue is at least the second and exceeds red by the third. The tape is dark and uneven in average light, about (79, 100, 126) on its bright side and (70, 90, 85) on its far side at 12 inches: a fixed difference from red failed on the dim side, blue over the other two together found the whole band on all 8 face-on distances (8 to 22 inches, `basket-blue`)
BLUE_LOOSE = (10, 50, 10)            # the same test for the tape's ends along its rows
BLUE_PURITY = 0.2                    # blue exceeds red by at least this fraction of blue: the tape is 0.37 (79, 100, 126), the pale blue-grey of the wall, the window and the sky is 0.11 to 0.17 (187, 201, 211 and 136, 148, 159 on the saved negatives)
BLUE_K, BLUE_C = 409.0, 3.91         # claw tip to the tub's centre in inches = BLUE_K / the tape's width in pixels + BLUE_C (least squares over the 8 face-on distances and 3 of the 4 off-centre pictures: within 1.5 inches everywhere; the owner's distances run from the claw tip to the tub's centre). A first fit: to be checked against the pictures still to come
BLUE_MIN_ROW = 67                    # the blue band's bottom row. 104 to 114 in the first session's 12 pictures, 82 to 87 in the 10 tub-at-8-inches pictures, but 71 to 75 for the tub 12 to 18 inches out in the 2026-11-26 goal run (the band rises as the tub goes back; the wall's base sits at row 70). 85 and then 82 hid every tub farther than about 9 inches. The grey-blue wall and sofa blobs end at rows 0 to 66 and are told from the tape by colour below
BLUE_BLOB_PURITY = 0.24              # the whole blue blob's mean (blue - red) / blue, at least this: the tape reads 0.26 to 0.39 (darker light gives the lower numbers), the pale pet bed and wall 0.22 to 0.26 but BRIGHT
BLUE_BLOB_MAX_BLUE = 140.0           # and its mean blue channel at most this: the tape is dark (78 to 126 over every tub picture), the pale grey-blue things 133 to 171
BLUE_MIN_ASPECT = 1.6                # the blue band is thicker than the red tape was: 3.1 to 1 at 8 inches, 3.3 at 16
MIN_SEED_PX = 30                     # the seed blob's size (50 pixels at 22 inches, about 300 at 8)
MIN_WIDTH_PX, MAX_WIDTH_PX = 20, 200
MIN_ASPECT = 3.5                     # width / height of the seed (the tape is 10 to 1 or thinner; the puck's red is about 1 to 2)
HORIZON_Y = 50                       # blobs above this row are not on the floor
FRAG_MIN_PX = 10                     # a thin piece of tape: at least this many strict pixels, thin and wide (below), and it can join its neighbours on the same rows into the seed
FRAG_MAX_H, FRAG_MIN_ASPECT = 4, 3.0
FRAG_ROW_TOL, FRAG_GAP_PX = 3.0, 12  # pieces whose rows differ by at most this and whose gap is at most this many columns are one strip of tape (2026-11-25: at about 24 inches the tape came as two pieces of 15 and 17 pixels with an 8 pixel gap, each too short to seed, and the look called it no basket with the tub right in front of him)
BAND_UP, BAND_DOWN = 4, 3            # the loose test looks on these rows around the seed's rows
MIN_COL_PX = 2                       # a column is tape when the loose test holds on this many of the band's rows
BASKET_IN = 5.0                      # the tub's width across (an estimate; the tape's width carries the distance)
LENS_OFFSET_IN = 2.0                 # the lens sits this far behind the claw tip (owner, 2026-11-22)
BEARING_FOCAL_PX = 140.0             # horizontal focal length in pixels
TUB_K = 1050.0                       # lens distance in inches = TUB_K / the tape's width in pixels (fitted 2026-11-24, see the module docstring)
BLUE_BASE_RATIO = 0.53               # the blue-banded tub is deeper than the red-taped one was: its base sat 34 to 35 rows under the band's bottom at a band 62 to 65 wide (the 10 tub pictures of 2026-11-26, the base read by eye from the pictures)
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
    blue: bool = False          # read from the blue band (the clear tub of 2026-11-26), not the red tape


def distance_from_width(width_px: float) -> float:
    """Lens distance in inches from the tape's width: TUB_K / width (inf for a width of zero or less). The claw tip distance is this minus LENS_OFFSET_IN."""
    return TUB_K / width_px if width_px > 0 else float("inf")


def _tape_mask(rgb: np.ndarray, thr: tuple, blue: bool = False) -> np.ndarray:
    r, g, b = rgb[..., 0].astype(int), rgb[..., 1].astype(int), rgb[..., 2].astype(int)
    if blue:
        return ((b - (r + g) / 2) > thr[0]) & (b > thr[1]) & (b - r > thr[2]) & ((b - r) > BLUE_PURITY * b)
    return (r > thr[0]) & (r - g > thr[1]) & (r - b > thr[2])


def _tape_groups(blobs) -> list:
    """The strict-red blobs as (ys, xs), with thin wide pieces of tape on the same rows (within FRAG_ROW_TOL rows, FRAG_GAP_PX columns apart) joined into one strip. Anything else stays as it is, so a puck's red is never joined to the tape."""
    out, frags = [], []
    for ys, xs in blobs:
        bw, bh = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        if len(xs) >= FRAG_MIN_PX and bh <= FRAG_MAX_H and bw / bh >= FRAG_MIN_ASPECT:
            frags.append((ys, xs))
        else:
            out.append((ys, xs))
    frags.sort(key=lambda f: int(f[1].min()))
    groups: list = []
    for ys, xs in frags:
        for g in groups:
            gy = np.concatenate([y for y, _x in g])
            gx = np.concatenate([x for _y, x in g])
            if abs(float(ys.mean()) - float(gy.mean())) <= FRAG_ROW_TOL and (int(xs.min()) - int(gx.max()) <= FRAG_GAP_PX) and (int(gx.min()) - int(xs.max()) <= FRAG_GAP_PX):
                g.append((ys, xs))
                break
        else:
            groups.append([(ys, xs)])
    for g in groups:
        out.append((np.concatenate([y for y, _x in g]), np.concatenate([x for _y, x in g])))
    return out


def find_basket_array(rgb: np.ndarray) -> BasketReading | None:
    """The tub in a picture: the strict tape test first (the calibrated colour: every reading it gave is unchanged), and only when that finds no tape the dimmer test (TAPE_DIM), under the same shape rules (a thin wide strip)."""
    return _find_basket(rgb, TAPE_STRICT) or _find_basket(rgb, TAPE_DIM) or _find_basket(rgb, BLUE_STRICT, blue=True)


def _find_basket(rgb: np.ndarray, seed_thr: tuple, blue: bool = False) -> BasketReading | None:
    h, w_img = rgb.shape[:2]
    m = _tape_mask(rgb, seed_thr, blue)
    m[h - IGNORE_BOTTOM_PX:, :] = False
    m[:HORIZON_Y, :] = False
    best = None
    for ys, xs in _tape_groups(_blobs(m)):
        n = len(xs)
        if n < MIN_SEED_PX:
            continue
        bw, bh = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        if blue and int(ys.max()) < BLUE_MIN_ROW:
            continue                                                     # a grey-blue sofa or wall up the picture, not tape on the floor
        if blue:
            mean = rgb[ys, xs].astype(float).mean(0)
            if (mean[2] - mean[0]) / max(mean[2], 1.0) < BLUE_BLOB_PURITY or mean[2] > BLUE_BLOB_MAX_BLUE:
                continue                                                 # a pale grey-blue pet bed or sofa: the tape is dark and deep blue (purity 0.31 to 0.39 over 14 tub pictures), those read 0.22 to 0.26 and are bright
        if bw < MIN_WIDTH_PX or bw / bh < (BLUE_MIN_ASPECT if blue else MIN_ASPECT):
            continue
        if best is None or n > best[0]:
            best = (n, xs, ys, bw, bh)
    if best is None:
        return None
    _, xs, ys, bw, bh = best
    top, bottom = int(ys.min()), int(ys.max())
    loose = _tape_mask(rgb, BLUE_LOOSE if blue else TAPE_LOOSE, blue)
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
    lens = (BLUE_K / width + BLUE_C + LENS_OFFSET_IN) if blue else distance_from_width(width)
    edge = bool(left <= 0 or right >= w_img - 1)
    return BasketReading(cx, cy, width, bh, math.degrees(math.atan2(cx - w_img / 2, BEARING_FOCAL_PX)), lens, lens - LENS_OFFSET_IN, edge,
                         left, right, float(bottom), float(bottom + (BLUE_BASE_RATIO if blue else BASE_RATIO) * width), blue)


def in_footprint(basket: BasketReading | None, x: float, y: float) -> bool:
    """Is the point (a blob's centre) inside the tub, between the tape's ends (less FOOT_MARGIN_X) and between the rim and the base (less FOOT_TOP and FOOT_BOTTOM)? One test for both puck finders: the floor puck finder ignores what is inside it, the in-tub finder reads only what is."""
    if basket is None or basket.right <= basket.left:
        return False
    return (basket.left + FOOT_MARGIN_X <= x <= basket.right - FOOT_MARGIN_X) and (basket.rim_row + FOOT_TOP <= y <= basket.base_row - FOOT_BOTTOM)


def find_basket(jpeg: bytes) -> BasketReading | None:
    rgb = _decode(jpeg)
    return None if rgb is None else find_basket_array(rgb)
