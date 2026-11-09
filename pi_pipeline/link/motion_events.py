"""One line in `~/.local/share/g2/motion_events.jsonl` for every stand-up (owner, 2026-11-09: "log every standup"): what pose the board reported before it, whether he was laid in rest first,
the numbers used, how long it took and how it ended (`reached` = the board reported the stand pose, `forced` = it did not and the Pi forced the legs, `refused` = nothing was played).
`diag/run_report.py` reads it. It never raises and never blocks a stand-up; `G2_MOTION_EVENTS=off` turns it off, another value is the file to use instead."""
from __future__ import annotations

import json
import os
import time

PATH = "~/.local/share/g2/motion_events.jsonl"
MAX_BYTES = 2 * 1024 * 1024


def path() -> str | None:
    v = os.environ.get("G2_MOTION_EVENTS", "").strip()
    if v.lower() in ("off", "0", "false", "no"):
        return None
    return os.path.expanduser(v or PATH)


def write(event: str, **fields) -> None:
    p = path()
    if not p:
        return
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        if os.path.exists(p) and os.path.getsize(p) > MAX_BYTES:
            os.replace(p, p + ".1")
        with open(p, "a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **fields}) + "\n")
    except Exception:  # noqa: BLE001
        pass
