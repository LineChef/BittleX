"""Wall calibration sets: the pictures that BUILD the wall estimator's calibration, kept apart from every other wall picture (owner, 2026-11-18).

A set is a folder `~/g2_wall_calibration/<name>/` on the Pi (`G2_WALL_CAL_DIR` moves the root) holding `shot_NNN.jpg` pictures, a `labels.json` (label, true distance in inches, angle, exposure, camera and arm state) and a
`MANIFEST.json` of SHA-256 hashes. Nothing else writes there: the roam pictures G2 keeps on its own go to `~/.local/share/g2/wall_pics` (a ring of 20) and the ordinary shots to `~/g2_wall_pics`, so a calibration picture
is never mixed with them, trashed with them, groomed with them or replaced by one. The files are read-only once written, `verify` re-hashes them and says what changed, the delete / trash / restore commands of
`wall_pictures` refuse a calibration folder, and the Mac copy (`~/Desktop/G2Memory/g2_pictures/wall_calibration/`) is pinned by `tools/g2_cal_verify.py`. Pure file work: no hardware."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path

CAL_ROOT = os.path.expanduser(os.environ.get("G2_WALL_CAL_DIR", "~/g2_wall_calibration"))
MANIFEST = "MANIFEST.json"
FOLDER_NAME = "g2_wall_calibration"            # on the Pi; the Mac mirror is G2Memory/g2_pictures/wall_calibration


def is_calibration_dir(path) -> bool:
    """True for a folder inside the calibration root or any folder with `wall_calibration` / `g2_wall_calibration` in its path (the Mac mirror)."""
    p = str(Path(path).expanduser().resolve()) if path else ""
    root = str(Path(CAL_ROOT).resolve())
    return p == root or p.startswith(root + os.sep) or "wall_calibration" in p


def set_dir(name: str) -> Path:
    clean = "".join(c for c in str(name) if c.isalnum() or c in "-_.")
    if not clean or clean != str(name):
        raise ValueError("a calibration set name uses letters, digits, - _ and . only, for example claw-walk-2026-11-19")
    return Path(CAL_ROOT) / clean


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(folder: Path) -> list:
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.name != MANIFEST)


def write_manifest(folder) -> dict:
    """Hash every file of the set and write MANIFEST.json (the set's name, when, and file -> SHA-256)."""
    folder = Path(folder)
    files = {str(p.relative_to(folder)): _sha(p) for p in _files(folder)}
    man = {"set": folder.name, "written": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}
    m = folder / MANIFEST
    if m.exists():
        m.chmod(m.stat().st_mode | stat.S_IWUSR)
    m.write_text(json.dumps(man, indent=1))
    return man


def lock(folder) -> int:
    """Make every file of the set read-only (the folder itself stays writable so the next picture can be added). Returns how many files were locked."""
    n = 0
    for p in list(_files(Path(folder))) + [Path(folder) / MANIFEST]:
        if p.exists():
            p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
            n += 1
    return n


def unlock_file(path) -> None:
    p = Path(path)
    if p.exists():
        p.chmod(p.stat().st_mode | stat.S_IWUSR)


def verify(folder, expected: dict | None = None) -> dict:
    """Compare the set on disk with a manifest (the one in the folder, or `expected`, a pinned copy): {"ok", "changed", "missing", "added", "files"}."""
    folder = Path(folder)
    if expected is None:
        try:
            expected = json.loads((folder / MANIFEST).read_text())
        except (OSError, ValueError):
            return {"ok": False, "changed": [], "missing": [], "added": [], "files": 0, "error": "no readable MANIFEST.json"}
    want = dict(expected.get("files", {}))
    have = {str(p.relative_to(folder)): _sha(p) for p in _files(folder)}
    changed = sorted(k for k in want if k in have and want[k] != have[k])
    missing = sorted(k for k in want if k not in have)
    added = sorted(k for k in have if k not in want)
    return {"ok": not (changed or missing or added), "changed": changed, "missing": missing, "added": added, "files": len(have)}
