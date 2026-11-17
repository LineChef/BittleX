#!/usr/bin/env python3
"""Keep the best pictures of ONE class under a cap (2026-11-17, owner-approved pruning of the green ball set).

    python tools/curate_class.py FOLDER [--cap 250] [--protect session_] [--apply]

Dry run by default: it scores every picture in FOLDER and writes a report; nothing moves. `--apply` MOVES the pictures that did not make the cut (with their `.json` notes) to `~/Desktop/G2Memory/_pruned/<class>_<date>/` (outside every class folder),
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
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pi_pipeline.vision import picture_score as ps  # noqa: E402
from pi_pipeline.vision.picture_score import choose as _choose  # noqa: E402,F401

DIST_BIN_IN, BEARING_BIN_DEG, DEDUP_HAMMING = ps.DIST_BIN_IN, ps.BEARING_BIN_DEG, ps.DEDUP_HAMMING


def score_one(path: str, need_ball: bool = True) -> dict:
    out = {"file": os.path.basename(path), "ok": False, "why": "", "quality": 0.0}
    try:
        jpeg = open(path, "rb").read()
    except Exception:  # noqa: BLE001
        out["why"] = "unreadable"
        return out
    m = ps.measure(jpeg)
    if m is None:
        out["why"] = "unreadable"
        return out
    out.update(m)
    out["why"] = ps.reject_reason(m)
    ball = None
    if not out["why"]:
        from pi_pipeline.vision import ball_finder as bf
        ball = bf.find_ball_or_color(jpeg, None)
        if ball is not None:
            out["dist_in"], out["bearing_deg"] = round(ball.distance_in, 1), round(ball.bearing_deg, 1)
        elif need_ball:
            out["why"] = "no ball found"
    out["quality"] = ps.quality(m, ball is not None)
    out["ok"] = not out["why"]
    return out


def choose(rows: list, cap: int, protect: tuple = ("session_",), dedup: int = DEDUP_HAMMING, protected_names=()) -> tuple[list, dict]:
    pn = set(protected_names)
    return ps.choose(rows, cap, protected=lambda n: n.startswith(protect) or n in pn, dedup=dedup)


def hand_named(folder: str) -> set:
    """Pictures a person named or promoted by hand (their sidecar says named_by "hand"): never trimmed."""
    out = set()
    for f in os.listdir(folder):
        if f.endswith(".json"):
            try:
                if json.load(open(os.path.join(folder, f))).get("named_by") == "hand":
                    out.add(os.path.splitext(f)[0] + ".jpg")
            except Exception:  # noqa: BLE001
                pass
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder", nargs="?", help="a class folder; or use --all-promoted")
    ap.add_argument("--all-promoted", action="store_true", help="every class folder under training_data/exploration/promoted with more pictures than the cap (the nightly pass): hand-named pictures are never trimmed")
    ap.add_argument("--cap", type=int, default=250)
    ap.add_argument("--protect", action="append", default=None)
    ap.add_argument("--no-need-ball", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default=None)
    ap.add_argument("--aside", default=None, help="where the dropped pictures go (default ~/Desktop/G2Memory/_pruned/<class>_<date>)")
    a = ap.parse_args()
    if a.all_promoted:
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "training_data", "exploration", "promoted")
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d) and not name.startswith("_") and len([f for f in os.listdir(d) if f.lower().endswith((".jpg", ".jpeg"))]) > a.cap:
                subprocess.run([sys.executable, os.path.abspath(__file__), d, "--cap", str(a.cap)] + (["--apply"] if a.apply else []), check=False)
        return
    if not a.folder:
        ap.error("give a class folder or --all-promoted")
    folder = os.path.abspath(os.path.expanduser(a.folder))
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg")))
    rows = [score_one(os.path.join(folder, f), not a.no_need_ball) for f in files]
    kept, dropped = choose(rows, a.cap, tuple(a.protect or ["session_"]), protected_names=hand_named(folder))
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
        dest = os.path.expanduser(a.aside or os.path.join("~/Desktop/G2Memory/_pruned", os.path.basename(folder) + time.strftime("_%Y%m%d")))      # OUTSIDE the class folders: the gallery reads every folder under promoted/ as a class
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
