#!/usr/bin/env python3
"""Diagnostic: run the on-device detector through aggressive post-filtering
(score floor + NMS + top-K) and see whether it yields stable, localized boxes
or planted background garbage.

    source pi_pipeline/.venv/bin/activate
    python tools/vision_diag.py /dev/cu.usbmodem58FA1045341 --secs 30

Point the camera at your face during the run.

Read-out:
  - if a box tracks your face and NO location is flagged PLANTED -> the camera
    firmware just wasn't running NMS; fixable in pi_pipeline/vision/feed.py.
  - if the same locations fire regardless of what's in frame (PLANTED) -> it's
    the training data (loose full-frame dog/cat boxes), and the fix is relabel.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pi_pipeline.config import settings
from pi_pipeline.vision.feed import SerialDetectionFeed


def _iou(a, b) -> float:
    ax1, ay1 = a.x + a.w, a.y + a.h
    bx1, by1 = b.x + b.w, b.y + b.h
    ix0, iy0 = max(a.x, b.x), max(a.y, b.y)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _nms(dets, iou_thr):
    keep = []
    for d in sorted(dets, key=lambda d: -d.confidence):
        if all(_iou(d, k) < iou_thr for k in keep):
            keep.append(d)
    return keep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("--secs", type=float, default=30.0)
    ap.add_argument("--score", type=float, default=0.75, help="min confidence, 0-1")
    ap.add_argument("--iou", type=float, default=0.45, help="NMS IoU threshold")
    ap.add_argument("--topk", type=int, default=3)
    a = ap.parse_args()

    feed = SerialDetectionFeed(
        a.port, settings.vision_serial_baud,
        frame_px=settings.vision_frame_px, labels=settings.vision_labels,
        sensor_opt=settings.vision_sensor_opt, ae_bump=settings.vision_ae_bump,
        min_score=0,
    )
    t0 = last = time.time()
    n = 0
    raw_counts: list[int] = []
    kept_counts: list[int] = []
    loc_hist: Counter = Counter()
    label_hist: Counter = Counter()
    print(f"filter: score>={a.score}  IoU<{a.iou}  top{a.topk}   -- point at your face\n")
    try:
        for frame in feed.frames():
            n += 1
            raw_counts.append(len(frame))
            kept = _nms([d for d in frame if d.confidence >= a.score], a.iou)[:a.topk]
            kept_counts.append(len(kept))
            for d in kept:
                cy = d.y + d.h / 2
                loc_hist[(d.label, round(d.center_x * 10), round(cy * 10))] += 1
                label_hist[d.label] += 1
            now = time.time()
            if now - last >= 1.0:
                last = now
                desc = "  ".join(
                    f"{d.label}:{d.confidence * 100:.0f}"
                    f"@({d.center_x:.2f},{d.y + d.h / 2:.2f})sz{d.area ** 0.5:.2f}"
                    for d in kept) or "(none)"
                print(f"  {now - t0:4.0f}s  raw{len(frame):2d} -> kept{len(kept)}   {desc}")
            if a.secs > 0 and now - t0 >= a.secs:
                break
    except KeyboardInterrupt:
        pass
    finally:
        feed.close()

    dur = time.time() - t0
    print(f"\n=== {n} frames / {dur:.0f}s ({n / max(dur, 1e-6):.1f} fps) ===")
    print(f"raw boxes/frame    mean {sum(raw_counts) / max(1, n):.1f}   max {max(raw_counts or [0])}")
    print(f"kept boxes/frame   mean {sum(kept_counts) / max(1, n):.1f}")
    print("labels kept        " + (", ".join(f"{k} x{v}" for k, v in label_hist.most_common()) or "(none)"))
    print("\npersistent kept-box locations  (label, cx, cy -> frames seen):")
    for (lab, cx, cy), cnt in loc_hist.most_common(8):
        pct = 100 * cnt / max(1, n)
        flag = "   <-- PLANTED (background overfit)" if pct > 60 else ""
        print(f"  {lab:6} ({cx / 10:.1f}, {cy / 10:.1f})   {cnt:4d}  {pct:3.0f}%{flag}")


if __name__ == "__main__":
    main()
