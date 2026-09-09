#!/usr/bin/env python3
"""Merge per-class, per-session curated captures into one upload/ folder.

`curate_captures.py` writes `pos_NNNN.jpg` / `pos_NNNN.txt` / `neg_NNNN.jpg`
with the SAME names every run, so combining several classes (and sessions) into
one folder collides. This copies them into `<root>/upload/` renamed
`<class>_s<k>_pos_NNNN.jpg` (+ matching `.txt`) so SenseCraft / Roboflow can
import the whole set at once.

Layout it expects (from the walkthrough):

    <root>/
      person/session_1/curated/ pos_*.jpg pos_*.txt neg_*.jpg
      person/session_2/curated/ ...
      animal/session_1/curated/ ...
      ledge/session_1/curated/  ...

    python tools/combine_for_upload.py ~/Desktop/g2_capture
    python tools/combine_for_upload.py ~/Desktop/g2_capture --classes person,animal,ledge

It also prints the class-id found in each class's YOLO `.txt` files -- catch a
forgotten `--class-id` before you upload, not after.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
from collections import Counter


def _class_ids(txts: list[str]) -> Counter:
    ids: Counter = Counter()
    for t in txts:
        try:
            with open(t) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        ids[line.split()[0]] += 1
        except OSError:
            pass
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="folder holding <class>/session_*/curated/")
    ap.add_argument("--classes", default=None,
                    help="comma list + ORDER (= class-id order). Default: every "
                         "subdir of root that has a session_*/curated inside it.")
    ap.add_argument("--out", default=None, help="output dir (default <root>/upload)")
    a = ap.parse_args()

    root = os.path.expanduser(a.root)
    out = a.out or os.path.join(root, "upload")

    if a.classes:
        classes = [c.strip() for c in a.classes.split(",") if c.strip()]
    else:
        classes = sorted(
            d for d in os.listdir(root)
            if glob.glob(os.path.join(root, d, "session_*", "curated")))
    if not classes:
        sys.exit(f"no <class>/session_*/curated found under {root}")

    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, "*")):
        os.remove(old)

    print(f"combining into {out}\n")
    grand_pos = grand_neg = 0
    for want_id, cls in enumerate(classes):
        cur_dirs = sorted(glob.glob(os.path.join(root, cls, "session_*", "curated")))
        cpos = cneg = 0
        all_txts: list[str] = []
        for cd in cur_dirs:
            sk = os.path.basename(os.path.dirname(cd)).replace("session_", "s")
            for jpg in sorted(glob.glob(os.path.join(cd, "pos_*.jpg"))):
                stem = jpg[:-4]
                base = f"{cls}_{sk}_{os.path.basename(stem)}"
                shutil.copy2(jpg, os.path.join(out, base + ".jpg"))
                if os.path.isfile(stem + ".txt"):
                    shutil.copy2(stem + ".txt", os.path.join(out, base + ".txt"))
                    all_txts.append(stem + ".txt")
                cpos += 1
            for jpg in sorted(glob.glob(os.path.join(cd, "neg_*.jpg"))):
                base = f"{cls}_{sk}_{os.path.basename(jpg)[:-4]}"
                shutil.copy2(jpg, os.path.join(out, base + ".jpg"))
                cneg += 1
        ids = _class_ids(all_txts)
        id_note = (f"class-id in .txt: {dict(ids)}"
                   + ("" if list(ids) == [str(want_id)]
                      else f"  <-- EXPECTED {want_id}! re-curate this class with "
                           f"--class-id {want_id}"))
        print(f"  [{want_id}] {cls:10} {cpos:4d} pos  {cneg:3d} neg   "
              f"({len(cur_dirs)} session(s))  {id_note}")
        grand_pos += cpos
        grand_neg += cneg

    print(f"\n  total: {grand_pos} positives, {grand_neg} negatives across "
          f"{len(classes)} classes")
    print(f"  VISION_LABELS={','.join(classes)}")
    print(f"\n  next: import {out}/ into a SenseCraft multi-class Object Detection "
          f"project (walkthrough section 6).")


if __name__ == "__main__":
    main()
