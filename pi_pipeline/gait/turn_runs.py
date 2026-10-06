"""A series of logged firmware turn runs (`kwkL`, `kwkR` alternating) to measure G2's real turn rate (run as `g2-turns` by tools/g2_turns.sh).

Each run is fw_skill_log.py (`kbalance` stand, the skill for --seconds with the IMU logged, rest). G2 speaks before each run and between runs so whoever is with him can put him
back on the hard floor with room to turn in a circle. `touch ~/.g2_turns_skip` after a prompt to skip the wait. The yaw sign is the firmware convention (+ = RIGHT), so
kwkL should come out negative and kwkR positive. Prints each run's turn rate and the mean per skill: the real-turn calibration target for the V3 plan's turning gate
(the calibrated sim has to turn the same gaits at >= 50% of these rates before the turn-command curriculum is trained).
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def yaw_rate_deg_s(path: str):
    """(deg/s, total deg, seconds) from a fw_skill_log CSV: a least-squares line through the unwrapped yaw (rad -> deg) against time."""
    ts, ys = [], []
    for line in open(path):
        if line.startswith("#") or line.startswith("t,") or not line.strip():
            continue
        c = line.split(",")
        ts.append(float(c[0]))
        ys.append(float(c[3]))
    if len(ts) < 5:
        return None
    unwrapped, prev, off = [], ys[0], 0.0
    for y in ys:
        d = y - prev
        if d > math.pi:
            off -= 2 * math.pi
        elif d < -math.pi:
            off += 2 * math.pi
        unwrapped.append(math.degrees(y + off))
        prev = y
    n = len(ts)
    mt, my = sum(ts) / n, sum(unwrapped) / n
    den = sum((t - mt) ** 2 for t in ts)
    slope = sum((t - mt) * (y - my) for t, y in zip(ts, unwrapped)) / den if den else 0.0
    return slope, unwrapped[-1] - unwrapped[0], ts[-1] - ts[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=6, help="total runs, alternating kwkL, kwkR, ...")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--label", default="turn_fw")
    ap.add_argument("--lead-s", type=float, default=15.0, help="spoken warning before a run")
    ap.add_argument("--reset-s", type=float, default=30.0, help="time to put G2 back between runs")
    args = ap.parse_args()

    from pi_pipeline.config import settings
    from pi_pipeline.voice.tts import make_tts

    tts = make_tts("piper", piper_model_path=settings.piper_model_path, style=settings.voice_style)
    out = os.path.expanduser("~/g2_runs")
    os.makedirs(out, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    skip = os.path.expanduser("~/.g2_turns_skip")
    results = {"kwkL": [], "kwkR": []}
    for k in range(1, args.runs + 1):
        token = "kwkL" if k % 2 == 1 else "kwkR"
        side = "left" if token == "kwkL" else "right"
        tts.speak(f"Turn run {k} of {args.runs}, turning {side}, in {int(args.lead_s)} seconds. Put me on the hard floor with room to turn.")
        time.sleep(max(0.0, args.lead_s - 6.0))
        path = os.path.join(out, f"{args.label}_{token}_{stamp}_run{k:02d}.csv")
        rc = subprocess.call([sys.executable, os.path.join(HERE, "fw_skill_log.py"), token, "--seconds", str(args.seconds), "--log", path])
        r = yaw_rate_deg_s(path) if os.path.exists(path) else None
        if r:
            results[token].append(r[0])
            print(f"run {k} {token}: exit {rc}  turn rate {r[0]:+.1f} deg/s (yaw change {r[1]:+.0f} deg over {r[2]:.1f} s) -> {path}", flush=True)
        else:
            print(f"run {k} {token}: exit {rc}  no usable log -> {path}", flush=True)
        if k < args.runs:
            tts.speak("Run finished. Please put me back down.")
            t0 = time.time()
            while time.time() - t0 < args.reset_s and not os.path.exists(skip):
                time.sleep(0.5)
            try:
                os.remove(skip)
            except OSError:
                pass
    tts.speak("All turn runs are finished.")
    for token, v in results.items():
        if v:
            print(f"SUMMARY {token}: mean {sum(v) / len(v):+.1f} deg/s over {len(v)} runs ({', '.join(f'{x:+.1f}' for x in v)})", flush=True)


if __name__ == "__main__":
    main()
