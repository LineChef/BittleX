#!/usr/bin/env python3
"""Read G2's joint angles over USB from the Mac and say whether the legs are symmetric (the BiBoard plugged into the Mac; the Pi off or not using the port). Moves legs only with --poses.

    python tools/g2_pose_read.py --suspended              # read what the board reports now (`j`), no move
    python tools/g2_pose_read.py --suspended --poses kbalance,kcalib   # command each pose, wait, read; ends with `d` (rest)
    python tools/g2_pose_read.py --at-rest                # same read with him lying in rest

Made from the three scratch scripts of 2026-11-19, which opened a port another program held and read values that were not trusted. It REFUSES to run when
  * another program has the port (`lsof`: the Petoi calibrator, a serial monitor, the voice service on the Pi side is not on this port), or
  * you did not say where he is: `--suspended` or `--at-rest` is required (never on his feet without hands near: opening the port can reset the board, and the firmware may move him).
`j` reports the angles the board last COMMANDED, not where the servos are (a sag cannot show), and reads all zeros before any pose was sent. Left and right are compared per leg pair (shoulder and
knee, front and rear) within --tol degrees; two poses that read identical are flagged as "the pose did not change". Not the stand-up path: poses go through SerialLink, so a stand is the eased one. Needs the repo venv:
`PYTHONPATH=. pi_pipeline/.venv/bin/python tools/g2_pose_read.py ...` (the `g2pose` alias does it)."""
from __future__ import annotations

import argparse
import glob
import subprocess
import sys
import time

# servo index: front-left shoulder 8, front-right 9, rear-right 10, rear-left 11; knees 12 to 15 in the same order (pi_pipeline/link/kskill.py URDF_TO_SERVO)
PAIRS = (("front shoulder", 8, 9), ("front knee", 12, 13), ("rear shoulder", 11, 10), ("rear knee", 15, 14))      # (name, left, right)


def find_port() -> str | None:
    found = sorted(glob.glob("/dev/cu.usbmodem*"))
    return found[0] if found else None


def port_users(port: str) -> list[str] | None:
    """The programs that hold the port open (`lsof`), [] if none, None when lsof cannot say."""
    try:
        r = subprocess.run(["lsof", "-t", port], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    pids = r.stdout.split()
    out = []
    for pid in pids:
        try:
            name = subprocess.run(["ps", "-p", pid, "-o", "comm="], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            name = "?"
        out.append(f"{name} (pid {pid})")
    return out


def symmetry(joints: list | None, tol: float = 3.0) -> dict:
    """{"state": "blank"|"unread"|"ok"|"off", "pairs": [(name, left, right, diff)], "off": [names]} for the 16 joint angles `j` gave."""
    if not joints or len(joints) < 16:
        return {"state": "unread", "pairs": [], "off": []}
    if all(v == 0 for v in joints):
        return {"state": "blank", "pairs": [], "off": []}                     # the board's start state: no pose commanded yet, the zeros say nothing
    pairs = [(n, joints[a], joints[b], abs(joints[a] - joints[b])) for n, a, b in PAIRS]
    off = [n for n, _l, _r, d in pairs if d > tol]
    return {"state": "off" if off else "ok", "pairs": pairs, "off": off}


def describe(tag: str, joints: list | None, tol: float = 3.0, previous: list | None = None) -> list[str]:
    s = symmetry(joints, tol)
    out = [f"{tag}: {joints}"]
    if s["state"] == "unread":
        return out + ["  no reading (the board did not answer): could not verify"]
    if s["state"] == "blank":
        return out + ["  all zeros: the board has no pose yet (nothing was commanded since it started); this says nothing about the legs"]
    for n, left, right, d in s["pairs"]:
        out.append(f"  {n}: left {left} right {right}  {'ok' if d <= tol else 'DIFFERENT by ' + str(d)}")
    out.append("  symmetric within %.0f deg" % tol if s["state"] == "ok" else "  NOT symmetric: " + ", ".join(s["off"]))
    if previous is not None and previous == joints:
        out.append("  identical to the pose before: the pose may not have changed (the read may be stale); do not trust it as this pose")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Read G2's joint angles over USB and compare left and right.")
    ap.add_argument("--suspended", action="store_true", help="he is held off the ground (required unless --at-rest)")
    ap.add_argument("--at-rest", action="store_true", help="he is lying in the rest position")
    ap.add_argument("--poses", default="", help="comma list of poses to command and read, e.g. kbalance,kcalib (moves the legs)")
    ap.add_argument("--port", default=None)
    ap.add_argument("--tol", type=float, default=3.0, help="largest left/right difference counted as symmetric, degrees")
    args = ap.parse_args()
    if not (args.suspended or args.at_rest):
        sys.exit("refused: say where he is with --suspended or --at-rest (opening the port can reset the board; never with him on his feet)")
    port = args.port or find_port()
    if not port:
        sys.exit("no /dev/cu.usbmodem* port: is the BiBoard plugged into the Mac?")
    users = port_users(port)
    if users:
        sys.exit(f"refused: {port} is held by {', '.join(users)}. Close it first (the Petoi calibrator, a serial monitor), then run this again")
    if users is None:
        print("could not check who holds the port (lsof did not answer); going on")
    from pi_pipeline.link import kskill
    from pi_pipeline.link.serial_link import SerialLink
    link = SerialLink(port, 115200)
    prev = None
    try:
        time.sleep(1.5)
        poses = [p.strip() for p in args.poses.split(",") if p.strip()]
        j = kskill.read_joints(link)
        print("\n".join(describe("as the board is", j, args.tol)))
        prev = j
        for tok in poses:
            link.send(tok, read_reply=False)
            time.sleep(5.0)
            j = kskill.read_joints(link)
            print("\n".join(describe(tok, j, args.tol, previous=prev)))
            prev = j
    finally:
        if args.poses:
            link.send("d", read_reply=False)                 # always end at rest after commanding poses
            time.sleep(2.0)
            print("rest sent")
        link.close()


if __name__ == "__main__":
    main()
