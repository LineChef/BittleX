"""Automatic per-run logs: every policy walk (and scripted walk) with no explicit `--log` writes `~/g2_runs/auto/<date>/<kind>_<time>.csv` plus a JSON sidecar
(kind, hardware epoch, surface, policy, commands, why the run ended). The data is raw and plain on the Pi; the Mac compresses it at ingest.

`G2_AUTOLOG=off` turns it off (the tests do). `G2_AUTOLOG_DIR` moves the folder. Nothing here may ever stop a walk: every failure falls back to no log."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from .epochs import epoch_at

log = logging.getLogger("g2.autolog")

SURFACE_FILE = "~/.local/share/g2/surface"
DEPLOYED_COMMIT_FILE = Path(__file__).resolve().parents[1] / ".deployed_commit"


def enabled() -> bool:
    return os.environ.get("G2_AUTOLOG", "on").strip().lower() not in ("off", "0", "false", "no")


def base_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get("G2_AUTOLOG_DIR", "~/g2_runs/auto")))


def get_surface_info() -> tuple[str, float | None]:
    """(label, hours since it was set). The file holds the label, then the time it was set; an old file with only a label has an unknown age."""
    try:
        lines = Path(os.path.expanduser(SURFACE_FILE)).read_text().split("\n")
    except OSError:
        return "unknown", None
    label = (lines[0].strip() if lines else "") or "unknown"
    try:
        age = max(0.0, (time.time() - float(lines[1])) / 3600.0)            # the stored time is rounded to the millisecond, so it can sit a hair in the future
    except (IndexError, ValueError):
        age = None
    return label, age


def get_surface() -> str:
    return get_surface_info()[0]


def set_surface(label: str) -> str:
    """Remember the floor G2 is on (hardwood, tile, carpet, ...); every later run records it."""
    label = "-".join(str(label).strip().lower().split()) or "unknown"
    p = Path(os.path.expanduser(SURFACE_FILE))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{label}\n{time.time():.3f}\n")
    return label


def deployed_commit() -> str | None:
    try:
        return DEPLOYED_COMMIT_FILE.read_text().strip() or None
    except OSError:
        return None


class RunLog:
    """One run's log: `csv_path` to write rows to, and a sidecar that is complete from the start and updated by `finish()`."""

    def __init__(self, csv_path: Path, meta: dict):
        self.csv_path = str(csv_path)
        self._side = csv_path.with_suffix(".json")
        self._meta = meta
        self._t0 = time.time()
        self._write()

    def _write(self) -> None:
        try:
            tmp = self._side.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._meta, indent=1))
            tmp.replace(self._side)
        except OSError:
            log.debug("could not write the run sidecar", exc_info=True)

    def finish(self, reason: str, **extra) -> None:
        self._meta.update(ended=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), end_reason=reason, duration_s=round(time.time() - self._t0, 2), **extra)
        self._write()


def new_run(kind: str, *, policy: str | None = None, cmd_fwd: float | None = None, hz: float | None = None, extra: dict | None = None, now: float | None = None) -> RunLog | None:
    """Open a run log, or None when auto-logging is off or the folder cannot be made (the walk then simply goes unlogged)."""
    if not enabled():
        return None
    try:
        t = time.time() if now is None else now
        started = datetime.fromtimestamp(t)
        folder = base_dir() / started.strftime("%Y%m%d")
        folder.mkdir(parents=True, exist_ok=True)
        csv_path = folder / f"{kind}_{started.strftime('%H%M%S')}.csv"
        n = 1
        while csv_path.exists() or csv_path.with_suffix(".json").exists():       # the sidecar exists from the start, the CSV only once the loop opens it
            n += 1
            csv_path = folder / f"{kind}_{started.strftime('%H%M%S')}_{n}.csv"
        ep = epoch_at(started)
        meta = {"kind": kind, "started": started.strftime("%Y-%m-%dT%H:%M:%S"), "epoch": ep["id"] if ep else None, "epoch_fit_ok": ep.get("fit_ok") if ep else None,
                "surface": get_surface_info()[0], "surface_age_h": None if get_surface_info()[1] is None else round(get_surface_info()[1], 2), "policy": policy, "cmd_fwd": cmd_fwd, "hz": hz, "commit": deployed_commit(), "ended": None, "end_reason": None}
        meta.update(extra or {})
        return RunLog(csv_path, meta)
    except Exception:  # noqa: BLE001 -- logging must never stop a walk
        log.debug("auto-log could not start", exc_info=True)
        return None


def run_sidecars(root: Path | None = None) -> list[Path]:
    """Every run's sidecar, oldest first; the label files that sit beside them are not runs."""
    return sorted(s for s in (root or base_dir()).glob("*/*.json") if not s.name.endswith(".labels.json"))


def close_orphans(root: Path | None = None) -> int:
    """Flag the sidecars of runs that never finished (the service or the Pi stopped mid-run) so they are not mistaken for complete ones. Returns how many."""
    n = 0
    for side in run_sidecars(root):
        try:
            d = json.loads(side.read_text())
            if d.get("ended") is None and d.get("end_reason") is None:
                d["end_reason"] = "unfinished"
                side.write_text(json.dumps(d, indent=1))
                n += 1
        except (OSError, ValueError):
            continue
    return n


def size_mb(root: Path | None = None) -> float:
    try:
        return sum(f.stat().st_size for f in (root or base_dir()).rglob("*") if f.is_file()) / 1e6
    except OSError:
        return 0.0


def find_run(stem: str, root: Path | None = None) -> Path | None:
    """The sidecar for a run named by its file stem or a unique part of it (for example `policy_walk_141700` or `141700`)."""
    sides = run_sidecars(root)
    exact = [s for s in sides if s.stem == stem]
    hits = exact or [s for s in sides if stem in s.stem]
    return hits[0] if len(hits) == 1 else None


def exclude_run(stem: str, reason: str, *, by: str = "user", root: Path | None = None) -> str | None:
    """Flag a run so it is never used for fitting (a collision, a pick-up, a bad surface label ...). Nothing is deleted: the log stays, the sidecar says why. Returns the run's name, or None if no single run matches."""
    side = find_run(stem, root)
    if side is None:
        return None
    d = json.loads(side.read_text())
    d.update(excluded=True, excluded_reason=reason, excluded_by=by, excluded_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    side.write_text(json.dumps(d, indent=1))
    return side.stem
