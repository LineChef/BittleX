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
    ap.add_argument("--yaw-sign", default=None,
                    help="A/B test only: the sign of the yaw fed to the policy (-1 = the corrected default, +1 = the pre-2026-10-06 behaviour), "
                         "or 'abba' to alternate new, old, old, new, new, old, old, new ... so a drifting battery / servo warm-up hits both equally")
    ap.add_argument("--hold", default=None, choices=("on", "off", "abba"),
                    help="A/B test of the Pi-side heading hold (gait/heading_hold.py): on, off, or 'abba' = off, on, on, off, off, on, on, off ...")
    ap.add_argument("--hold-ff", type=float, default=None, help="feed-forward for the heading-hold runs (see run_gait --hold-ff)")
    ap.add_argument("--hold-ki", type=float, default=None, help="integral gain for the heading-hold runs")
    ap.add_argument("--hold-umax", type=float, default=None, help="largest stride difference for the heading-hold runs")
    ap.add_argument("--hold-kp", type=float, default=None, help="proportional gain for the heading-hold runs")
    ap.add_argument("--const-u", default=None,
                    help="comma list of fixed stride differences, e.g. -0.2,0,0.2: run k uses the list walked forward then backward (a b c c b a ...), no feedback")
    ap.add_argument("--reset-s", type=float, default=35.0, help="time to put G2 back at the start between runs")
    args = ap.parse_args()

    from pi_pipeline.config import settings
    from pi_pipeline.voice.tts import make_tts

    def hold_for(k):
        if args.hold is None:
            return None
        if args.hold == "abba":
            return (False, True, True, False)[(k - 1) % 4]
        return args.hold == "on"

    const_us = [float(x) for x in args.const_u.split(",")] if args.const_u else None

    def const_for(k):
        if const_us is None:
            return None
        order = const_us + const_us[::-1]
        return order[(k - 1) % len(order)]

    def sign_for(k):
        if args.yaw_sign is None:
            return None
        if args.yaw_sign == "abba":
            return (-1.0, 1.0, 1.0, -1.0)[(k - 1) % 4]
        return float(args.yaw_sign)
    tts = make_tts("piper", piper_model_path=settings.piper_model_path, style=settings.voice_style)
    out = os.path.expanduser("~/g2_runs")
    os.makedirs(out, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    skip = os.path.expanduser("~/.g2_baseline_skip")
    logs = []
    for k in range(1, args.runs + 1):
        tts.speak(f"Baseline run {k} of {args.runs} in {int(args.lead_s)} seconds. Make sure I am on the hard floor with a clear lane ahead.")
        time.sleep(max(0.0, args.lead_s - 6.0))
        sgn, hold, cu = sign_for(k), hold_for(k), const_for(k)
        path = os.path.join(out, f"{args.label}_{stamp}_run{k:02d}" + ("" if sgn is None else f"_sign{'P' if sgn > 0 else 'M'}")
                            + ("" if hold is None else f"_hold{'ON' if hold else 'OFF'}")
                            + ("" if cu is None else f"_u{cu:+.2f}") + ".csv")
        child_env = dict(os.environ, **({} if sgn is None else {"G2_POLICY_YAW_SIGN": f"{sgn:g}"}))
        rc = subprocess.call([sys.executable, os.path.join(HERE, "run_gait.py"), "--cmd", str(args.cmd), "--seconds", str(args.seconds),
                              "--log", path] + (["--heading-hold"] if hold else [])
                              + (["--hold-ff", str(args.hold_ff)] if hold and args.hold_ff is not None else [])
                              + (["--hold-kp", str(args.hold_kp)] if hold and args.hold_kp is not None else [])
                              + (["--hold-umax", str(args.hold_umax)] if args.hold_umax is not None else [])
                              + (["--hold-ki", str(args.hold_ki)] if hold and args.hold_ki is not None else []) + ([] if cu is None else ["--steer-const", str(cu)]), env=child_env)
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
