#!/usr/bin/env python3
"""Check the wall calibration sets on this Mac (owner, 2026-11-18): `~/Desktop/G2Memory/g2_pictures/wall_calibration/<set>/` holds the pictures the wall calibration is built from, kept apart from every other wall picture.

    python3 tools/g2_cal_verify.py [--quiet] [--root DIR]

For every set it (1) pins the set's MANIFEST.json the first time it is seen, in `_pinned/<set>.json` beside the sets (a Mac-only copy that a sync from the Pi never overwrites), (2) re-hashes every file and compares with the
pinned copy, saying CHANGED / MISSING / ADDED for anything that differs, and (3) makes the files read-only. A set with new pictures after a sync shows ADDED: run with `--accept NAME` to pin the new state once you
have looked. Exit 1 when any set differs. Nothing is deleted or rewritten except the pinned copies and the file modes."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pi_pipeline.vision import wall_calibration_set as wcs  # noqa: E402

ROOT = Path(os.path.expanduser("~/Desktop/G2Memory/g2_pictures/wall_calibration"))


def sets(root: Path) -> list:
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")) if root.exists() else []


def check(root: Path = ROOT, accept: str | None = None) -> list:
    """[(set name, result dict)] for every set under `root`; pins new sets, locks files."""
    pins = root / "_pinned"
    out = []
    for d in sets(root):
        pinned_file = pins / f"{d.name}.json"
        if accept == d.name or not pinned_file.exists():
            m = d / wcs.MANIFEST
            man = json.loads(m.read_text()) if m.exists() else wcs.write_manifest(d)
            have = wcs.write_manifest(d) if accept == d.name else man
            pins.mkdir(parents=True, exist_ok=True)
            pinned_file.write_text(json.dumps(have, indent=1))
        res = wcs.verify(d, json.loads(pinned_file.read_text()))
        wcs.lock(d)
        out.append((d.name, res))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--accept", default=None, metavar="NAME", help="pin the current state of this set (after you have looked at what was added)")
    a = ap.parse_args(argv)
    root = Path(a.root)
    res = check(root, a.accept)
    bad = [(n, r) for n, r in res if not r["ok"]]
    if not a.quiet or bad:
        if not res:
            print("wall calibration sets: none yet (the first set is taken with `wall_pictures shot --calibration NAME --inches N`)")
        for n, r in res:
            if r["ok"]:
                print(f"wall calibration set {n}: {r['files']} files, all match the pinned copy")
            else:
                print(f"wall calibration set {n}: DIFFERS from the pinned copy: changed {r['changed']}, missing {r['missing']}, added {r['added']}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
