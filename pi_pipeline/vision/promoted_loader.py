"""Load the pictures you PROMOTED on the g2pics page into the robot's object gallery, automatically (user, 2026-10-10: "make loading happen automatically after promotion").

Promoting a labelled picture on the Mac queues its path here (`add`); if no exploration is running the queue is processed at once, otherwise at the start of the next exploration session
(the session loads the gallery file and would overwrite a change made while it runs). For each queued picture the gallery learns it under its label (`Recognizer.learn_named`: the picture is
embedded and added to the entry it matches or a new one, and the entry is named). A picture whose look-alike already has a DIFFERENT name is not loaded (reported as a conflict: two names for
look-alikes is for you to decide). Nothing is removed from the gallery when a picture is un-promoted.

    python -m pi_pipeline.vision.promoted_loader add named/mug/mug_1.jpg [...]      queue, and load now when idle
    python -m pi_pipeline.vision.promoted_loader run                                load what is queued (the session start does this)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("g2.promoted_loader")

PENDING = Path(os.path.expanduser(os.environ.get("G2_GALLERY_PENDING", "~/.local/share/g2/gallery_pending.json")))
PICTURES = os.environ.get("G2_EXPLORE_PICTURES_DIR", "~/.local/share/g2/explore_pictures")


def _pending() -> list[str]:
    try:
        return [str(x) for x in json.loads(PENDING.read_text())]
    except (OSError, ValueError):
        return []


def _save_pending(rels: list[str]) -> None:
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(sorted(set(rels))))


def exploring() -> bool:
    """True while an exploration session runs (it holds the gallery in memory)."""
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", "g2-explore"], timeout=5).returncode == 0
    except Exception:  # noqa: BLE001 -- not a systemd machine
        return False


def process(gallery_path: str | None = None, pictures_root: str | None = None, *, embedder=None, gallery=None, save=True) -> dict:
    """Teach the gallery every queued picture. Returns {"loaded": [...], "conflicts": [...], "missing": [...]}; loaded and missing ones leave the queue, conflicts stay out of it too (reported once)."""
    from ..config import settings
    from .object_gallery import ObjectGallery, ObjectGalleryConfig
    from .recognizer import Recognizer
    from .embedder import make_embedder, to_image
    from .interest import crop_quality
    rels = _pending()
    out = {"loaded": [], "conflicts": [], "missing": []}
    if not rels:
        return out
    gpath = Path(gallery_path or os.path.join(os.path.expanduser(settings.object_gallery_dir), "gallery.json"))
    gal = gallery or ObjectGallery.load(gpath, ObjectGalleryConfig(lock_by_holdout=True))
    rec = Recognizer(embedder or make_embedder(os.environ.get("G2_EMBEDDER", "histogram")), gal)
    root = Path(os.path.expanduser(pictures_root or PICTURES))
    for rel in rels:
        f = root / rel
        parts = rel.split("/")
        if len(parts) < 3 or parts[0] != "named" or not f.exists():
            out["missing"].append(rel)
            continue
        try:
            img = to_image(f.read_bytes())
            decision = rec.learn_named(img, parts[1].replace("-", " "), quality=crop_quality(img), crop_ref=rel)
        except Exception:  # noqa: BLE001
            log.exception("could not load %s", rel)
            out["missing"].append(rel)
            continue
        if decision is None:
            out["conflicts"].append({"path": rel, "conflict": list(rec.last_conflict or ())})
        else:
            out["loaded"].append({"path": rel, "decision": decision.value})
    if save and (out["loaded"] or out["conflicts"]):
        gpath.parent.mkdir(parents=True, exist_ok=True)
        gal.save(gpath)
    _save_pending([])
    log.info("promoted pictures loaded into the gallery: %s", json.dumps(out))
    return out


def add(rels: list[str], **kw) -> dict:
    """Queue `rels` and load them now unless an exploration is running (then the next session start does it)."""
    _save_pending(_pending() + list(rels))
    if exploring():
        return {"queued": list(rels), "loaded": [], "deferred": True}
    return {**process(**kw), "deferred": False}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.vision.promoted_loader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("paths", nargs="+")
    sub.add_parser("run")
    args = ap.parse_args(argv)
    print(json.dumps(add(args.paths) if args.cmd == "add" else process()))


if __name__ == "__main__":
    main()
