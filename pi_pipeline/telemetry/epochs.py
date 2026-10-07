"""Hardware epochs: dated hardware changes. Fits use the current epoch only; older ones are kept but not fed unless a person says so.

The user says when hardware changes; the entry is added to `hardware_epochs.json` (dated, newest last). `fit_ok` is False for an epoch with a known fault."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("hardware_epochs.json")


def load_epochs(path=None) -> list[dict]:
    try:
        rows = json.loads(Path(path or DEFAULT_PATH).read_text())
    except (OSError, ValueError):
        return []
    return sorted((r for r in rows if "id" in r and "start" in r), key=lambda r: r["start"])


def epoch_at(when=None, path=None) -> dict | None:
    """The epoch in force at `when` (a datetime, epoch seconds, or None for now); None before the first one."""
    if when is None:
        when = datetime.now()
    elif isinstance(when, (int, float)):
        when = datetime.fromtimestamp(when)
    stamp = when.strftime("%Y-%m-%dT%H:%M")
    found = None
    for e in load_epochs(path):
        if e["start"] <= stamp:
            found = e
    return found
