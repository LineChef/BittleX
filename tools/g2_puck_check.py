#!/usr/bin/env python3
"""Rough check of a 2 inch puck calibration picture (puck-near set): is the puck where a 2 inch picture from a fully standing G2 should show it?

Measured by colour (a saturated blob on the floor part of the picture), not by the puck finder (which reads nothing this close). The ranges come from the one picture the owner accepted
(2026-11-26: width 36 px, height 30 px, base row 191, centre column 117) with room for the feet landing a little differently each time; they are rough on purpose.
Usage: python tools/g2_puck_check.py PICTURE.jpg [...]   (exit 1 when any picture is outside the ranges)"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pi_pipeline.vision import puck_close as pc

WIDTH_PX = pc.WIDTH_PX
BASE_ROW = (pc.PICK_ROW - pc.ROW_TOL_PX - 4, 199)
CENTRE_COL = (pc.PICK_COL - 18, pc.PICK_COL + 17)


def measure(path) -> dict | None:
    r = pc.find_close_array(np.asarray(Image.open(path).convert("RGB")))
    if r is None:
        return None
    return {"width": r.width_px, "height": r.height_px, "base_row": r.base_row, "centre_col": r.centre_col}


def check(path) -> tuple[bool, str]:
    r = measure(path)
    if r is None:
        return False, "no puck blob found"
    bad = [f"{k} {r[v]} outside {rng}" for k, v, rng in (("width", "width", WIDTH_PX), ("base row", "base_row", BASE_ROW), ("centre column", "centre_col", CENTRE_COL)) if not rng[0] <= r[v] <= rng[1]]
    return (not bad), (f"width {r['width']} px, base row {r['base_row']}, centre column {r['centre_col']}" + ("" if not bad else "  OUT: " + "; ".join(bad)))


def main(argv=None) -> int:
    bad = 0
    for p in (argv if argv is not None else sys.argv[1:]):
        ok, why = check(p)
        print(("FITS  " if ok else "OUT   ") + p.split("/")[-1] + "  " + why)
        bad += 0 if ok else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
