#!/usr/bin/env python3
"""Near-duplicate and storage report for the picture galleries (2026-11-17, owner-approved), a dry run unless told otherwise.

    python tools/gallery_report.py [NAME ...] [--apply]

For each gallery (vision_library, capture_raw, pictures, exploration; or the names given) it reports the picture count and size against a storage budget, the unreadable files, and the near-duplicate groups
(average hash within picture_score.DEDUP_HAMMING of each other, so the same scene again): the best-scored picture of each group stays, the rest are the "extras". A contact sheet of the biggest groups (kept
first, the extras after it) and a JSON report are written to ~/Desktop/G2Memory/_dedup_reports/. Nothing moves unless `--apply`, which MOVES the extras (and their .json notes) to
~/Desktop/G2Memory/_pruned/<gallery>_<date>/ keeping their folder layout; nothing is deleted, and moving them back undoes it. Protected pictures are never extras: hand-named (sidecar named_by "hand"), anything under promoted/, named/, auto/ or person/.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pi_pipeline.vision import picture_score as ps  # noqa: E402

GALLERIES = {
    "vision_library": ("~/Desktop/G2Memory/g2_vision_library", 300.0),
    "capture_raw": ("~/Desktop/G2Memory/g2_capture_raw", 150.0),
    "pictures": ("~/Desktop/G2Memory/g2_pictures", 100.0),
    "exploration": ("training_data/exploration", 100.0),
}                                                                              # name: (folder, storage budget in MB)
SKIP_DIRS = ("_pruned", "_trash")


def scan(root: str) -> tuple[list, list]:
    rows, bad = [], []
    for d, dirs, fs in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in fs:
            if not f.lower().endswith((".jpg", ".jpeg")):
                continue
            p = os.path.join(d, f)
            try:
                jpeg = open(p, "rb").read()
                m = ps.measure(jpeg)
            except Exception:  # noqa: BLE001
                m = None
            if m is None:
                bad.append(p)
                continue
            rows.append({"path": p, "size": len(jpeg), "hash": m["hash"], "quality": ps.quality(m, False), "hand": _hand(p)})
    return rows, bad


PROTECTED_PARTS = ("/promoted/", "/named/", "/auto/", "/person/")      # hand-promoted and voice-named pictures, the nightly-regenerated set, and the face captures: never moved


def _hand(path: str) -> bool:
    if any(part in path for part in PROTECTED_PARTS):
        return True
    side = os.path.splitext(path)[0] + ".json"
    try:
        return json.load(open(side)).get("named_by") == "hand"
    except Exception:  # noqa: BLE001
        return False


def groups(rows: list, dedup: int = ps.DEDUP_HAMMING) -> list:
    """Near-duplicate groups (best first inside each): [[row, ...], ...] with more than one picture."""
    order = sorted(rows, key=lambda r: (not r["hand"], -r["quality"]))        # a hand-named picture leads its group, then the best scored
    reps: list = []
    for r in order:
        for g in reps:
            if ps.hamming(r["hash"], g[0]["hash"]) <= dedup:
                g.append(r)
                break
        else:
            reps.append([r])
    return [g for g in reps if len(g) > 1]


def extras(gs: list) -> list:
    return [r for g in gs for r in g[1:] if not r["hand"]]


def contact_sheet(gs: list, path: str, n: int = 10, per: int = 5, side: int = 96) -> None:
    gs = sorted(gs, key=lambda g: -len(g))[:n]
    if not gs:
        return
    sheet = Image.new("RGB", (per * side, len(gs) * side), (30, 30, 30))
    for y, g in enumerate(gs):
        for x, r in enumerate(g[:per]):
            try:
                sheet.paste(Image.open(r["path"]).convert("RGB").resize((side, side)), (x * side, y * side))
            except Exception:  # noqa: BLE001
                pass
    sheet.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    out_dir = os.path.expanduser("~/Desktop/G2Memory/_dedup_reports")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M")
    for name in (a.names or list(GALLERIES)):
        folder, budget = GALLERIES[name]
        folder = os.path.abspath(os.path.expanduser(folder))
        rows, bad = scan(folder)
        gs = groups(rows)
        ex = extras(gs)
        mb = sum(r["size"] for r in rows) / 1e6
        ex_mb = sum(r["size"] for r in ex) / 1e6
        print(f"{name}: {len(rows)} pictures, {mb:.0f} MB (budget {budget:.0f} MB{', OVER' if mb > budget else ''}); {len(bad)} unreadable; "
              f"{len(gs)} near-duplicate groups, {len(ex)} extras ({ex_mb:.0f} MB) would move aside")
        sheet = os.path.join(out_dir, f"{name}_{stamp}.png")
        contact_sheet(gs, sheet)
        with open(os.path.join(out_dir, f"{name}_{stamp}.json"), "w") as f:
            json.dump({"pictures": len(rows), "mb": round(mb, 1), "budget_mb": budget, "unreadable": bad, "extras": [r["path"] for r in ex],
                       "groups": [[r["path"] for r in g] for g in sorted(gs, key=lambda g: -len(g))[:200]]}, f, indent=1)
        print(f"   report: {out_dir}/{name}_{stamp}.json" + (f", contact sheet: {sheet}" if os.path.exists(sheet) else ""))
        if a.apply:
            dest = os.path.expanduser(f"~/Desktop/G2Memory/_pruned/{name}_{time.strftime('%Y%m%d')}")
            for r in ex:
                rel = os.path.relpath(r["path"], folder)
                for src in (r["path"], os.path.splitext(r["path"])[0] + ".json"):
                    if os.path.exists(src):
                        to = os.path.join(dest, os.path.relpath(src, folder))
                        os.makedirs(os.path.dirname(to), exist_ok=True)
                        shutil.move(src, to)
                _ = rel
            print(f"   moved {len(ex)} extras to {dest} (nothing deleted)")
        else:
            print("   dry run: nothing moved")


if __name__ == "__main__":
    main()
