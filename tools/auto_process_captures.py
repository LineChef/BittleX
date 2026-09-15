#!/usr/bin/env python3
"""End-to-end pipeline: capture is still manual (`g2cam`), everything after
that runs here in one command.

For every raw session found under <raw-root>/<class>/session_<k>/ that hasn't
already been promoted:

    1. curate_captures.py        raw frames -> session_<k>/curated/
    2. check_library_overlap.py  drops curated frames that are near-duplicates
                                  of anything already promoted for that class
                                  (--remove), across every prior session
    3. promote_to_library.py     adds the survivors into the persistent library
                                  (idempotent -- already-promoted sessions are
                                  detected up front and skipped)

Then, once every pending session is processed:

    4. optimize_library.py   quality-ranked, deduped, distance-composition-
                              capped subset per class, capped at --target
    5. combine_for_upload.py the optimized subset -> a single upload/ folder,
                              class-ids rewritten in --classes order

    python tools/auto_process_captures.py
    python tools/auto_process_captures.py --classes sam,dog,cat
    python tools/auto_process_captures.py --dry-run       # preview only, no changes
    python tools/auto_process_captures.py --skip-optimize # steps 1-3 only

Raw folder name is taken as the class name (matches `g2cam <name> <session>`,
which saves into <raw-root>/<name>/session_<k>/). If you used a different raw
folder name than the target library class at some point, promote those
sessions by hand with `--class` as before; this script assumes the two match,
which is the case for every capture done via `g2cam` going forward.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def _load_promoted(library: str) -> set[str]:
    p = os.path.join(os.path.expanduser(library), "_manifest.json")
    if not os.path.isfile(p):
        return set()
    try:
        return set(json.load(open(p)).get("promoted", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _run(args: list[str], dry_run: bool) -> tuple[int, str]:
    cmd = [PY] + args
    if dry_run:
        print(f"    (dry-run) {' '.join(cmd)}")
        return 0, ""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.strip().splitlines():
        print(f"    {line}")
    return proc.returncode, out


def discover_sessions(raw_root: str, classes: list[str] | None) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for cls_dir in sorted(glob.glob(os.path.join(raw_root, "*"))):
        cls = os.path.basename(cls_dir)
        if not os.path.isdir(cls_dir) or (classes and cls not in classes):
            continue
        sessions = []
        for sess_dir in sorted(glob.glob(os.path.join(cls_dir, "session_*"))):
            if glob.glob(os.path.join(sess_dir, "*.jpg")):
                sessions.append(sess_dir)
        if sessions:
            found[cls] = sessions
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-root", default="~/Desktop/g2_capture_raw")
    ap.add_argument("--library", default="~/Desktop/g2_vision_library")
    ap.add_argument("--classes", help="comma-separated filter (default: every class found)")
    ap.add_argument("--positives", type=int, default=200, help="curate_captures.py --positives")
    ap.add_argument("--negatives", type=int, default=20, help="curate_captures.py --negatives")
    ap.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270))
    ap.add_argument("--dedup-thresh", type=int, default=4)
    ap.add_argument("--target", type=int, default=150, help="optimize_library.py --target")
    ap.add_argument("--mix", default="far:0.20,mid:0.30,close:0.30,vclose:0.20")
    ap.add_argument("--neg-target", type=int, default=40)
    ap.add_argument("--force", action="store_true", help="reprocess sessions already promoted")
    ap.add_argument("--skip-optimize", action="store_true", help="steps 1-3 only, no final rebuild")
    ap.add_argument("--dry-run", action="store_true", help="print planned actions, change nothing")
    a = ap.parse_args()

    raw_root = os.path.expanduser(a.raw_root)
    library = os.path.expanduser(a.library)
    classes = [c.strip() for c in a.classes.split(",")] if a.classes else None

    promoted = set() if a.force else _load_promoted(library)
    sessions_by_class = discover_sessions(raw_root, classes)

    if not sessions_by_class:
        print(f"no raw sessions with *.jpg found under {raw_root}")
        if a.skip_optimize:
            return
    processed, skipped, failed = 0, 0, 0

    for cls, sessions in sessions_by_class.items():
        for sess_dir in sessions:
            sess_name = os.path.basename(sess_dir)
            sess_id = f"{cls}/{sess_name}"
            if sess_id in promoted:
                print(f"skip  {sess_id}  (already promoted)")
                skipped += 1
                continue

            print(f"\n== {sess_id} ==")
            curated_dir = os.path.join(sess_dir, "curated")

            rc, _ = _run([os.path.join(HERE, "curate_captures.py"), sess_dir, curated_dir,
                          "--positives", str(a.positives), "--negatives", str(a.negatives),
                          "--class-id", "0", "--rotate", str(a.rotate)], a.dry_run)
            if rc != 0:
                print(f"  FAILED at curate -- skipping this session")
                failed += 1
                continue

            _run([os.path.join(HERE, "check_library_overlap.py"), curated_dir,
                  "--library", library, "--class", cls, "--remove"], a.dry_run)
            # overlap check is advisory (e.g. "no existing images yet") -- never
            # blocks promotion on its own exit code.

            rc, _ = _run([os.path.join(HERE, "promote_to_library.py"), curated_dir,
                          "--library", library, "--class", cls], a.dry_run)
            if rc != 0:
                print(f"  FAILED at promote -- check the message above")
                failed += 1
                continue

            processed += 1

    print(f"\n{processed} session(s) processed, {skipped} already promoted, {failed} failed")

    if a.skip_optimize:
        return
    if processed == 0 and not a.dry_run:
        print("nothing new promoted -- rebuilding the upload set from the library as-is")

    all_classes = classes or sorted(
        d for d in os.listdir(library)
        if os.path.isdir(os.path.join(library, d)) and glob.glob(os.path.join(library, d, f"{d}_*.jpg"))
    )
    if not all_classes:
        print("no classes with library images -- nothing to optimize/combine")
        return

    out_dir = os.path.join(library, "upload_optimized")
    print(f"\n== rebuilding {out_dir} ({','.join(all_classes)}, target {a.target}) ==")
    _run([os.path.join(HERE, "optimize_library.py"), library,
          "--classes", ",".join(all_classes), "--target", str(a.target), "--mix", a.mix,
          "--dedup-thresh", str(a.dedup_thresh), "--neg-target", str(a.neg_target),
          "--out", out_dir], a.dry_run)

    print(f"\n== combining for upload ==")
    _run([os.path.join(HERE, "combine_for_upload.py"), out_dir,
          "--classes", ",".join(all_classes)], a.dry_run)

    if not a.dry_run:
        print(f"\nready: {out_dir}/upload/  -- import into SenseCraft")


if __name__ == "__main__":
    main()
