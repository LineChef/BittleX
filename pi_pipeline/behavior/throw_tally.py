"""The throw tally on the Mac (the basket goal, docs/plan-detail/basket-goal-plan.md, step 1): one row per throw with the distance and the sideways offset the person measures, and a summary per script and grip.

`~/.local/share/g2/throw_distances.csv` (outside the repo; `G2_THROW_TALLY` moves it). Columns: time, script, inches, pitch_deg, roll_deg, pack_pct, log, grip, then `side_in` (inches to the right of the aim line, negative = left), `note` and `grab` (the person's verdict on the claw's grab: good, marginal or bad); an older file
gets the columns added the first time a row is written. Runs on the Mac only: `g2throws add lob 24 --side -2 --grip "full cradle"`, `g2throws summary`. Reads nothing from G2.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import time

COLUMNS = ["time", "script", "inches", "pitch_deg", "roll_deg", "pack_pct", "log", "grip", "side_in", "note", "grab"]


def path() -> str:
    return os.environ.get("G2_THROW_TALLY") or os.path.expanduser("~/.local/share/g2/throw_distances.csv")


def read(p: str | None = None) -> list:
    p = p or path()
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return [{c: (r.get(c) or "") for c in COLUMNS} for r in csv.DictReader(f)]


def add(script: str, inches: float | None, *, side_in: float | None = None, grip: str = "", note: str = "", grab: str = "", pitch: str = "", roll: str = "", pack: str = "", log: str = "",
        p: str | None = None, now: str | None = None) -> dict:
    """Append one row (the file is rewritten with both new columns if it is an older one). Returns the row."""
    p = p or path()
    rows = read(p)
    row = {"time": now or time.strftime("%Y-%m-%d %-I:%M %p"), "script": script, "inches": "" if inches is None else f"{inches:g}", "pitch_deg": pitch, "roll_deg": roll, "pack_pct": pack,
           "log": log, "grip": grip, "side_in": "" if side_in is None else f"{side_in:g}", "note": note, "grab": grab}
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows + [row])
    return row


def _num(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summary(rows: list | None = None) -> list:
    """One dict per (script, grip) with the throws that have a distance: n, mean, lowest, highest, and the sideways offsets (n, mean, spread as the largest absolute value)."""
    rows = read() if rows is None else rows
    groups: dict = {}
    for r in rows:
        d = _num(r["inches"])
        if d is not None:
            groups.setdefault((r["script"], r["grip"]), []).append((d, _num(r["side_in"]), r.get("grab", "")))
    out = []
    for (script, grip), v in sorted(groups.items()):
        dist = [x[0] for x in v]
        side = [x[1] for x in v if x[1] is not None]
        grabs = {g: sum(1 for x in v if x[2] == g) for g in ("good", "marginal", "bad")}
        out.append({"script": script, "grip": grip, "n": len(dist), "mean": round(statistics.mean(dist), 1), "low": min(dist), "high": max(dist),
                    "side_n": len(side), "side_mean": round(statistics.mean(side), 1) if side else None, "side_max": max(abs(s) for s in side) if side else None,
                    "grabs": grabs, "by_grab": {g: round(statistics.mean([x[0] for x in v if x[2] == g]), 1) for g in grabs if grabs[g]}})
    return out


def main(argv: list | None = None) -> None:
    ap = argparse.ArgumentParser(description="The throw tally on the Mac: add a throw, or print the summary.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="add one throw")
    a.add_argument("script")
    a.add_argument("inches", type=float, nargs="?", help="how far it went (omit if not seen)")
    a.add_argument("--side", type=float, default=None, help="inches to the right of the aim line (negative = left)")
    a.add_argument("--grip", default="", help='for example "full cradle"')
    a.add_argument("--note", default="")
    a.add_argument("--grab", choices=("good", "marginal", "bad"), default="", help="the person's verdict on the claw's grab for this throw")
    sub.add_parser("summary", help="per script and grip: count, mean, range and the sideways offsets")
    args = ap.parse_args(argv)
    if args.cmd == "add":
        row = add(args.script, args.inches, side_in=args.side, grip=args.grip, note=args.note, grab=args.grab)
        print("added:", {k: v for k, v in row.items() if v})
        return
    for s in summary():
        side = f", sideways mean {s['side_mean']} in, up to {s['side_max']} in off ({s['side_n']} measured)" if s["side_n"] else ", sideways not measured"
        grab = (", by grab: " + ", ".join(f"{g} {s['grabs'][g]} (mean {s['by_grab'][g]} in)" for g in s["by_grab"])) if s["by_grab"] else ""
        print(f"{s['script']} ({s['grip'] or 'grip not noted'}): {s['n']} throws, mean {s['mean']} in, {s['low']:g} to {s['high']:g} in{side}{grab}")


if __name__ == "__main__":
    main()
