#!/usr/bin/env python3
"""Find the pictures that cannot be decoded even with truncation allowed (2026-11-17, owner-approved), and optionally delete them.

    python tools/find_unreadable.py [--delete]

Scans ~/Desktop/G2Memory/g2_pictures and training_data/exploration/promoted. Never looks at the people pictures (any path with person, people or face), and never at calibration pictures
(tools/g2_groom.is_calibration). A picture cut short by a few bytes still decodes and is NOT listed. A dry run by default; `--delete` removes each file and its .json notes on the Mac and queues the same
removal for the Pi's restorable trash (explore pictures through the exploration module, behaviour pictures through claw_pictures) and sends the queue when the Pi answers.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g2_groom as gm  # noqa: E402
from pi_pipeline.vision import picture_score as ps  # noqa: E402

ROOTS = {"g2_pictures": "~/Desktop/G2Memory/g2_pictures", "promoted": "training_data/exploration/promoted"}
PEOPLE = ("person", "people", "face")


def scan(roots: dict | None = None) -> tuple[list, int, int]:
    """(bad, scanned, skipped_calibration): bad = [(root name, path, size)]."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad, scanned, skipped = [], 0, 0
    for name, root in (roots or ROOTS).items():
        root = os.path.abspath(os.path.join(base, os.path.expanduser(root)) if not os.path.isabs(os.path.expanduser(root)) else os.path.expanduser(root))
        for d, _, fs in os.walk(root):
            for f in fs:
                if not f.lower().endswith((".jpg", ".jpeg")):
                    continue
                p = os.path.join(d, f)
                if any(w in p.lower() for w in PEOPLE):
                    continue
                if name == "g2_pictures" and gm.is_calibration(p, root):
                    skipped += 1
                    continue
                scanned += 1
                try:
                    m = ps.measure(open(p, "rb").read())
                except OSError:
                    m = None
                if m is None:
                    bad.append((name, p, os.path.getsize(p) if os.path.exists(p) else -1))
    return bad, scanned, skipped


def delete(bad: list, root: str | None = None, queue: bool = True) -> dict:
    root = os.path.abspath(os.path.expanduser(root or ROOTS["g2_pictures"]))
    exp, claw, gone = [], [], 0
    for name, p, _ in bad:
        if name != "g2_pictures":                                                # a training picture under promoted/ is only reported: the owner decides
            continue
        assert p.startswith(root + os.sep) and not any(w in p.lower() for w in PEOPLE) and not gm.is_calibration(p, root), p
        rel = os.path.relpath(p, root)
        top = rel.split("/")[0]
        if top == "explore":
            exp.append(os.path.relpath(p, os.path.join(root, "explore")))
        elif top in ("watch", "stream", "bout", "seen", "contact"):
            claw.append(rel.split("/", 1)[1])
        for f in (p, os.path.splitext(p)[0] + ".json"):
            if os.path.exists(f):
                os.remove(f)
                gone += 1
    queued = 0
    if queue and (exp or claw):
        import g2_review_queue as rq
        for module, rels in (("pi_pipeline.vision.exploration_pictures", exp), ("pi_pipeline.vision.claw_pictures", claw)):
            for i in range(0, len(rels), 40):
                rq.add(module, ["trash"] + rels[i:i + 40], text=f"unreadable pictures: trash {len(rels[i:i + 40])} on the Pi too")
                queued += len(rels[i:i + 40])
        print("   Pi:", rq.apply().get("message"))
    return {"deleted_files": gone, "queued": queued}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--delete", action="store_true")
    a = ap.parse_args()
    bad, scanned, skipped = scan()
    print(f"scanned {scanned} pictures (skipped {skipped} calibration pictures and every people picture): {len(bad)} cannot be decoded even with truncation allowed")
    for name, p, size in bad:
        print(f"   {'empty  ' if size == 0 else 'partial'} {name}: {p}")
    if a.delete and bad:
        print("   ", delete(bad))
    elif bad:
        print("   dry run: nothing deleted (add --delete)")


if __name__ == "__main__":
    main()
