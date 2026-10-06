"""A series of logged, closed-loop V2.1 walks on the hard floor, for a fresh sim-vs-real baseline (run as `g2-baseline` by tools/g2_baseline.sh).

Each run is the proven CLI path (`run_gait.py --cmd 0.10 --seconds 12.5 --log <csv>`, fall guard on). G2 speaks before each run and between runs, so
whoever is with him can put him back at the start of the lane. `touch ~/.g2_baseline_skip` after hearing the prompt to skip the wait.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=6)
    ap.add_argument("--label", default="case_v21")
    ap.add_argument("--cmd", type=float, default=0.10)
    ap.add_argument("--seconds", type=float, default=12.5)
    ap.add_argument("--lead-s", type=float, default=20.0, help="spoken warning before a run")
    ap.add_argument("--reset-s", type=float, default=35.0, help="time to put G2 back at the start between runs")
    args = ap.parse_args()

    from pi_pipeline.config import settings
    from pi_pipeline.voice.tts import make_tts

    tts = make_tts("piper", piper_model_path=settings.piper_model_path, style=settings.voice_style)
    out = os.path.expanduser("~/g2_runs")
    os.makedirs(out, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    skip = os.path.expanduser("~/.g2_baseline_skip")
    logs = []
    for k in range(1, args.runs + 1):
        tts.speak(f"Baseline run {k} of {args.runs} in {int(args.lead_s)} seconds. Make sure I am on the hard floor with a clear lane ahead.")
        time.sleep(max(0.0, args.lead_s - 6.0))
        path = os.path.join(out, f"{args.label}_{stamp}_run{k:02d}.csv")
        rc = subprocess.call([sys.executable, os.path.join(HERE, "run_gait.py"), "--cmd", str(args.cmd), "--seconds", str(args.seconds),
                              "--log", path])
        logs.append(path)
        print(f"run {k}: exit {rc} -> {path}", flush=True)
        if k < args.runs:
            tts.speak("Run finished. Please put me back at the start of the lane.")
            t0 = time.time()
            while time.time() - t0 < args.reset_s and not os.path.exists(skip):
                time.sleep(0.5)
            try:
                os.remove(skip)
            except OSError:
                pass
    tts.speak("All baseline runs are finished.")
    print("LOGS", " ".join(logs), flush=True)


if __name__ == "__main__":
    main()
