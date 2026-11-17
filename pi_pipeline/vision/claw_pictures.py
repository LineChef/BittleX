"""The Pi's behaviour pictures (`~/g2_claw_pics/<kind>_<time>/…`: the attentive bouts, the active look's watch, the camera stream probes, the seen and contact pictures) and the one edit the Mac's gallery
grooming may queue for them (2026-11-17, owner-approved): `trash` moves pictures to `~/g2_claw_pics_trash/` (restorable with `restore`, nothing is deleted).

It is an allowlist: only folders that start with a kind in ALLOWED_PREFIXES, and never a path with a calibration or recognition word in it (lift, step, claw, wall, ring, localizer, labels), so a calibration
picture cannot be trashed by this command even if the Mac asks for it.

    python -m pi_pipeline.vision.claw_pictures trash|restore PATH [PATH ...]      (PATH under ~/g2_claw_pics, e.g. watch_20261115_190038/pic_03.jpg)
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = "~/g2_claw_pics"
ALLOWED_PREFIXES = ("bout_", "watch_", "stream_", "seen_", "contact_")
REFUSED_WORDS = ("cal", "wall", "ring", "localizer", "label", "claw")


def base(root: str = ROOT) -> Path:
    return Path(os.path.expanduser(root))


def trash_root(root: str = ROOT) -> Path:
    b = base(root)
    return b.with_name(b.name + "_trash")


def _inside(b: Path, rel: str) -> Path:
    p = (b / rel).resolve()
    parts = p.relative_to(b.resolve()).parts if b.resolve() in p.parents else ()
    if not parts or p.suffix.lower() != ".jpg":
        raise ValueError(f"not a picture inside {b}: {rel}")
    if not parts[0].startswith(ALLOWED_PREFIXES):
        raise ValueError(f"not an allowed picture folder: {rel}")
    if any(w in part.lower() for part in parts for w in REFUSED_WORDS):
        raise ValueError(f"a calibration or recognition picture is never trashed: {rel}")
    return p


def trash_pictures(root: str, rels: list[str]) -> list[str]:
    b, tr, moved = base(root), trash_root(root), []
    for rel in rels:
        src = _inside(b, rel)
        if not src.exists():
            continue
        dst = tr / src.relative_to(b.resolve())
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        side = src.with_suffix(".json")
        if side.exists():
            side.replace(dst.with_suffix(".json"))
        moved.append(rel)
    return moved


def restore_pictures(root: str, rels: list[str]) -> list[str]:
    b, tr, back = base(root), trash_root(root), []
    for rel in rels:
        dst = _inside(b, rel)
        src = tr / dst.relative_to(b.resolve())
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        side = src.with_suffix(".json")
        if side.exists():
            side.replace(dst.with_suffix(".json"))
        back.append(rel)
    return back


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("trash", "restore"):
        sp = sub.add_parser(name)
        sp.add_argument("paths", nargs="+")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "trash":
            print(json.dumps({"moved": trash_pictures(a.root, a.paths)}))
        else:
            print(json.dumps({"restored": restore_pictures(a.root, a.paths)}))
    except ValueError as e:
        print(json.dumps({"error": str(e)}))


if __name__ == "__main__":
    main()
