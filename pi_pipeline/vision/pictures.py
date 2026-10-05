"""Housekeeping for pictures G2 keeps (only when G2_VISION_SAVE_DIR is set): every picture is deleted after `days` (default 7), and
near-duplicates are pruned as they are saved. Saved pictures have little value to G2 (he cannot recall an image), so they do not pile up.

A picture is a duplicate of an earlier one when their 256-bit average hashes differ in at most `max_distance` bits (the same gate
`tools/camera_preview.py` uses to skip repeated capture frames). The earliest picture of each cluster is kept; later near-copies are
deleted. Only files matching `look_*.jpg` directly inside the given folder are ever touched."""
from __future__ import annotations

import io
import logging
import time
from pathlib import Path

log = logging.getLogger("g2.pictures")

DEFAULT_MAX_DISTANCE = 12


def ahash(jpeg: bytes, side: int = 16) -> int:
    """256-bit average hash of a JPEG (needs Pillow)."""
    from PIL import Image
    im = Image.open(io.BytesIO(jpeg)).convert("L").resize((side, side))
    px = list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())
    avg = sum(px) / len(px)
    h = 0
    for p in px:
        h = (h << 1) | (1 if p > avg else 0)
    return h


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def prune_old(folder, days: float = 7.0, pattern: str = "look_*.jpg", *, now: float | None = None) -> list[str]:
    """Delete every picture in `folder` older than `days` days (0 or less = keep forever). Returns the names removed. Never raises."""
    removed: list[str] = []
    if days <= 0:
        return removed
    cutoff = (time.time() if now is None else now) - days * 86400.0
    try:
        for f in Path(folder).glob(pattern):
            if f.is_symlink() or not f.is_file():
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed.append(f.name)
            except OSError:
                log.debug("could not remove %s", f, exc_info=True)
    except Exception:  # noqa: BLE001
        log.debug("old-picture cleanup failed", exc_info=True)
    if removed:
        log.info("deleted %d picture(s) older than %.0f days", len(removed), days)
    return removed


def prune_duplicates(folder, max_distance: int = DEFAULT_MAX_DISTANCE, pattern: str = "look_*.jpg") -> list[str]:
    """Delete near-duplicate pictures in `folder`, keeping the earliest of each cluster. Returns the names removed. Never raises."""
    removed: list[str] = []
    try:
        kept: list[int] = []
        for f in sorted(Path(folder).glob(pattern)):           # names are timestamps, so sorted = oldest first
            if not f.is_file() or f.is_symlink():
                continue
            try:
                h = ahash(f.read_bytes())
            except Exception:  # noqa: BLE001 -- an unreadable file is left alone
                continue
            if any(hamming(h, k) <= max_distance for k in kept):
                f.unlink()
                removed.append(f.name)
            else:
                kept.append(h)
    except Exception:  # noqa: BLE001
        log.debug("duplicate pruning failed", exc_info=True)
    if removed:
        log.info("pruned %d near-duplicate picture(s): %s", len(removed), ", ".join(removed))
    return removed
