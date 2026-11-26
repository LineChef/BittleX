#!/usr/bin/env python3
"""Rough check of a 2 inch puck calibration picture (puck-near set): is the puck where a 2 inch picture from a fully standing G2 should show it?

Measured by colour (a saturated blob on the floor part of the picture), not by the puck finder (which reads nothing this close). The ranges come from the one picture the owner accepted
(2026-11-26: width 36 px, height 30 px, base row 191, centre column 117) with room for the feet landing a little differently each time; they are rough on purpose.
Usage: python tools/g2_puck_check.py PICTURE.jpg [...]   (exit 1 when any picture is outside the ranges)"""
import sys

import numpy as np
from PIL import Image

WIDTH_PX = (28, 48)
BASE_ROW = (180, 199)
CENTRE_COL = (100, 135)


def measure(path) -> dict | None:
    im = np.asarray(Image.open(path).convert("RGB"), float) / 255
    mx, mn = im.max(2), im.min(2)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    m = (sat > 0.38) & (mx > 0.3)
    m[:110] = False
    m[212:] = False
    cols = m.sum(0)
    if cols.max() < 3:
        return None
    c0 = int(np.argmax(np.convolve(cols, np.ones(9), "same")))
    lo = hi = c0
    while lo > 0 and cols[lo - 1] >= 3:
        lo -= 1
    while hi < len(cols) - 1 and cols[hi + 1] >= 3:
        hi += 1
    rr = np.nonzero(m[:, lo:hi + 1].sum(1) >= 3)[0]
    return {"width": hi - lo + 1, "height": int(rr.max() - rr.min() + 1), "base_row": int(rr.max()), "centre_col": (lo + hi) // 2}


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
