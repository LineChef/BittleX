#!/usr/bin/env python3
"""Fill in YOLO box labels for a slow-pan capture from a few hand-drawn keyframes.

For a class nothing auto-detects (the `ledge`), you don't have to box every
frame. Because the capture is a slow, roughly-linear pan, box the object on a
handful of frames (every ~8-15) in any labeller, then this interpolates a box
onto every frame in between (and carries the nearest keyframe's box past the
ends). Review + nudge the outliers afterwards.

  # 1. curate the capture -> pos_*.jpg with NO .txt
  # 2. in Roboflow / SenseCraft, box ~1 in 10 frames, export YOLO .txt next to the jpgs
  # 3. fill the gaps:
  python tools/interp_labels.py ~/Desktop/g2_capture_raw/ledge/session_1/curated --class-id 2
  # 4. spot-check the frames it flags as far from a keyframe, then g2promote

Each keyframe .txt is one line `<cls> cx cy w h` (normalised). Multi-box frames
are passed through untouched (interpolation only makes sense for one moving box).
"""
from __future__ import annotations

import argparse
import glob
import os
import sys


def _read(txt: str):
    try:
        rows = [ln.split() for ln in open(txt) if ln.strip()]
    except OSError:
        return None
    if len(rows) != 1 or len(rows[0]) != 5:
        return "multi"                      # leave alone
    return [float(x) for x in rows[0][1:]]  # cx cy w h


def _lerp(a, b, t):
    return [x + (y - x) * t for x, y in zip(a, b)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="folder of pos_*.jpg with a few keyframe .txt files")
    ap.add_argument("--class-id", type=int, required=True, help="class id to write")
    ap.add_argument("--flag-gap", type=int, default=12,
                    help="warn about frames more than this many away from a keyframe")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    jpgs = sorted(glob.glob(os.path.join(a.folder, "pos_*.jpg"))) \
        or sorted(glob.glob(os.path.join(a.folder, "*.jpg")))
    if not jpgs:
        sys.exit(f"no images in {a.folder}")

    keys: list[tuple[int, list[float]]] = []
    multi = 0
    for i, j in enumerate(jpgs):
        box = _read(j[:-4] + ".txt")
        if box == "multi":
            multi += 1
        elif box:
            keys.append((i, box))
    if len(keys) < 2:
        sys.exit(f"need >=2 keyframe .txt files, found {len(keys)}. Box a few frames first.")

    print(f"{len(jpgs)} frames, {len(keys)} keyframes"
          + (f", {multi} multi-box frames left as-is" if multi else ""))

    written = flagged = 0
    for i, j in enumerate(jpgs):
        txt = j[:-4] + ".txt"
        existing = _read(txt)
        if existing == "multi":
            continue
        # bracketing keyframes
        prev = max((k for k in keys if k[0] <= i), default=None)
        nxt = min((k for k in keys if k[0] >= i), default=None)
        if prev and nxt and prev[0] != nxt[0]:
            t = (i - prev[0]) / (nxt[0] - prev[0])
            box = _lerp(prev[1], nxt[1], t)
            gap = min(i - prev[0], nxt[0] - i)
        else:
            src = prev or nxt
            box = list(src[1])
            gap = abs(i - src[0])
        if gap > a.flag_gap:
            flagged += 1
        line = f"{a.class_id} " + " ".join(f"{v:.6f}" for v in box) + "\n"
        if not a.dry_run:
            open(txt, "w").write(line)
        written += 1

    print(f"{'would write' if a.dry_run else 'wrote'} {written} labels"
          f"  ({flagged} more than {a.flag_gap} frames from a keyframe -- spot-check those)")
    if not a.dry_run:
        print("next: eyeball the contact sheet / a labeller, nudge the drifted boxes, "
              "then g2promote")


if __name__ == "__main__":
    main()
