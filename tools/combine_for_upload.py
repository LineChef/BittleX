#!/usr/bin/env python3
"""Build one upload/ folder from the training library (or raw curated sessions).

`curate_captures.py` names every run `pos_NNNN` / `neg_NNNN`, so combining
classes/sessions into one folder collides. This copies them out renamed, and
rewrites each YOLO `.txt` class-id from the `--classes` ORDER so the library
stays reorder-safe (the id lives in the class list, not baked into the files).

Two input layouts, auto-detected per class:

  LIBRARY (preferred -- the persistent KEEP folder):
    <root>/person/ person_0001.jpg person_0001.txt ...
    <root>/dog/    dog_0001.jpg ...
    <root>/_negatives/ neg_0001.jpg ...

  RAW curated sessions:
    <root>/person/session_1/curated/ pos_*.jpg pos_*.txt neg_*.jpg
    <root>/person/session_2/curated/ ...

    python tools/combine_for_upload.py ~/Desktop/g2_vision_library --classes person,dog,cat,ledge
    # -> ~/Desktop/g2_vision_library/upload/   (import THIS in walkthrough section 6)
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys

NEG_DIRS = ("_negatives", "negatives")


def _relabel(txt: str, dst: str, class_id: int, relabel: bool) -> None:
    if not relabel:
        shutil.copy2(txt, dst)
        return
    out = []
    with open(txt) as f:
        for line in f:
            p = line.split()
            if len(p) == 5:
                p[0] = str(class_id)
                out.append(" ".join(p))
    open(dst, "w").write("\n".join(out) + ("\n" if out else ""))


def _class_sources(root: str, cls: str):
    """Yield (jpg, txt_or_None, tag) for a class, from whichever layout it uses.
    `tag` disambiguates the output filename."""
    cdir = os.path.join(root, cls)
    lib_jpgs = sorted(glob.glob(os.path.join(cdir, "*.jpg")))
    if lib_jpgs:                                            # LIBRARY layout
        for jpg in lib_jpgs:
            t = jpg[:-4] + ".txt"
            yield jpg, (t if os.path.isfile(t) else None), "lib"
        return
    for cd in sorted(glob.glob(os.path.join(cdir, "session_*", "curated"))):   # RAW
        sk = os.path.basename(os.path.dirname(cd)).replace("session_", "s")
        for jpg in sorted(glob.glob(os.path.join(cd, "pos_*.jpg"))):
            t = jpg[:-4] + ".txt"
            yield jpg, (t if os.path.isfile(t) else None), sk


def _negatives(root: str):
    for nd in NEG_DIRS:
        for jpg in sorted(glob.glob(os.path.join(root, nd, "*.jpg"))):
            yield jpg
    for jpg in sorted(glob.glob(os.path.join(root, "*", "session_*", "curated", "neg_*.jpg"))):
        yield jpg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="the library root (or a raw-capture root)")
    ap.add_argument("--classes", default=None,
                    help="comma list + ORDER = class-id order (also your VISION_LABELS). "
                         "Default: every class subfolder found, alphabetical.")
    ap.add_argument("--out", default=None, help="output dir (default <root>/upload)")
    ap.add_argument("--no-relabel", action="store_true",
                    help="keep the class-id already in each .txt instead of "
                         "rewriting it from --classes order")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap positives PER CLASS at N, evenly spread across the "
                         "set (for the dataset-size threshold experiment)")
    a = ap.parse_args()

    root = os.path.expanduser(a.root)
    out = os.path.expanduser(a.out) if a.out else os.path.join(root, "upload")

    if a.classes:
        classes = [c.strip() for c in a.classes.split(",") if c.strip()]
    else:
        classes = sorted(
            d for d in os.listdir(root)
            if not d.startswith(("_", "upload"))
            and os.path.isdir(os.path.join(root, d))
            and (glob.glob(os.path.join(root, d, "*.jpg"))
                 or glob.glob(os.path.join(root, d, "session_*", "curated"))))
    if not classes:
        sys.exit(f"no class folders found under {root}")

    os.makedirs(out, exist_ok=True)
    for old in glob.glob(os.path.join(out, "*")):
        os.remove(old)

    relabel = not a.no_relabel
    print(f"combining into {out}   (class-id relabel: {'on' if relabel else 'OFF'})\n")
    grand_pos = grand_neg = 0
    missing = 0
    for cid, cls in enumerate(classes):
        src = list(_class_sources(root, cls))
        if a.limit and len(src) > a.limit:
            idx = [round(i * (len(src) - 1) / (a.limit - 1)) for i in range(a.limit)]
            src = [src[i] for i in idx]
        cpos = 0
        for jpg, txt, tag in src:
            base = f"{cls}_{tag}_{cpos + 1:04d}"
            shutil.copy2(jpg, os.path.join(out, base + ".jpg"))
            if txt:
                _relabel(txt, os.path.join(out, base + ".txt"), cid, relabel)
            else:
                missing += 1
            cpos += 1
        note = "" if cpos else "  <-- 0 images! check --classes name vs. the folder"
        if a.limit and cpos == a.limit:
            note = f"  (capped at --limit {a.limit})"
        print(f"  [{cid}] {cls:10} {cpos:4d} images{note}")
        grand_pos += cpos

    for jpg in _negatives(root):
        grand_neg += 1
        shutil.copy2(jpg, os.path.join(out, f"negative_{grand_neg:04d}.jpg"))
    print(f"  [-]  negatives  {grand_neg:4d} images")

    # class list files -- Roboflow wants these on YOLO import; SenseCraft ignores
    # extras harmlessly.
    with open(os.path.join(out, "classes.txt"), "w") as f:
        f.write("\n".join(classes) + "\n")
    with open(os.path.join(out, "data.yaml"), "w") as f:
        f.write(f"nc: {len(classes)}\nnames: [{', '.join(classes)}]\n"
                f"train: .\nval: .\n")

    if missing:
        print(f"\n  ! {missing} positives have NO label .txt -- these need boxing "
              f"(SenseCraft labeller, or Roboflow). Usually just the 'ledge' class.")
    print(f"\n  total: {grand_pos} positives ({grand_pos - missing} already labelled) "
          f"+ {grand_neg} negatives, {len(classes)} classes")
    print(f"  VISION_LABELS={','.join(classes)}")
    print(f"\n  next: import {out}/ into a SenseCraft multi-class Object Detection "
          f"project (walkthrough section 6). The .txt files import as pre-drawn "
          f"boxes -- do NOT run SenseCraft auto-label.")


if __name__ == "__main__":
    main()
