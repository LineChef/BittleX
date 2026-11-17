#!/usr/bin/env python3
"""Keep the best pictures of ONE class under a cap (2026-11-17, owner-approved pruning of the green ball set).

    python tools/curate_class.py FOLDER [--cap 250] [--protect session_] [--apply]

Dry run by default: it scores every picture in FOLDER and writes a report; nothing moves. `--apply` MOVES the pictures that did not make the cut (with their `.json` notes) into `FOLDER/../_pruned/<name>/`,
never deletes them, so every step is undoable by moving them back.

A picture scores on its own quality (brightness, contrast, sharpness: `tools/curate_captures.py`), on whether the ball finder sees the ball in it, and on how well it fills a gap in the set. The cut:
  1. pictures whose name starts with a `--protect` prefix (the structured capture sessions) are always kept;
  2. too dark, blown out, blurry or flat pictures, and (with `--need-ball`, the default) pictures where the finder does not see the ball, are dropped as rejects;
  3. near-identical pictures (average-hash distance) are collapsed to the best one;
  4. what is left is spread over bins of distance and bearing, the best pictures of each bin first, until the cap is reached.
The same ranking is what a "keep the best, replace the worst" rule needs: a new picture is scored the same way and replaces the lowest-scoring kept one only if it scores higher.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import curate_captures as cc  # noqa: E402

DIST_BIN_IN = 4.0
BEARING_BIN_DEG = 10.0
DEDUP_HAMMING = 6
MIN_BRIGHT, MAX_BRIGHT, MIN_CONTRAST, MIN_SHARP = 40.0, 215.0, 18.0, 20.0


def score_one(path: str, need_ball: bool = True) -> dict:
    out = {"file": os.path.basename(path), "ok": False, "why": "", "quality": 0.0}
    try:
        im = Image.open(path).convert("RGB")
        jpeg = open(path, "rb").read()
    except Exception:  # noqa: BLE001
        out["why"] = "unreadable"
        return out
    mean, contrast = cc.brightness_contrast(im)
    sharp = cc.sharpness(im)
    out.update(mean=round(float(mean), 1), contrast=round(float(contrast), 1), sharp=round(float(sharp), 1), hash=cc.ahash(im))
    if mean < MIN_BRIGHT:
        out["why"] = "dark"
    elif mean > MAX_BRIGHT:
        out["why"] = "blown"
    elif contrast < MIN_CONTRAST:
        out["why"] = "flat"
    elif sharp < MIN_SHARP:
        out["why"] = "blurry"
    ball = None
    if not out["why"]:
        from pi_pipeline.vision import ball_finder as bf
        ball = bf.find_ball_or_color(jpeg, None)
        if ball is not None:
            out["dist_in"], out["bearing_deg"] = round(ball.distance_in, 1), round(ball.bearing_deg, 1)
        elif need_ball:
            out["why"] = "no ball found"
    out["quality"] = round(min(sharp / 200.0, 1.0) * 0.5 + min(contrast / 60.0, 1.0) * 0.3 + (1.0 - abs(mean - 128.0) / 128.0) * 0.2 + (0.3 if ball is not None else 0.0), 3)
    out["ok"] = not out["why"]
    return out


def choose(rows: list, cap: int, protect: tuple = ("session_",), dedup: int = DEDUP_HAMMING) -> tuple[list, dict]:
    """(kept file names, {file: reason dropped}). Pure: takes the scored rows."""
    dropped: dict = {}
    kept = [r["file"] for r in rows if r["file"].startswith(protect)]                   # always kept, whatever their score
    for r in rows:
        if not r["ok"] and not r["file"].startswith(protect):
            dropped[r["file"]] = r["why"]
    pool = sorted((r for r in rows if r["ok"] and not r["file"].startswith(protect)), key=lambda r: -r["quality"])
    uniq = []
    for r in pool:                                                              # best first: a later near-twin is the one dropped
        if any(cc.hamming(r["hash"], u["hash"]) <= dedup for u in uniq):
            dropped[r["file"]] = "near-duplicate"
        else:
            uniq.append(r)
    room = max(0, cap - len(kept))
    bins: dict = {}
    for r in uniq:
        key = (int(r.get("dist_in", 0) // DIST_BIN_IN), int((r.get("bearing_deg", 0) + 90) // BEARING_BIN_DEG))
        bins.setdefault(key, []).append(r)
    order = []
    depth = 0
    while len(order) < len(uniq):                                               # round-robin over the bins, the best of each bin first
        for key in sorted(bins):
            if depth < len(bins[key]):
                order.append(bins[key][depth])
        depth += 1
    for r in order[:room]:
        kept.append(r["file"])
    for r in order[room:]:
        dropped[r["file"]] = "over the cap (a better one fills the bin)"
    return kept, dropped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--cap", type=int, default=250)
    ap.add_argument("--protect", action="append", default=None)
    ap.add_argument("--no-need-ball", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    folder = os.path.abspath(os.path.expanduser(a.folder))
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg")))
    rows = [score_one(os.path.join(folder, f), not a.no_need_ball) for f in files]
    kept, dropped = choose(rows, a.cap, tuple(a.protect or ["session_"]))
    reasons: dict = {}
    for why in dropped.values():
        reasons[why] = reasons.get(why, 0) + 1
    print(f"{folder}: {len(files)} pictures -> keep {len(kept)}, drop {len(dropped)} (cap {a.cap})")
    for why, n in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"   dropped {n}: {why}")
    ds = [r["dist_in"] for r in rows if r.get("dist_in") is not None and r["file"] in set(kept)]
    if ds:
        print(f"   kept distances (in): min {min(ds):.0f}, median {float(np.median(ds)):.0f}, max {max(ds):.0f}; kept beyond 24 in: {sum(1 for d in ds if d > 24)}")
    if a.report:
        with open(a.report, "w") as f:
            json.dump({"kept": kept, "dropped": dropped, "rows": [{k: v for k, v in r.items() if k != "hash"} for r in rows]}, f, indent=1)
        print(f"   report: {a.report}")
    if a.apply:
        dest = os.path.join(os.path.dirname(folder), "_pruned", os.path.basename(folder))
        os.makedirs(dest, exist_ok=True)
        for name in dropped:
            for ext in ("", ):
                src = os.path.join(folder, name)
                if os.path.exists(src):
                    shutil.move(src, os.path.join(dest, name))
            side = os.path.join(folder, os.path.splitext(name)[0] + ".json")
            if os.path.exists(side):
                shutil.move(side, os.path.join(dest, os.path.basename(side)))
        print(f"   moved {len(dropped)} pictures to {dest} (nothing deleted)")
    else:
        print("   dry run: nothing moved (add --apply to move the dropped ones aside)")


if __name__ == "__main__":
    main()
