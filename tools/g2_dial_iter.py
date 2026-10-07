#!/usr/bin/env python3
"""One logged heading-hold (or fixed stride difference) walk on G2's Pi, then print the analysis: the loop for dialling the steering correction in
(docs/rl/real-walk-log.md "The stride-difference lever has the opposite sign..."). Needs G2_PI; run with pi_pipeline/.venv/bin/python or any python3.

    tools/g2_dial_iter.py hold  N FF KP KI UMAX     # closed loop: feed-forward FF, gains KP / KI, output limit UMAX (u < 0 = longer RIGHT strides = a left turn)
    tools/g2_dial_iter.py const N U                  # no feedback: a fixed stride difference U

N numbers the run (it names the log dial3_iNN / dial3_cNN; reuse a number and the new log is picked by the newest file). Starts the run through tools/g2_baseline.sh
(g2-voice is stopped for it and restarted after), waits, copies the CSV to docs/rl/v3-data/dial3/ and prints the final heading change (+ = right) with the heading at
2 / 4 / ... 12 s and the controller output u. The spoken warning gives about 8 s to put G2 on the floor. Ask whoever is with G2 what they SAW (left / right / straight)
and compare: a log that disagrees with the eyes means the run was handled (the yaw jumps when G2 is picked up) or the yaw is unreliable.
"""
import glob
import math
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    mode, n = sys.argv[1], sys.argv[2]
    if mode == "hold":
        ff, kp, ki, umax = sys.argv[3:7]
        label = f"dial3_i{int(n):02d}"
        args = ["--hold", "on", f"--hold-ff={ff}", "--hold-kp", kp, "--hold-ki", ki, "--hold-umax", umax]
        desc = f"hold ff={ff} kp={kp} ki={ki} umax={umax}"
    else:
        label = f"dial3_c{int(n):02d}"
        args = [f"--const-u={sys.argv[3]}", "--hold-umax", "0.4"]
        desc = f"fixed u={sys.argv[3]}"
    subprocess.run(["bash", f"{ROOT}/tools/g2_baseline.sh", "start", "1", label] + args + ["--lead-s", "14"], capture_output=True, text=True, cwd=ROOT)
    time.sleep(5)
    t0 = time.time()
    while time.time() - t0 < 120:
        st = subprocess.run(["bash", f"{ROOT}/tools/g2_baseline.sh", "status"], capture_output=True, text=True, cwd=ROOT).stdout.split()
        if st and st[0] == "inactive":
            break
        time.sleep(2)
    out_dir = f"{ROOT}/docs/rl/v3-data/dial3"
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(f'scp -q "$G2_PI:~/g2_runs/{label}_*.csv" {out_dir}/', shell=True, cwd=ROOT)
    f = sorted(glob.glob(f"{out_dir}/{label}_*.csv"), key=os.path.getmtime)[-1]
    T, Y, U = [], [], []
    for line in open(f):
        if line[0] in "#t" or not line.strip():
            continue
        c = line.strip().split(",")
        if len(c) < 21:
            continue
        T.append(float(c[0])); Y.append(float(c[3])); U.append(float(c[20]))
    if not T:
        print(f"{label}: no usable rows (G2 tilted / fell at the start?) -> {f}")
        return
    un, prev, off = [], Y[0], 0.0
    for y in Y:
        d = y - prev
        if d > math.pi:
            off -= 2 * math.pi
        elif d < -math.pi:
            off += 2 * math.pi
        un.append(math.degrees(y + off)); prev = y
    h = [x - un[0] for x in un]
    pts = " ".join("%+4.0f" % h[min(range(len(T)), key=lambda k: abs(T[k] - t))] for t in (2, 4, 6, 8, 10, 12))
    print(f"{label} {desc}: FINAL {h[-1]:+.0f} deg | heading@2,4,6,8,10,12 s: {pts} | max right {max(h):+.0f} max left {min(h):+.0f} | "
          f"u mean {sum(U) / len(U):+.3f} min {min(U):+.3f} max {max(U):+.3f} last {U[-1]:+.3f}")


if __name__ == "__main__":
    main()
