#!/usr/bin/env python3
"""Flag curated positives that are near-duplicates of images already promoted
into the vision library, using the same average-hash `curate_captures.py`'s
own dedup uses -- so a new capture session can't waste its distance/pose quota
on frames the model has effectively already seen.

    python tools/check_library_overlap.py <curated_dir> --library ~/Desktop/g2_vision_library --class sam
    python tools/check_library_overlap.py <curated_dir> --library ~/Desktop/g2_vision_library --class sam --remove

Checks every `pos_*.jpg` in <curated_dir> against every already-promoted
`<class>_*.jpg` under <library>/<class>/ -- i.e. against every prior session
for that class, not just the most recent one. `--remove` deletes flagged
files (and their `.txt` label) from <curated_dir> only -- it never touches the
library -- so `promote_to_library.py` only sees the survivors. Default
threshold matches curate's own `--dup-thresh` (4, tight: only near-identical
frames match, not just a similar pose or distance).
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from curate_captures import ahash, hamming  # noqa: E402
from PIL import Image  # noqa: E402


def _hashes(paths: list[str]) -> dict[str, int]:
    out = {}
    for p in paths:
        try:
            out[p] = ahash(Image.open(p))
        except Exception as e:
            print(f"  skip (unreadable): {p}  ({e})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("curated_dir", help="a .../session_<k>/curated folder (checks pos_*.jpg)")
    ap.add_argument("--library", required=True, help="the vision library root")
    ap.add_argument("--class", dest="cls", required=True, help="class subfolder under the library")
    ap.add_argument("--thresh", type=int, default=4,
                    help="hamming distance counted as a duplicate (default 4, matches curate's --dup-thresh)")
    ap.add_argument("--remove", action="store_true",
                    help="delete flagged files from curated_dir (default: report only, no changes)")
    a = ap.parse_args()

    new_paths = sorted(glob.glob(os.path.join(a.curated_dir, "pos_*.jpg")))
    lib_paths = sorted(glob.glob(os.path.join(os.path.expanduser(a.library), a.cls, f"{a.cls}_*.jpg")))

    if not new_paths:
        print(f"no pos_*.jpg in {a.curated_dir}")
        return
    if not lib_paths:
        print(f"no existing {a.cls} images in {a.library} -- nothing to compare against, nothing flagged")
        return

    print(f"comparing {len(new_paths)} new positives against {len(lib_paths)} existing "
          f"{a.cls} library images (hamming <= {a.thresh})")
    lib_hashes = _hashes(lib_paths)
    new_hashes = _hashes(new_paths)

    flagged = []
    for np_, nh in new_hashes.items():
        match = next((lp for lp, lh in lib_hashes.items() if hamming(nh, lh) <= a.thresh), None)
        if match:
            flagged.append((np_, match))

    if not flagged:
        print(f"no overlap found -- all {len(new_hashes)} new positives are distinct from the library")
        return

    print(f"\n{len(flagged)} near-duplicate(s) of existing library images:")
    for np_, match in flagged:
        print(f"  {os.path.basename(np_)}  ~=  {os.path.basename(match)}")

    if a.remove:
        for np_, _ in flagged:
            txt = os.path.splitext(np_)[0] + ".txt"
            os.remove(np_)
            if os.path.exists(txt):
                os.remove(txt)
        print(f"\nremoved {len(flagged)} duplicate(s) from {a.curated_dir}")
    else:
        print("\n(dry run -- rerun with --remove to delete these from the curated dir before promoting)")


if __name__ == "__main__":
    main()
