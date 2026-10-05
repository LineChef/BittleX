"""Delete old logs and walk-run files so they cannot pile up on the SD card.

At service start, anything directly inside the named folders (diagnostic session folders in ~/g2_logs, walk logs in ~/g2_runs) whose
modification time is older than `days` is removed. Deliberately narrow:
  * only the folders passed in, and only their direct children (no recursion above, no other paths);
  * symlinks and dot-files are never touched;
  * it never deletes the memory database, `.env`, policies or code, because none of those live in these folders and the caller names
    the folders explicitly;
  * `days` <= 0 turns it off. Everything removed is logged."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

log = logging.getLogger("g2.tidy")


def tidy_old(folder, days: float, *, now: float | None = None) -> list[str]:
    """Remove direct children of `folder` older than `days` days. Returns the names removed. Never raises."""
    removed: list[str] = []
    if days <= 0:
        return removed
    now = time.time() if now is None else now
    cutoff = now - days * 86400.0
    try:
        root = Path(folder).expanduser()
        if not root.is_dir() or root.is_symlink():
            return removed
        for child in root.iterdir():
            if child.name.startswith(".") or child.is_symlink():
                continue
            try:
                if child.stat().st_mtime >= cutoff:
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                elif child.is_file():
                    child.unlink()
                else:
                    continue
                removed.append(child.name)
            except OSError:
                log.debug("could not remove %s", child, exc_info=True)
    except Exception:  # noqa: BLE001 -- housekeeping must never stop the service
        log.debug("tidy of %s failed", folder, exc_info=True)
    if removed:
        log.info("tidied %d item(s) older than %.0f days from %s", len(removed), days, folder)
    return removed


def clear_folder(folder, *, min_age_s: float = 600.0, now: float | None = None) -> list[str]:
    """Delete EVERY direct child of `folder` (any age) except things modified in the last `min_age_s` seconds, so a capture session that
    is still being written is not wiped. For the camera preview's capture folder: captures are meant to be pulled to the Mac and then
    forgotten. Same safety rules as `tidy_old` (direct children only, never dot-files or symlinks). Never raises."""
    removed: list[str] = []
    now = time.time() if now is None else now
    try:
        root = Path(folder).expanduser()
        if not root.is_dir() or root.is_symlink():
            return removed
        for child in root.iterdir():
            if child.name.startswith(".") or child.is_symlink():
                continue
            try:
                if now - child.stat().st_mtime < min_age_s:
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                elif child.is_file():
                    child.unlink()
                else:
                    continue
                removed.append(child.name)
            except OSError:
                log.debug("could not remove %s", child, exc_info=True)
    except Exception:  # noqa: BLE001
        log.debug("clearing %s failed", folder, exc_info=True)
    if removed:
        log.info("cleared %d capture item(s) from %s", len(removed), folder)
    return removed


def tidy_startup(folders, days: float) -> dict[str, int]:
    return {str(f): len(tidy_old(f, days)) for f in folders}
