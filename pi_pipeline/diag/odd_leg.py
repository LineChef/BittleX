"""A flag for an odd leg (owner, 2026-11-06: one leg points at a wrong angle after a stand-up about 2% of the time, a different leg each time). Run it the moment you see it:

    g2oddleg [which leg and what it did]          # on the Mac: runs this on the Pi

It writes the time, your note and the last leg checks (what the board held, pack volts, tilt) to ~/.local/share/g2/odd_leg.jsonl, so the leg check, tilt and voltage logs can be lined up with
what you saw. It sends nothing to the board.
"""
from __future__ import annotations

import json
import os
import sys
import time

LOG = "~/.local/share/g2/odd_leg.jsonl"
LEG_CHECK = "~/.local/share/g2/leg_check.jsonl"


def last_checks(n: int = 3, path: str = LEG_CHECK) -> list:
    try:
        rows = [json.loads(line) for line in open(os.path.expanduser(path)) if line.strip()]
    except (OSError, ValueError):
        return []
    return rows[-n:]


def flag(note: str = "", *, path: str = LOG, now=time.time) -> dict:
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now())), "note": note, "last_leg_checks": last_checks()}
    p = os.path.expanduser(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def main(argv=None) -> None:
    rec = flag(" ".join(sys.argv[1:] if argv is None else argv))
    print("flagged", rec["t"], "-", len(rec["last_leg_checks"]), "recent leg check(s) attached")


if __name__ == "__main__":
    main()
