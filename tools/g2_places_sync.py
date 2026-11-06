#!/usr/bin/env python3
"""Feed G2's places memory from the room tags set on pictures in g2pics (user, 2026-11-06), and copy his places memory back for the Rooms tab. Standard library only.

    python tools/g2_places_sync.py            # tags -> counts -> the Pi (needs G2_PI); then the Pi's places memory -> ~/Desktop/G2Memory/places.json
    python tools/g2_places_sync.py --dry      # print the counts, send nothing

The tags live on the Mac only (~/Desktop/G2Memory/g2_pictures/explore/rooms.json: picture file name -> room). Each tagged picture counts once toward its room's `views`; what is in it
counts toward `items`: the object's name for a named picture ("dog-bowl" -> "dog bowl"), and the detector's labels. The import REPLACES the earlier import for those rooms (memory/places.py
`import_tagged`), so running it again never counts a picture twice. Counts only: no pictures and no times go to the Pi.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

PICS = Path(os.path.expanduser("~/Desktop/G2Memory/g2_pictures/explore"))
OUT = Path(os.path.expanduser("~/Desktop/G2Memory/places.json"))


def tagged_stats(pics: Path = PICS) -> dict:
    try:
        rooms = json.loads((pics / "rooms.json").read_text())
    except (OSError, ValueError):
        return {}
    where = {f.name: f for top in ("survey", "named") for f in (pics / top).rglob("*.jpg")}
    views, items = Counter(), defaultdict(Counter)
    for fname, room in rooms.items():
        room = (room or "").strip().lower()
        if not room or fname not in where:
            continue
        views[room] += 1
        try:
            meta = json.loads(where[fname].with_suffix(".json").read_text())
        except (OSError, ValueError):
            meta = {}
        if meta.get("name"):
            items[room][str(meta["name"]).replace("-", " ").replace("_", " ")] += 1
        for label in {d.get("label") for d in (meta.get("detections") or []) if d.get("label")}:
            items[room][label] += 1
    return {r: {"views": views[r], "items": dict(items[r])} for r in views}


def main(argv: list[str]) -> int:
    stats = tagged_stats()
    print(f"{sum(v['views'] for v in stats.values())} tagged pictures in {len(stats)} rooms: " + ", ".join(f"{r} {v['views']}" for r, v in sorted(stats.items(), key=lambda kv: -kv[1]['views'])))
    if "--dry" in argv:
        print(json.dumps(stats, indent=1))
        return 0
    host = os.environ.get("G2_PI", "")
    if not host:
        print("G2_PI is not set: nothing sent")
        return 1
    base = "cd ~/bittleX && PYTHONPATH=. pi_pipeline/.venv/bin/python -m pi_pipeline.memory place import"
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, base], input=json.dumps(stats), capture_output=True, text=True, timeout=60)
    print((r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else f"exit {r.returncode}")
    if r.returncode != 0:
        return 1
    g = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "cat ~/.local/share/g2/places.json"], capture_output=True, text=True, timeout=60)
    if g.returncode == 0 and g.stdout.strip():
        OUT.write_text(g.stdout)
        print(f"copied his places memory to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
