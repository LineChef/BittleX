"""Data-type labels for captured runs (docs/rl/real-data-pipeline.md, "Data-type labels").

When we think we know what kind of data a stretch of a run is (a snag on tile, a fall, a collision, a pick-up), it is labelled. Labels live in a file BESIDE the run (`<run>.labels.json`), never inside the raw log or the sidecar, so the raw data is
never changed and a labeller can be re-run. Each label records who or what made it (`by`: "user" or "claude"), the method and its version (`signature-v1`, `manual`), a confidence when it is inferred, and an optional time window in the run (`t0`..`t1`, seconds from the run start).
Re-running a method replaces only that method's earlier labels; a person's labels are never replaced by a machine."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .autolog import find_run

KNOWN_TAGS = {
    "snag_candidate": "a foot probably caught on something (grout line, edge): a disturbance signature, not confirmed",
    "snag": "a snag a person confirmed",
    "fall": "G2 went down",
    "collision": "G2 hit something (furniture, wall); not a gait event",
    "pickup": "G2 was picked up or moved by hand",
    "steady_walk": "an uninterrupted stretch of ordinary walking",
    "short_segment": "too short for steady-state use",
    "unfinished": "the run never closed cleanly (a crash or power loss)",
}


def labels_path(side: Path) -> Path:
    return side.with_suffix(".labels.json")


def read_labels(stem: str, root: Path | None = None) -> list[dict]:
    side = find_run(stem, root)
    if side is None:
        return []
    try:
        return json.loads(labels_path(side).read_text())
    except (OSError, ValueError):
        return []


def add_labels(stem: str, entries: list[dict], *, by: str, method: str, version: str = "", root: Path | None = None) -> str | None:
    """Add labels to a run. `entries`: dicts with `tag` and optionally `t0`, `t1`, `confidence`, `note`. Earlier labels from the same `method` are replaced (so a machine labeller can be re-run); other methods' labels, and any
    by a person, are kept. Returns the run's name, or None when no single run matches."""
    side = find_run(stem, root)
    if side is None:
        return None
    for e in entries:
        if e.get("tag") not in KNOWN_TAGS:
            raise ValueError(f"unknown label {e.get('tag')!r}; known: {', '.join(sorted(KNOWN_TAGS))}")
    keep = [x for x in read_labels(side.stem, root or side.parent.parent) if x.get("method") != method or x.get("by") == "user" and by != "user"]
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    new = [{"tag": e["tag"], "t0": e.get("t0"), "t1": e.get("t1"), "confidence": e.get("confidence"), "note": e.get("note", ""), "by": by, "method": method, "version": version, "at": now} for e in entries]
    labels_path(side).write_text(json.dumps(keep + new, indent=1))
    return side.stem


def summary(root: Path | None = None) -> dict[str, int]:
    """How many labels of each tag exist across all runs."""
    from .autolog import base_dir
    out: dict[str, int] = {}
    for f in (root or base_dir()).glob("*/*.labels.json"):
        try:
            for x in json.loads(f.read_text()):
                out[x["tag"]] = out.get(x["tag"], 0) + 1
        except (OSError, ValueError, KeyError):
            continue
    return out
