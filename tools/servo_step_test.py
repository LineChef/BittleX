#!/usr/bin/env python3
"""Measure one servo's real speed (backlog H13) over the BiBoard's USB serial, using the firmware's `f` position feedback.

    pi_pipeline/.venv/bin/python tools/servo_step_test.py [--port /dev/cu.usbmodem...] [--joint FL-sh] [--start 30 --end 70] [--repeats 3]
                                    [--out ~/g2_runs/servo_step_FL-sh.csv]

The feedback stream is only ~5 rows/s, too slow for one step, so the step is repeated and the first `f` is sent a different delay after
each move command (0 .. 190 ms in 10 ms steps by default); pooled, the samples trace the move (pi_pipeline/gait/servo_step.py explains
the fit). Prints the fitted rate in deg/s: ~250 means the servo keeps up with the firmware's own easing (2 deg per 8 ms); the sim
assumes 137.

SAFETY (user rules): G2 is held UPRIGHT in the air by hand, legs free, never on its back, with balance off; or standing on the floor
for a loaded run (--label loaded). Only the chosen joint moves, between --start and --end. Run it for a shoulder AND a knee, up and down
(the script does both directions), on a charged pack (a sagging pack slows the servos and would blur the answer).
Servos 8..15 = FL, FR, BR, BL shoulders, then FL, FR, BR, BL knees. Shoulder stand = 50 deg, knee stand = 0 deg.
Also worth filming on a phone in slow motion as a cross-check.
"""
import argparse
import csv
import os
import sys
import time

import numpy as np
import serial

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pi_pipeline.gait import servo_step  # noqa: E402

STAND = "i8 50 12 0 9 50 13 0 10 50 14 0 11 50 15 0"
NAMES = ["FL-sh", "FR-sh", "BR-sh", "BL-sh", "FL-kn", "FR-kn", "BR-kn", "BL-kn"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbmodem5AA90271591")
    ap.add_argument("--joint", default="FL-sh", choices=NAMES)
    ap.add_argument("--start", type=float, default=None, help="deg (default 30 for a shoulder, -20 for a knee)")
    ap.add_argument("--end", type=float, default=None, help="deg (default 70 for a shoulder, 30 for a knee)")
    ap.add_argument("--also", default=None, choices=NAMES,
                    help="move this second joint at the SAME instant with the same angles (e.g. --joint FL-sh --also FR-sh); each joint is fitted "
                         "separately, so a joint that lags its mirror shows up as a larger lag / lower rate")
    ap.add_argument("--no-stand", action="store_true",
                    help="do not send the whole stand pose first or rest at the end: only the chosen joint(s) are ever commanded (G2 held in the air)")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--label", default="unloaded", help="free text saved in the CSV: unloaded / loaded")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    j = NAMES.index(args.joint)
    idx = 8 + j
    j2 = NAMES.index(args.also) if args.also else None
    idx2 = 8 + j2 if j2 is not None else None
    if j2 is not None and (j2 < 4) != (j < 4):
        raise SystemExit("--also must be the same kind of joint (both shoulders or both knees): the angles are shared")
    a = args.start if args.start is not None else (30.0 if j < 4 else -20.0)
    b = args.end if args.end is not None else (70.0 if j < 4 else 30.0)
    out = args.out or os.path.expanduser(f"~/g2_runs/servo_step_{args.joint}{'+' + args.also if args.also else ''}_{args.label}.csv")
    both = lambda angle: f"i{idx} {angle:g}" + (f" {idx2} {angle:g}" if idx2 is not None else "")
    delays = [d / 1000.0 for d in range(0, 200, 10)]

    s = serial.Serial(args.port, 115200, timeout=0.01)
    time.sleep(4.5)
    s.read(20000)
    buf = b""
    tx = lambda c: s.write((c + "\n").encode())

    def rows_until(deadline, want=None):
        """Parse 8-value feedback rows; returns [(arrival_monotonic, [8 values])]."""
        nonlocal buf
        got = []
        while time.monotonic() < deadline and (want is None or len(got) < want):
            buf += s.read(400)
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                try:
                    v = [float(x) for x in line.decode("utf8", "replace").split("\t") if x.strip()]
                except ValueError:
                    continue
                if len(v) == 8:
                    got.append((time.monotonic(), v))
        return got

    def settle(angle):
        tx(both(angle))
        rows_until(time.monotonic() + 1.4)
        buf_clear()

    def buf_clear():
        nonlocal buf
        buf = b""
        s.reset_input_buffer()

    tx("gb")
    rows_until(time.monotonic() + 0.5)
    if not args.no_stand:
        tx(STAND)
        rows_until(time.monotonic() + 3.0)
    print(f"{args.joint}: {a:g} <-> {b:g} deg, {args.repeats} repeats x {len(delays)} delays x 2 directions "
          f"(about {int(args.repeats * len(delays) * 2 * 3.3)} s)")

    trials = {"up": [], "down": []}
    trials2 = {"up": [], "down": []}                    # the --also joint
    for rep in range(args.repeats):
        for d in delays:
            for name, (p0, p1) in (("up", (a, b)), ("down", (b, a))):
                settle(p0)
                t0 = time.monotonic()
                tx(both(p1))
                rows_until(t0 + d)                      # (nothing should arrive before `f`; drains stray rows)
                buf_clear()
                tx("f")
                got = rows_until(t0 + d + 1.0, want=5)  # ~5 rows/s: the first few trace the end of the move
                trials[name].append([(t - t0, v[j]) for t, v in got])
                if j2 is not None:
                    trials2[name].append([(t - t0, v[j2]) for t, v in got])
    tx(both(50 if j < 4 else 0))
    rows_until(time.monotonic() + 1.0)
    if not args.no_stand:
        tx("d")
    s.close()

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["joint", "label", "direction", "start", "end", "t_s", "reading_deg"])
        for jn, tdict in ((args.joint, trials), (args.also, trials2)):
            if jn is None:
                continue
            for name, ts in tdict.items():
                p0, p1 = (a, b) if name == "up" else (b, a)
                for tr in ts:
                    for t, v in tr:
                        w.writerow([jn, args.label, name, p0, p1, f"{t:.4f}", f"{v:.2f}"])
    print(f"samples -> {out}")
    for jn, tdict in ((args.joint, trials), (args.also, trials2)):
        if jn is None:
            continue
        for name, ts in tdict.items():
            p0, p1 = (a, b) if name == "up" else (b, a)
            try:
                r = servo_step.fit_rate(servo_step.pool(ts), p0, p1)
            except ValueError as e:
                print(f"  {jn} {name}: {e}")
                continue
            ends = [v for tr in ts for t, v in tr if t > 0.9]
            end_txt = f", settles at {np.median(ends):.1f} deg" if ends else ""
            print(f"  {jn:6s} {name:4s} {p0:g} -> {p1:g}: rate {r['rate_deg_s']:.0f} deg/s, lag {r['lag_s'] * 1000:.0f} ms, "
                  f"fit rms {r['rms_deg']:.1f} deg, {r['n']} samples{end_txt}   (firmware easing {servo_step.FIRMWARE_EASE_DEG_S:.0f}, sim assumes 137)")


if __name__ == "__main__":
    main()
