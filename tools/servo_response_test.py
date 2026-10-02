#!/usr/bin/env python3
"""Servo response test over the BiBoard's USB serial, using the firmware's `f` position feedback.

CAUTION (2026-10-02): `cmd()` restarts the feedback stream with `f` only 0.15 s after each move command, and a new
token interrupts a move in progress, so the stand/rest transitions here get cut short. Use servo_static_test.py for
trustworthy offsets/gains; fix this script (wait for the move to finish before `f`) before relying on it.

    python tools/servo_response_test.py [--port /dev/cu.usbmodem...] [--out ~/g2_runs/servo_resp.csv]

`f` starts a continuous feedback stream (~5 rows/s, 8 values = servos 8..15: FL, FR, BR, BL shoulders
then FL, FR, BR, BL knees). G2 must be standing on the floor, clear of obstacles, with the Mac cable
the only tether. Phases, with the firmware gyro balance off (`gb`):
  baseline   stand pose, 3 s
  to_rest    stand -> `d` (rest), 4 s       reproduces "lag in the rest position"
  to_stand   rest -> stand, 4 s
  step_<leg> each shoulder alone 50 -> 70 -> 50 deg, 2.5 s each way (FL, FR, BR, BL)
Writes every feedback row with its arrival time (+-0.05 s) and prints per-joint summaries and
left-right comparisons. A row every ~0.2 s cannot resolve a lag under ~0.2 s; it shows slow
settling, offsets and overshoot.
"""
import argparse
import os
import sys
import time

import numpy as np
import serial

STAND = "i8 50 12 0 9 50 13 0 10 50 14 0 11 50 15 0"
NAMES = ["FL-sh", "FR-sh", "BR-sh", "BL-sh", "FL-kn", "FR-kn", "BR-kn", "BL-kn"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbmodem5AA90271591")
    ap.add_argument("--out", default=os.path.expanduser("~/g2_runs/servo_response.csv"))
    ap.add_argument("--amp", type=float, default=20.0, help="shoulder step amplitude, deg")
    args = ap.parse_args()
    s = serial.Serial(args.port, 115200, timeout=0.02)
    time.sleep(4.5)
    s.read(20000)
    s.reset_input_buffer()
    rows, buf, phase = [], b"", "boot"
    t0 = time.monotonic()

    def pump(sec):
        nonlocal buf
        end = time.monotonic() + sec
        while time.monotonic() < end:
            buf += s.read(400)
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                parts = line.decode("utf8", "replace").split("\t")
                try:
                    v = [float(x) for x in parts if x.strip()]
                except ValueError:
                    continue
                if len(v) == 8:
                    rows.append((time.monotonic() - t0, phase, *v))

    def tx(c):
        s.write((c + "\n").encode())

    def cmd(c):
        """Send a command, then restart the feedback stream (any new command stops it)."""
        tx(c)
        pump(0.15)
        tx("f")

    tx("gb"); pump(0.5)                      # firmware balance off
    tx(STAND); pump(2.5)
    tx("f"); pump(1.0)                       # start the feedback stream
    phase = "baseline"; pump(3.0)
    phase = "to_rest"; cmd("d"); pump(4.0)
    phase = "to_stand"; cmd(STAND); pump(4.0)
    for leg, idx in (("FL", 8), ("FR", 9), ("BR", 10), ("BL", 11)):
        phase = f"step_{leg}_up"; cmd(f"i{idx} {50 + args.amp:g}"); pump(2.5)
        phase = f"step_{leg}_down"; cmd(f"i{idx} 50"); pump(2.5)
    tx("d"); pump(0.5); s.close()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        f.write("t,phase," + ",".join(f"v{i}" for i in range(8, 16)) + "\n")
        for r in rows:
            f.write(f"{r[0]:.3f},{r[1]}," + ",".join(f"{x:.1f}" for x in r[2:]) + "\n")
    print(f"{len(rows)} feedback rows -> {args.out}")
    summarize(rows)


def summarize(rows):
    ph = {}
    for r in rows:
        ph.setdefault(r[1], []).append(r)
    def arr(p):
        return np.array([r[2:] for r in ph[p]]), np.array([r[0] for r in ph[p]])
    if "baseline" in ph:
        a, _ = arr("baseline")
        print("\nSTAND baseline (mean, noise):", "  ".join(f"{n} {m:+.1f}({sd:.1f})" for n, m, sd in zip(NAMES, a.mean(0), a.std(0))))
        m = a.mean(0)
        print(f"  left-right: shoulders FL-FR {m[0]-m[1]:+.1f}  BL-BR {m[3]-m[2]:+.1f} | knees FL-FR {m[4]-m[5]:+.1f}  BL-BR {m[7]-m[6]:+.1f}")
    for p in ("to_rest", "to_stand"):
        if p not in ph:
            continue
        a, t = arr(p)
        t = t - t[0]
        fin = a[-3:].mean(0)
        sett = []
        for j in range(8):                     # time until within 3 deg of the final value and staying there
            off = np.abs(a[:, j] - fin[j]) > 3.0
            idx = np.where(off)[0]
            sett.append(t[idx[-1] + 1] if len(idx) and idx[-1] + 1 < len(t) else (0.0 if not len(idx) else t[-1]))
        print(f"\n{p}: final  " + "  ".join(f"{n} {v:+.0f}" for n, v in zip(NAMES, fin)))
        print(f"{p}: settle time s (within 3 deg of final)  " + "  ".join(f"{n} {x:.1f}" for n, x in zip(NAMES, sett)))
    for leg, j in (("FL", 0), ("FR", 1), ("BR", 2), ("BL", 3)):
        for d in ("up", "down"):
            p = f"step_{leg}_{d}"
            if p in ph:
                a, t = arr(p)
                x = a[:, j]
                print(f"{p}: start {x[0]:+.1f} end {x[-3:].mean():+.1f} peak {x.max():+.1f} min {x.min():+.1f}  rows {len(x)}")


if __name__ == "__main__":
    main()
