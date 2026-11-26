"""The puck at the pick-up spot (the basket goal's last step): where it sits in a claw-down picture when the claw can take it.

`puck_finder.find_puck` cannot read a puck this near (it drops any blob wider than 26 pixels and any below row 200: at the pick-up spot the puck is about 40 pixels wide and its base sits near row 192). This reads it by colour, whatever face is toward the camera
(a loose saturation test: the red, green and yellow faces differ a lot), and says how far it is from the spot the owner's four 2 inch calibration pictures (2026-11-26, the `puck-near` set, one per quarter turn) put it.
The spot: base row 191 to 196 (mean 192), centre column 115 to 120, width 38 to 46 pixels. G2 stood a little differently after each stand-up (the base row of the same face spread 183 to 196), so the tolerances are rough on purpose."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .ball_finder import _decode

SAT_MIN, VALUE_MIN = 0.22, 0.25          # a pixel counts when its saturation and brightest channel (0 to 1) are at least this
TOP_ROW, BOTTOM_ROW = 140, 212           # the floor rows the puck at the pick-up spot can occupy (the jaw tip is near row 205)
PICK_ROW, PICK_COL = 192, 118            # where the puck's base and centre sit at the pick-up spot
ROW_TOL_PX, COL_TOL_PX = 8, 10
WIDTH_PX = (30, 52)
FOCAL_PX = 140.0                         # the same horizontal focal length the finders use for a bearing


@dataclass(frozen=True)
class CloseReading:
    width_px: int
    height_px: int
    base_row: int
    centre_col: int

    @property
    def col_err_px(self) -> int:
        return self.centre_col - PICK_COL            # + = the puck is right of the spot

    @property
    def row_err_px(self) -> int:
        return self.base_row - PICK_ROW              # + = nearer than the spot (lower in the picture), - = farther

    @property
    def bearing_err_deg(self) -> float:
        return math.degrees(math.atan2(self.col_err_px, FOCAL_PX))

    @property
    def at_spot(self) -> bool:
        return abs(self.col_err_px) <= COL_TOL_PX and abs(self.row_err_px) <= ROW_TOL_PX and WIDTH_PX[0] <= self.width_px <= WIDTH_PX[1]


def find_close_array(rgb: np.ndarray) -> CloseReading | None:
    """The puck near the pick-up spot in a decoded picture, or None (nothing wide and coloured on the near floor rows)."""
    im = rgb.astype(float) / 255.0
    mx, mn = im.max(2), im.min(2)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    m = (sat > SAT_MIN) & (mx > VALUE_MIN)
    m[:TOP_ROW] = False
    m[BOTTOM_ROW:] = False
    cols = m.sum(0)
    if cols.max() < 3:
        return None
    c0 = int(np.argmax(np.convolve(cols, np.ones(9), "same")))
    lo = hi = c0
    while lo > 0 and cols[lo - 1] >= 3:
        lo -= 1
    while hi < len(cols) - 1 and cols[hi + 1] >= 3:
        hi += 1
    rows = np.nonzero(m[:, lo:hi + 1].sum(1) >= 3)[0]
    if len(rows) == 0:
        return None
    return CloseReading(int(hi - lo + 1), int(rows.max() - rows.min() + 1), int(rows.max()), int((lo + hi) // 2))


def find_close(jpeg: bytes) -> CloseReading | None:
    rgb = _decode(jpeg)
    return None if rgb is None else find_close_array(rgb)
