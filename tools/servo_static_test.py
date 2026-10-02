#!/usr/bin/env python3
"""Per-joint static offset/gain check using the firmware's `f` position feedback (BiBoard USB).

    python tools/servo_static_test.py [--port /dev/cu.usbmodem...] [--out ~/g2_runs/servo_static.csv]

G2 stands on the floor (balance off). Each leg joint in turn is commanded alone to a few angles,
given time to settle, then the feedback is averaged for 1.5 s (the stream is restarted with `f` after
each settled move, since any new command stops it). Prints reading - command per point and a
least-squares gain/offset per joint. A joint whose offset or gain differs from its mirror /
neighbours is miscalibrated, slipped on its horn, or binding. Servos 8..15 = FL, FR, BR, BL shoulders,
then FL, FR, BR, BL knees (confirmed 2026-10-02 by watching which leg moved).
"""
import argparse
import os
import time

import numpy as np
import serial

STAND = "i8 50 12 0 9 50 13 0 10 50 14 0 11 50 15 0"
NAMES = ["FL-sh", "FR-sh", "BR-sh", "BL-sh", "FL-kn", "FR-kn", "BR-kn", "BL-kn"]
SHOULDER_PTS, KNEE_PTS = (35, 50, 65), (-15, 0, 15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbmodem5AA90271591")
    ap.add_argument("--out", default=os.path.expanduser("~/g2_runs/servo_static.csv"))
    args = ap.parse_args()
    s = serial.Serial(args.port, 115200, timeout=0.02)
    time.sleep(4.5)
    s.read(20000)
    buf = b""
    tx = lambda c: s.write((c + "\n").encode())

    def sample(sec):
        nonlocal buf
        rows, end = [], time.monotonic() + sec
        while time.monotonic() < end:
            buf += s.read(400)
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                try:
                    v = [float(x) for x in line.decode("utf8", "replace").split("\t") if x.strip()]
                except ValueError:
                    continue
                if len(v) == 8:
                    rows.append(v)
        return np.array(rows)

    def measure():
        tx("f")
        sample(0.6)                                  # let the stream start
        a = sample(1.5)
        return a.mean(0) if len(a) else np.full(8, np.nan)

    tx("gb"); sample(0.5)
    tx(STAND); sample(3.0)
    base = measure()
    results = {}                                     # joint -> [(cmd, reading)]
    for j in range(8):
        idx = 8 + j
        pts = SHOULDER_PTS if j < 4 else KNEE_PTS
        results[j] = []
        for ang in pts:
            tx(f"i{idx} {ang}"); sample(1.2)         # move + settle, no `f` in between
            results[j].append((ang, measure()[j]))
        tx(f"i{idx} {50 if j < 4 else 0}"); sample(1.2)
    tx("d"); sample(0.5); s.close()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        f.write("joint,command,reading\n")
        for j, pts in results.items():
            for c, r in pts:
                f.write(f"{NAMES[j]},{c},{r:.2f}\n")
    print("baseline reading with every joint at the stand pose (shoulders 50, knees 0):")
    print("  " + "  ".join(f"{n} {v:+.1f}" for n, v in zip(NAMES, base)))
    print("\njoint    command -> reading (reading - command) ... | gain   offset")
    for j, pts in results.items():
        c = np.array([p[0] for p in pts], float)
        r = np.array([p[1] for p in pts], float)
        g, o = np.polyfit(c, r, 1)
        print(f"{NAMES[j]:6s}  " + "  ".join(f"{int(a):+d}->{b:+.1f}({b - a:+.1f})" for a, b in pts) + f" | {g:.2f}  {o:+.1f}")


if __name__ == "__main__":
    main()
