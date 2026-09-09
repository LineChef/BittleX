#!/usr/bin/env python3
"""Promote a curated capture session into the persistent training library.

Two folders, kept apart:

  ~/Desktop/g2_capture_raw/          disposable -- raw frames + curate output
    <class>/session_<k>/             *.jpg *.json  (raw)
    <class>/session_<k>/curated/     pos_*.jpg pos_*.txt neg_*.jpg _contact_sheet.png

  ~/Desktop/g2_vision_library/       KEEP -- only curated, labelled, upload-ready
    person/  person_0001.jpg person_0001.txt ...
    dog/     dog_0001.jpg ...
    cat/     ...
    ledge/   ...
    _negatives/  neg_0001.jpg ...
    _manifest.json  _MANIFEST.md

This copies the `pos_*` (jpg + YOLO .txt) and `neg_*` from ONE curated session
into the library, continuing the per-class numbering, and updates the manifest.
Idempotent: a session already promoted is skipped unless --force.

    python tools/promote_to_library.py \\
        ~/Desktop/g2_capture_raw/person/session_1/curated \\
        --library ~/Desktop/g2_vision_library --class person

Run `combine_for_upload.py` on the library when it's time to (re)train.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import shutil
import sys

NEG_DIR = "_negatives"
MANIFEST = "_manifest.json"


def _load_manifest(lib: str) -> dict:
    p = os.path.join(lib, MANIFEST)
    if os.path.isfile(p):
        try:
            return json.load(open(p))
        except (OSError, json.JSONDecodeError):
            pass
    return {"classes": {}, "negatives": 0, "promoted": [], "updated": None}


def _write_manifest(lib: str, m: dict) -> None:
    m["updated"] = dt.datetime.now().isoformat(timespec="seconds")
    json.dump(m, open(os.path.join(lib, MANIFEST), "w"), indent=2)
    lines = ["# G2 vision training library", "",
             f"updated: {m['updated']}", "",
             "| class | images |", "|---|---|"]
    for c, n in sorted(m["classes"].items()):
        lines.append(f"| `{c}` | {n} |")
    lines += [f"| _negatives_ | {m['negatives']} |", "",
              f"{len(m['promoted'])} session(s) promoted:", ""]
    lines += [f"- {s}" for s in m["promoted"]]
    # hint uses first-promoted order (= intended class-id order), not alphabetical
    order = ",".join(m["classes"].keys()) or "person,dog,cat,ledge"
    lines += ["", "Rebuild the upload set:", "```",
              "python tools/combine_for_upload.py ~/Desktop/g2_vision_library \\",
              f"    --classes {order}",
              "```", ""]
    open(os.path.join(lib, "_MANIFEST.md"), "w").write("\n".join(lines))


def _next_index(dirpath: str, prefix: str) -> int:
    n = 0
    for p in glob.glob(os.path.join(dirpath, f"{prefix}_*.jpg")):
        try:
            n = max(n, int(os.path.basename(p)[len(prefix) + 1:-4]))
        except ValueError:
            pass
    return n + 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("curated_dir", help="a .../<class>/session_<k>/curated folder")
    ap.add_argument("--library", required=True, help="the KEEP library root")
    ap.add_argument("--class", dest="cls", required=True, help="class name (= subfolder)")
    ap.add_argument("--force", action="store_true", help="re-promote even if already done")
    a = ap.parse_args()

    cur = os.path.expanduser(a.curated_dir)
    lib = os.path.expanduser(a.library)
    if not glob.glob(os.path.join(cur, "pos_*.jpg")):
        sys.exit(f"no pos_*.jpg in {cur} -- run curate_captures.py first")

    # a stable id for this session: ".../person/session_1/curated" -> "person/session_1"
    parts = os.path.normpath(cur).split(os.sep)
    sess_id = "/".join(parts[-3:-1]) if len(parts) >= 3 else os.path.basename(cur)

    m = _load_manifest(lib)
    if sess_id in m["promoted"] and not a.force:
        sys.exit(f"{sess_id} already promoted (--force to redo). "
                 f"library has {m['classes'].get(a.cls, 0)} {a.cls} images.")

    cls_dir = os.path.join(lib, a.cls)
    neg_dir = os.path.join(lib, NEG_DIR)
    os.makedirs(cls_dir, exist_ok=True)
    os.makedirs(neg_dir, exist_ok=True)

    pi = _next_index(cls_dir, a.cls)
    npos = 0
    for jpg in sorted(glob.glob(os.path.join(cur, "pos_*.jpg"))):
        txt = jpg[:-4] + ".txt"
        dst = os.path.join(cls_dir, f"{a.cls}_{pi:04d}")
        shutil.copy2(jpg, dst + ".jpg")
        if os.path.isfile(txt):
            shutil.copy2(txt, dst + ".txt")
        else:
            print(f"  ! no label for {os.path.basename(jpg)} -- box it in SenseCraft/Roboflow")
        pi += 1
        npos += 1

    ni = _next_index(neg_dir, "neg")
    nneg = 0
    for jpg in sorted(glob.glob(os.path.join(cur, "neg_*.jpg"))):
        shutil.copy2(jpg, os.path.join(neg_dir, f"neg_{ni:04d}.jpg"))
        ni += 1
        nneg += 1

    m["classes"][a.cls] = m["classes"].get(a.cls, 0) + npos
    m["negatives"] = m["negatives"] + nneg
    if sess_id not in m["promoted"]:
        m["promoted"].append(sess_id)
    _write_manifest(lib, m)

    print(f"promoted {sess_id}: +{npos} {a.cls}, +{nneg} negatives")
    print(f"library now: " + ", ".join(f"{c} {n}" for c, n in sorted(m["classes"].items()))
          + f", negatives {m['negatives']}")


if __name__ == "__main__":
    main()
