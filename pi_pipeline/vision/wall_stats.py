"""Statistics from the wall and detection logs (user, 2026-10-10: "how often something is seen and when", and walls with the distance we think they are at, for debugging).

    python -m pi_pipeline.vision.wall_stats [--days N]          # default: everything in the logs

Reads `~/.local/share/g2/wall_dryrun.jsonl` (one line per wall look: state clear / far / near / blocked, nearest distance in inches, per column group distances, the turn it would
make, the exploration mode, and a picture name for near / blocked looks in `wall_pics`) and `~/g2_runs/detections/YYYYMMDD.jsonl` (animal detections: label, outcome, score).
Prints in inches, never changes anything."""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

from .wall_distance import LOG_PATH

DETECTION_DIR = os.path.expanduser(os.environ.get("G2_DETECTION_LOG_DIR", "~/g2_runs/detections"))
BUCKETS = ((8, "8 in or less"), (12, "8 to 12 in"), (16, "12 to 16 in"), (24, "16 to 24 in"), (40, "24 to 40 in"), (1e9, "over 40 in"))


def _rows(path, since: float | None, key: str):
    out = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                t = r.get(key)
                if since is not None and t:
                    try:
                        ts = time.mktime(time.strptime(t[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S"))
                    except ValueError:
                        continue
                    if ts < since:
                        continue
                out.append(r)
    except OSError:
        pass
    return out


def wall_summary(rows: list) -> dict:
    """Counts and distances from wall log rows (old rows without inches are converted from centimetres)."""
    states = Counter(r.get("state") or ("blocked" if r.get("blocked") else "clear" if r.get("nearest_cm") is None else "?") for r in rows)
    inches = [r["nearest_in"] if r.get("nearest_in") is not None else round(r["nearest_cm"] / 2.54, 1) for r in rows if r.get("nearest_in") is not None or r.get("nearest_cm") is not None]
    hist = Counter()
    for v in inches:
        for top, name in BUCKETS:
            if v <= top:
                hist[name] += 1
                break
    by_hour = defaultdict(Counter)
    for r in rows:
        by_hour[(r.get("t") or "?")[:13]][r.get("state") or "?"] += 1
    streaks, cur = [], []
    for r in rows:                                                      # a streak = consecutive near / blocked looks (a wall he stayed in front of)
        if r.get("state") in ("near", "blocked"):
            cur.append(r)
        elif cur:
            streaks.append(cur); cur = []
    if cur:
        streaks.append(cur)
    return {"looks": len(rows), "states": dict(states), "distance_hist": dict(hist), "turns": dict(Counter(r.get("turn") for r in rows if r.get("turn"))),
            "uncalibrated": sum(1 for r in rows if r.get("calibrated") is False or "uncalibrated" in str(r.get("reason", ""))),
            "near_streaks": [(s[0].get("t"), len(s), min((x.get("nearest_in") or 0) for x in s)) for s in streaks],
            "by_hour": {h: dict(c) for h, c in sorted(by_hour.items())},
            "pictures": [r["pic"] for r in rows if r.get("pic")][-5:]}


def detection_summary(rows: list) -> dict:
    """How often each label was seen, and what happened to it (kept or filtered), per hour."""
    per_label = Counter((r.get("label"), r.get("outcome")) for r in rows)
    by_hour = defaultdict(Counter)
    for r in rows:
        by_hour[(r.get("time") or "?")[:13]][r.get("label")] += 1
    return {"detections": len(rows), "per_label_outcome": {f"{k[0]} {k[1]}": v for k, v in sorted(per_label.items(), key=lambda kv: -kv[1])},
            "by_hour": {h: dict(c) for h, c in sorted(by_hour.items())}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=None, help="only the last N days")
    a = ap.parse_args(argv)
    since = None if a.days is None else time.time() - a.days * 86400
    w = wall_summary(_rows(LOG_PATH, since, "t"))
    print(f"WALL LOOKS: {w['looks']} ({w['uncalibrated']} before calibration)")
    for k, v in sorted(w["states"].items()):
        print(f"  {k:8s} {v}")
    if w["distance_hist"]:
        print("nearest wall (inches):")
        for _, name in BUCKETS:
            if name in w["distance_hist"]:
                print(f"  {name:14s} {w['distance_hist'][name]}")
    if w["turns"]:
        print("turns it would make:", ", ".join(f"{k} {v}" for k, v in w["turns"].items()))
    if w["near_streaks"]:
        print("times he stayed near a wall (start, looks, closest in):")
        for t, n, c in w["near_streaks"][-8:]:
            print(f"  {t}  {n} looks, closest {c:g} in")
    if w["pictures"]:
        print("latest saved pictures (~/.local/share/g2/wall_pics):", ", ".join(w["pictures"]))
    rows = []
    for f in sorted(Path(DETECTION_DIR).glob("*.jsonl")):
        rows += _rows(f, since, "time")
    d = detection_summary(rows)
    print(f"DETECTIONS: {d['detections']}")
    for k, v in list(d["per_label_outcome"].items())[:10]:
        print(f"  {k:30s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
