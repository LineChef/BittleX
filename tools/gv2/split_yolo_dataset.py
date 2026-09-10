#!/usr/bin/env python3
"""Flat YOLO folder  ->  train/val split + resize + zip, ready for the GV2 notebook.

The missing middle step between `tools/combine_for_upload.py` and training. The
2026-09-09 working model used an ad-hoc inline version of this; here it is as a
real, deterministic tool.

    # 1. build the flat folder (jpg + txt pairs, negatives = jpg with no txt)
    python tools/combine_for_upload.py ~/Desktop/g2_vision_library \
        --classes you,dog,cat --out ~/Desktop/g2_vision_library/upload_v4

    # 2. split + resize + zip
    python tools/gv2/split_yolo_dataset.py ~/Desktop/g2_vision_library/upload_v4 \
        --classes you,dog,cat --imgsz 224 --val-frac 0.15 \
        --out ~/Desktop/g2_vision_library/custom_data_yolo_v4.zip

Output zip layout (what g2_yolov8_828_3class.ipynb cell "Upload dataset" expects):

    data.yaml                 # path: /content/ds  train: images/train  val: images/val  nc  names
    images/train/*.jpg        labels/train/*.txt
    images/val/*.jpg          labels/val/*.txt

- Deterministic: seeded shuffle, stratified so every class (and the negatives
  pool) is represented in val at `--val-frac`.
- Resize is plain NxN (ultralytics/SSCMA letterbox internally at train time);
  224 keeps headroom over the 192 train size and keeps the zip small.
- Negatives (jpg with no txt) are carried through as background images.
- Class ids in the .txt are used as-is -- run combine_for_upload.py with the
  same `--classes` first so they already match this order.

Needs Pillow (`pip install pillow`).
"""
from __future__ import annotations

import argparse
import glob
import os
import random
import shutil
import sys
import tempfile
import zipfile


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("flat_dir", help="output of combine_for_upload.py (flat jpg+txt)")
    ap.add_argument("--classes", required=True,
                    help="comma list, SAME ORDER used for combine_for_upload.py")
    ap.add_argument("--out", required=True, help="path to the .zip to write")
    ap.add_argument("--imgsz", type=int, default=224)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-resize", action="store_true",
                    help="copy jpgs as-is instead of resizing to --imgsz")
    a = ap.parse_args()

    names = [c.strip() for c in a.classes.split(",") if c.strip()]
    flat = os.path.expanduser(a.flat_dir)
    out_zip = os.path.expanduser(a.out)
    jpgs = sorted(glob.glob(os.path.join(flat, "*.jpg")))
    if not jpgs:
        sys.exit(f"no .jpg in {flat}")

    if not a.no_resize:
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            sys.exit("Pillow needed for resize -- `pip install pillow` or pass --no-resize")

    # stratify key: first class id in the .txt, or "neg" when there's no .txt
    strata: dict[str, list[str]] = {}
    n_pos = n_neg = 0
    for j in jpgs:
        txt = j[:-4] + ".txt"
        if os.path.isfile(txt) and os.path.getsize(txt) > 0:
            with open(txt) as fh:
                first = fh.readline().split()
            key = first[0] if first else "neg"
            n_pos += 1
        else:
            key = "neg"
            n_neg += 1
        strata.setdefault(key, []).append(j)

    rng = random.Random(a.seed)
    train: list[str] = []
    val: list[str] = []
    for key, items in sorted(strata.items()):
        rng.shuffle(items)
        k = max(1, round(len(items) * a.val_frac)) if len(items) > 1 else 0
        val += items[:k]
        train += items[k:]
    rng.shuffle(train)
    rng.shuffle(val)

    tmp = tempfile.mkdtemp(prefix="gv2ds_")
    ds = os.path.join(tmp, "ds")
    for part in ("train", "val"):
        os.makedirs(os.path.join(ds, "images", part))
        os.makedirs(os.path.join(ds, "labels", part))

    def emit(src_jpgs: list[str], part: str) -> None:
        for src in src_jpgs:
            base = os.path.basename(src)
            dst_img = os.path.join(ds, "images", part, base)
            if a.no_resize:
                shutil.copy2(src, dst_img)
            else:
                from PIL import Image
                with Image.open(src) as im:
                    im.convert("RGB").resize((a.imgsz, a.imgsz)).save(dst_img, quality=92)
            src_txt = src[:-4] + ".txt"
            if os.path.isfile(src_txt) and os.path.getsize(src_txt) > 0:
                shutil.copy2(src_txt, os.path.join(ds, "labels", part, base[:-4] + ".txt"))

    emit(train, "train")
    emit(val, "val")

    with open(os.path.join(ds, "data.yaml"), "w") as fh:
        fh.write("path: /content/ds\ntrain: images/train\nval: images/val\n")
        fh.write(f"nc: {len(names)}\nnames: [{', '.join(names)}]\n")

    os.makedirs(os.path.dirname(out_zip) or ".", exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(ds):
            for f in files:
                full = os.path.join(root, f)
                zf.write(full, os.path.relpath(full, ds))
    shutil.rmtree(tmp, ignore_errors=True)

    mb = os.path.getsize(out_zip) / 1e6
    print(f"{len(jpgs)} images ({n_pos} labelled, {n_neg} negatives)")
    print(f"  train {len(train)}   val {len(val)}   (val-frac {a.val_frac}, seed {a.seed})")
    print(f"  strata: " + ", ".join(f"{names[int(k)] if k.isdigit() and int(k) < len(names) else k}={len(v)}"
                                    for k, v in sorted(strata.items())))
    print(f"-> {out_zip}  ({mb:.1f} MB)")
    if mb > 25:
        print("  ⚠ >25 MB — Colab files.upload() gets flaky; drop --imgsz or cap with combine --limit")


if __name__ == "__main__":
    main()
