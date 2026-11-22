"""What did the newest run do? (`g2lastrun`, runs on the Pi, read-only.) One look at the newest scripted, arm-skill or catapult run logs in `~/g2_runs/`: the verdict, tilt, pack, and for a script whether the board took it.

A body verdict of `ok` only says G2 did not tip; it does not say the movement played (2026-11-21: a script the board never took still read `ok`). So for a script the summary says what the board answered after the script was sent
(`board_after_send`, recorded by `scripted_skill`: a `K` means it was taken) and, when it was not taken or the field is missing, says so plainly. Nothing here moves G2 or writes anything.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time

DIRS = ("scripts", "arm_skills", "catapult")


def newest(n: int = 1, root: str | None = None) -> list:
    root = root or os.path.expanduser("~/g2_runs")
    files = [f for d in DIRS for f in glob.glob(os.path.join(root, d, "*.json"))]
    return sorted(files, key=os.path.getmtime, reverse=True)[:max(1, n)]


def describe(path: str, now: float | None = None) -> list:
    """The lines about one run log (a list of strings). Never raises: an unreadable log says so."""
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        return [f"{os.path.basename(path)}: could not read ({e})"]
    now = time.time() if now is None else now
    age = max(0, int(now - os.path.getmtime(path))) if os.path.exists(path) else 0
    out = [f"{os.path.basename(path)} ({age // 60} min {age % 60} s ago)"]
    out.append(f"  verdict {d.get('verdict')}: pitch {d.get('max_pitch_dev')} and roll {d.get('max_roll_dev')} degrees from where he stood, fell {d.get('fell')}")
    pack = d.get("pack_pct")
    if pack is not None:
        after = d.get("pack_pct_after")
        out.append(f"  pack {pack}%" + (f" before, {after}% after" if after is not None else " at the gate"))
    if "script" in d:
        extra = []
        if d.get("picked_first"):
            extra.append(f"pickF first, pause {d.get('pick_gap_s', 'not recorded')} s")
        extra.append("gyro off" if d.get("gyro_off") else "gyro default")
        out.append(f"  script {d.get('script')} at amount {d.get('amount')}: " + ", ".join(extra))
        if "board_after_send" not in d:
            out.append("  the board's answer after the send was not recorded (a run before that logging): the verdict alone does not show the script played")
        elif "K" in d["board_after_send"]:
            out.append(f"  the board took the script (it answered K): {d['board_after_send']}")
        else:
            out.append(f"  NO K from the board after the send ({d['board_after_send'] or 'nothing'}): the script was probably NOT taken, whatever the verdict says")
    g = d.get("grip_look")
    if g:
        out.append("  grip look: " + (f"no picture ({g['error']})" if "error" in g else f"{g['verdict']} (colour block {g['n']} px, centre column {g['cx']} row {g['cy']}), picture {g.get('file', 'not saved')}"))
    if d.get("claw_joint_after") is not None:
        out.append(f"  claw reading before {d.get('claw_joint_before')} and after {d.get('claw_joint_after')} (part-open can mean an object is held; the board reports commanded angles)")
    if d.get("note") or d.get("landing"):
        out.append(f"  noted by the person: {d.get('note') or d.get('landing')}")
    return out


def main(argv: list | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    n = int(argv[0]) if argv and argv[0].isdigit() else 1
    files = newest(n)
    if not files:
        print("no run logs found in ~/g2_runs/scripts, arm_skills or catapult")
        return
    for f in files:
        print("\n".join(describe(f)))


if __name__ == "__main__":
    main()
