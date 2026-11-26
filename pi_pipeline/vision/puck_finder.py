"""Find the puck (the cylinder the basket goal throws) on the floor in a claw-camera picture: its bearing and a distance from the claw tip (the basket goal, docs/plan-detail/basket-goal-plan.md).

Why not by its band colours (`object_finder.find_cylinder`): tried on the 16 recognition pictures of the puck on the hardwood (2026-11-23) the two-band colour rule found it in only 7, with false hits on the cluttered wall (a bearing of -22 degrees every time) and missed it at 6 and 9 inches.
The floor is grey and the puck is the one strongly coloured thing on it, so this finds the biggest SATURATED blob on the floor part of the picture (below the wall's base, above the jaws, away from the side edges), the right size and shape for a puck, and not inside the tub's footprint (a puck inside the tub is read by `find_puck_in_tub_array` from a close picture).
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
TOP_ROW_CLAW_DOWN = 84                       # a claw-down picture sees the floor further out (the puck at the wall's base, about 25 inches, sits at row 91): the floor part starts higher there
BLOB_SAT_MEAN_MIN, BLOB_SAT_P90_MIN = 0.40, 0.50   # the blob's own colour: the puck is strongly saturated (mean 0.42 to 0.54 and 90th percentile 0.55 to 0.70 over the recognition pictures), the hardwood's glare and grain are not (mean 0.33 to 0.39, 90th percentile 0.35 to 0.46 over the false blobs of 2026-11-23)
BLUE_REJECT = 8.0                           # a blob whose mean blue exceeds both red and green by this much is the basket's blue tape, not the puck
FAR_ZONE_IN = 24.0                          # the puck seen above row 94 in a claw-down picture is at least this far
MIN_WIDTH_RATIO = 0.4                       # by row: a blob narrower than this fraction of the width its row predicts (WIDTH_K / distance) is a speck, not the puck (a 4 pixel false blob at a row that means 6 inches)
WIDTH_K = 95.0                             # the other reading, for a picture with the claw DOWN (the row means another distance there): distance = WIDTH_K / the blob's width in pixels (14, 11, 9 pixels at 6, 9, 12 inches, face-on); good to about 15 percent inside 12 inches
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
    clipped: bool = False       # the blob runs down to the picture's lowest floor row: the puck is at the claw tip, partly hidden by the jaws, so its width and row understate how near it is


def distance_from_row(row: float) -> float:
    return ROW_K / (row - ROW_HORIZON_PX) if row > ROW_HORIZON_PX + 1 else float("inf")


def _inside(basket, x: float, y: float, margin: float = 6.0) -> bool:
    """Is the blob's centre inside the tub's footprint (the basket finder's `in_footprint`)? Those blobs are a puck in the tub, read by `find_puck_in_tub_array`, not a puck on the floor. `margin` is unused: the footprint's own margins say where the tub's edge is."""
    from .basket_finder import in_footprint
    return in_footprint(basket, x, y)


def _on_tape(basket, x: float, y: float, pad: float = 4.0) -> bool:
    """Is the blob's centre on the tub's red tape (its rows, its columns, a few pixels around)? The tape's red ends can pass the puck's colour test (a 48 pixel blob on the tape's left end read as a puck 45 inches out in the off-centre 8 inch picture)."""
    if basket is None or getattr(basket, "right", 0) <= getattr(basket, "left", 0):
        return False
    return basket.left - pad <= x <= basket.right + pad and basket.rim_row - basket.height_px - pad <= y <= basket.rim_row + pad


def find_puck_array(rgb: np.ndarray, basket=None, by: str = "row") -> PuckReading | None:
    """The puck in a decoded picture, or None. `basket`: the basket finder's reading in the same picture (a BasketReading or None); blobs inside its box are the basket, not the puck. `by`: "row" for a picture taken with the claw
    raised to 120 in the attention pose (the fit above), "width" for a quick picture with the claw down."""
    a = rgb.astype(float)
    mx, mn = a.max(2), a.min(2)
    sat = (mx - mn) / (mx + 1)
    m = (sat > SAT_MIN) & (mx > VALUE_MIN)
    m[:(TOP_ROW_CLAW_DOWN if by == "width" else TOP_ROW), :] = False
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
        if _inside(basket, cx, cy) or _on_tape(basket, cx, cy):
            continue
        blob_sat = sat[ys, xs]
        if float(blob_sat.mean()) < BLOB_SAT_MEAN_MIN or float(np.percentile(blob_sat, 90)) < BLOB_SAT_P90_MIN:
            continue                                                                   # glare or grain on the hardwood, not the puck's colour
        mean_rgb = a[ys, xs].mean(0)
        if mean_rgb[2] - max(mean_rgb[0], mean_rgb[1]) > BLUE_REJECT:
            continue                                                                   # blue: the new basket's tape (2026-11-26), never the puck (red, green and yellow bands)
        if by != "width" and w < MIN_WIDTH_RATIO * WIDTH_K / max(distance_from_row(cy), 1.0):
            continue                                                                   # a speck far smaller than a puck at that row's distance
        if best is None or n > best[0]:
            best = (n, cx, cy, w, h, bool(ys.max() >= BOTTOM_ROW - 1))
    if best is None:
        return None
    n, cx, cy, w, h, clipped = best
    dist = WIDTH_K / max(w, 1) if by == "width" else distance_from_row(cy)
    if by == "width" and cy < TOP_ROW:
        dist = max(dist, FAR_ZONE_IN)                                                  # in the extra rows a claw-down picture adds, the puck is far, whatever a speck merged with the wall's base makes of its width
    return PuckReading(cx, cy, w, h, n, math.degrees(math.atan2(cx - rgb.shape[1] / 2, BEARING_FOCAL_PX)), dist, clipped)


def find_puck(jpeg: bytes, basket=None, by: str = "row") -> PuckReading | None:
    rgb = _decode(jpeg)
    return None if rgb is None else find_puck_array(rgb, basket, by)


INSIDE_SAT_MIN = 45                          # a pixel inside the tub counts when its max-minus-min channel spread is above this (the floor seen through the clear walls is grey). 2026-11-24 first run on G2: a puck inside read a spread of at most 52 in a darker picture, so the first 55 missed it; at 45 the empty and outside cases hold 0 to 2 such pixels (the past case 2) and every puck inside 25 or more (the far wall 35, the dark run 25)
MIN_INSIDE_PX = 8                            # the puck inside the tub: at least this many such pixels in one blob (8 against 0 to 2 for no puck, 25 or more with one: a margin both ways)
INSIDE_SIDE_COLS = 5                         # the window reaches this far outside the tape's ends and this far under the base, so a blob's centre is read whole
INSIDE_BELOW_ROWS = 30


INSIDE_MIN_SIDE_PX = 3                      # a puck inside the tub is at least this many pixels each way (a sliver 14 by 1 and one 1 by 8 were read as pucks inside on 2026-11-25: a glint or a tape edge)
INSIDE_ASPECT = (0.4, 2.6)                  # the blob's width over its height: 0.6 to 1.7 on the calibration pictures
INSIDE_WIDTH_RATIO = (0.04, 0.28)          # the blob's width over the tape's width: a puck's size follows the tub's at any distance (0.06 to 0.19 on the calibration pictures, 0.10 on the 16 by 16 pixel make)


@dataclass(frozen=True)
class PuckInTub:
    x: float
    y: float
    count: int                  # the blob's coloured pixels
    width_px: int
    height_px: int


def find_puck_in_tub_array(rgb: np.ndarray, basket) -> PuckInTub | None:
    """A coloured blob INSIDE the tub in a close picture (about 8 to 10 inches, the attention pose, the claw at 120), or None. `basket`: the basket finder's reading in the same picture. The blob is read whole in a window around the tub and counted only when its centre is in the footprint
    (`basket_finder.in_footprint`): a puck on the floor touching the tub's wall or its near side has its centre outside it. At 16 inches a puck inside is 0 to 5 such pixels and cannot be told from an empty tub; this is for the close look."""
    from .basket_finder import in_footprint
    if basket is None or getattr(basket, "right", 0) <= getattr(basket, "left", 0):
        return None
    a = rgb.astype(np.int16)
    spread = a.max(2) - a.min(2)
    m = spread > INSIDE_SAT_MIN
    h, w = m.shape
    y0, y1 = max(int(basket.rim_row) + 3, 0), min(int(basket.base_row) + INSIDE_BELOW_ROWS, h - 24)
    x0, x1 = max(basket.left - INSIDE_SIDE_COLS, 0), min(basket.right + INSIDE_SIDE_COLS + 1, w)
    win = np.zeros_like(m)
    win[y0:y1, x0:x1] = m[y0:y1, x0:x1]
    best = None
    for ys, xs in _blobs(win):
        n = len(xs)
        if n < MIN_INSIDE_PX:
            continue
        cx, cy = float(xs.mean()), float(ys.mean())
        if not in_footprint(basket, cx, cy):
            continue
        bw, bh = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        tape = float(getattr(basket, "width_px", 0) or 0)
        if min(bw, bh) < INSIDE_MIN_SIDE_PX or not INSIDE_ASPECT[0] <= bw / bh <= INSIDE_ASPECT[1]:
            continue                                                       # a sliver: not a puck
        if tape > 0 and not INSIDE_WIDTH_RATIO[0] <= bw / tape <= INSIDE_WIDTH_RATIO[1]:
            continue                                                       # the wrong size for this tub at this distance
        if best is None or n > best[0]:
            best = (n, cx, cy, bw, bh)
    if best is None:
        return None
    n, cx, cy, bw, bh = best
    return PuckInTub(cx, cy, n, bw, bh)


def find_puck_in_tub(jpeg: bytes, basket) -> PuckInTub | None:
    rgb = _decode(jpeg)
    return None if rgb is None else find_puck_in_tub_array(rgb, basket)
