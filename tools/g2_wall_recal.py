#!/usr/bin/env python3
"""Rebuild the wall-distance calibration from a protected calibration set and score it against the one now in use (Mac only; nothing is sent to the Pi, nothing is overwritten).

    python tools/g2_wall_recal.py SET [--current PATH] [--roam DIR] [--out PATH]

The chain `docs/STATUS.md` plan item 5 described by hand: (1) verify the set's hashes (a changed set is refused), (2) build a candidate calibration from its `wall_straight` shots with the arm
attachment (the floor strip rows differ with the arm: a replay without `G2_ATTACHMENT=arm` scored the wrong band on 2026-11-18, so it is set here), (3) score the calibration now in use and the
candidate the same way (`wall_replay.score`: of the set's own wall shots how many are acted on by distance band, and of the roam pictures you labelled `nothing` how many are wrongly acted on),
(4) print both and say which is better. The candidate goes to `--out` (default ~/g2_wall_cal_candidates/SET.json), never over the live file. Putting it on the Pi is a write to the Pi: ask the owner.
`--current` is a copy of the Pi's `~/.local/share/g2/wall_calibration.json`; left out, it is read over ssh (G2_PI) and "could not verify" is printed if the Pi is off. SET is looked up in
~/g2_wall_calibration (as on the Pi) and in ~/Desktop/G2Memory/g2_pictures/wall_calibration (the Mac copy). Needs the repo venv: `g2wallrecal SET` does that."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HOME = Path.home()
SET_ROOTS = (HOME / "g2_wall_calibration", HOME / "Desktop/G2Memory/g2_pictures/wall_calibration")
ROAM_DIR = HOME / "Desktop/G2Memory/g2_pictures/wall"
LIVE_ON_PI = "~/.local/share/g2/wall_calibration.json"


def find_set(name: str) -> Path | None:
    for root in SET_ROOTS:
        p = root / name
        if p.is_dir():
            return p
    return None


def count(text: str) -> tuple[int, int]:
    """(hits, total) from a score string like "3 of 5"."""
    m = re.match(r"\s*(\d+) of (\d+)", str(text))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def verdict(before: dict, after: dict) -> str:
    """Which calibration is better, from two `wall_replay.score` dicts: a wall within 24 in must be acted on, and a picture labelled `nothing` must not be. The candidate wins only if it acts on at least as
    many walls in each band within 24 in AND has fewer false alarms; fewer false alarms with a missed wall is reported as a trade, never a win."""
    fa = "false alarms (labelled nothing, acted on)"
    wa = "wall acted on"
    nb, na = count(before[fa])[0], count(after[fa])[0]
    miss = [k for k in ("within 12 in", "13 to 24 in") if count(after[wa][k])[0] < count(before[wa][k])[0]]
    if miss:
        return f"TRADE: the candidate acts on fewer walls in {', '.join(miss)} ({nb} -> {na} false alarms): do not use it without looking at those shots"
    if na < nb:
        return f"BETTER: false alarms {nb} -> {na}, no wall within 24 in missed"
    if na == nb:
        return f"SAME: false alarms stay at {na}; the candidate is not an improvement"
    return f"WORSE: false alarms {nb} -> {na}"


def _current_cal_path(arg: str | None) -> str | None:
    if arg:
        return arg
    pi = os.environ.get("G2_PI")
    if not pi:
        return None
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", pi, f"cat {LIVE_ON_PI}"], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, prefix="g2_cal_now_")
    f.write(r.stdout)
    f.close()
    return f.name


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild the wall calibration from a protected set and score it against the live one.")
    ap.add_argument("set")
    ap.add_argument("--current", default=None, help="a copy of the Pi's wall_calibration.json (default: read over ssh)")
    ap.add_argument("--roam", default=str(ROAM_DIR), help="the wall picture folder with ring/ and roam_labels.json")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    os.environ["G2_ATTACHMENT"] = "arm"                        # BEFORE the vision modules are imported: the floor strip depends on it
    folder = find_set(a.set)
    if folder is None:
        sys.exit(f"no calibration set {a.set!r} in {', '.join(str(r) for r in SET_ROOTS)}: take one with g2calpic, then sync")
    from pi_pipeline.vision import wall_calibration_set as ws
    v = ws.verify(folder)
    if not v["ok"]:
        sys.exit(f"refused: the set {a.set} does not match its manifest ({v}); run python3 tools/g2_cal_verify.py")
    from pi_pipeline.vision import wall_distance as wd
    from pi_pipeline.vision import wall_replay as wr
    out = Path(a.out or HOME / "g2_wall_cal_candidates" / f"{a.set}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    cand, table = wd.calibrate_from_pictures(str(folder), save=True, path=str(out))
    if len(cand.points) < 2:
        sys.exit(f"the set gives {len(cand.points)} calibration point(s): it needs wall_straight shots at two or more distances")
    print(f"candidate from {a.set} ({v['files']} files, hashes ok): {len(cand.points)} points, saved to {out}")
    for d, row, used in table:
        print(f"  {d:g} in: row {row} from {len(used)} shot(s)")
    cur_path = _current_cal_path(a.current)
    cur = wd.Calibration.load(cur_path) if cur_path else None
    roam_labels = json.loads((Path(a.roam) / "roam_labels.json").read_text()) if (Path(a.roam) / "roam_labels.json").exists() else {}
    shots_c = wr.replay(str(folder), cand)
    roam_c = wr.replay_roam(a.roam, roam_labels, cand)
    after = wr.score(shots_c, roam_c)
    print("\ncandidate:")
    for k, val in after.items():
        print(f"  {k}: {val}")
    if cur is None:
        print("\ncould not verify the calibration now in use (no --current and the Pi did not answer): no comparison")
        return 3
    before = wr.score(wr.replay(str(folder), cur), wr.replay_roam(a.roam, roam_labels, cur))
    print("\nnow in use:")
    for k, val in before.items():
        print(f"  {k}: {val}")
    print("\n" + verdict(before, after))
    print(f"to use it: copy {out} to the Pi as {LIVE_ON_PI} (a write to the Pi: ask the owner), then a look is judged by it on the next start")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
