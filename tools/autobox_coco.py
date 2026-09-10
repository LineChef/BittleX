#!/usr/bin/env python3
"""Auto-label a folder of images with a COCO-pretrained YOLOv8 detector and
write YOLO `.txt` boxes next to each `.jpg`. Retroactively does what "capture
with a COCO-80 model loaded" would have — real boxes around the subject instead
of the whole-frame `--box-fallback` placeholder.

    python tools/autobox_coco.py ~/Desktop/g2_vision_library/dog      --coco-class dog
    python tools/autobox_coco.py ~/Desktop/g2_vision_library/cat      --coco-class cat
    python tools/autobox_coco.py ~/Desktop/g2_vision_library/<person> --coco-class person --overwrite

Writes class id 0 (a placeholder — `combine_for_upload.py --classes ...` rewrites
it from the class order). Images with no detection get no `.txt` and are listed
at the end (hand-box the few, or they drop out at combine).
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

COCO = {"person": 0, "cat": 15, "dog": 16}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--coco-class", required=True, choices=sorted(COCO))
    ap.add_argument("--conf", type=float, default=0.25, help="min detection confidence")
    ap.add_argument("--weights", default="yolov8n.pt", help="yolov8n/s/m/l/x .pt")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--augment", action="store_true", help="test-time augmentation (slower, better recall)")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace existing .txt (default: skip images that already have one)")
    ap.add_argument("--max-boxes", type=int, default=3, help="cap boxes per image")
    a = ap.parse_args()

    from ultralytics import YOLO

    tid = COCO[a.coco_class]
    folder = os.path.expanduser(a.folder)
    jpgs = sorted(glob.glob(os.path.join(folder, "*.jpg")))
    if not jpgs:
        sys.exit(f"no .jpg in {folder}")

    todo = jpgs if a.overwrite else [j for j in jpgs if not os.path.isfile(j[:-4] + ".txt")]
    print(f"{folder}: {len(jpgs)} images, labelling {len(todo)} "
          f"(coco '{a.coco_class}'=#{tid}, conf>={a.conf})")

    model = YOLO(a.weights)
    hit = miss = nbox = 0
    areas: list[float] = []
    confs: list[float] = []
    missed: list[str] = []

    for i in range(0, len(todo), 64):
        batch = todo[i:i + 64]
        for jpg, res in zip(batch, model.predict(batch, conf=a.conf, verbose=False,
                                                 classes=[tid], imgsz=a.imgsz,
                                                 augment=a.augment)):
            rows = []
            b = res.boxes
            if b is not None and len(b):
                xywhn = b.xywhn.cpu().numpy()          # normalized cx,cy,w,h
                cf = b.conf.cpu().numpy()
                order = cf.argsort()[::-1][:a.max_boxes]
                for k in order:
                    cx, cy, w, h = (float(v) for v in xywhn[k])
                    rows.append(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
                    areas.append(w * h)
                    confs.append(float(cf[k]))
            if rows:
                open(jpg[:-4] + ".txt", "w").write("\n".join(rows) + "\n")
                hit += 1
                nbox += len(rows)
            else:
                miss += 1
                missed.append(os.path.basename(jpg))
        print(f"  {min(i + 64, len(todo)):4d}/{len(todo)}  hit {hit}  miss {miss}", end="\r")

    print()
    med = sorted(areas)[len(areas) // 2] if areas else 0.0
    print(f"\n{hit}/{len(todo)} labelled ({nbox} boxes), {miss} with NO detection")
    if confs:
        print(f"  confidence  mean {sum(confs) / len(confs):.2f}  min {min(confs):.2f}")
        print(f"  box area    mean {sum(areas) / len(areas):.3f}  median {med:.3f}   "
              f"(fallback was 0.740 — lower & varied is the point)")
    if missed:
        print(f"\n  {len(missed)} images with no '{a.coco_class}' detected "
              f"(hand-box or drop):")
        for m in missed[:40]:
            print("   ", m)
        if len(missed) > 40:
            print(f"    ... +{len(missed) - 40} more")


if __name__ == "__main__":
    main()
