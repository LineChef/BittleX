#!/usr/bin/env python3
"""Summarize real-robot walk logs from `run_gait.py --log`, `--openloop --log` or
`fw_skill_log.py` (columns t,roll,pitch,yaw[,...][,volt]; angles in radians).

    python tools/walk_log_summary.py ~/g2_runs/hard_v21_run06.csv ~/g2_runs/carpet_v21_run01.csv

Per log: duration, roll/pitch mean/std/range, yaw change at 25/50/75/100% of the run (positive =
turned right; includes any hand corrections), the first time |roll| or |pitch| passed 45 deg (a
fall) with the roll/pitch swing before it, and battery voltage min/max if it was logged.
"""
import os
import sys

import numpy as np


def summarize(path):
    d = np.genfromtxt(os.path.expanduser(path), delimiter=",", names=True, skip_header=1,
                      dtype=None, encoding=None)
    t = d["t"]
    roll, pitch, yaw = (np.degrees(d[k]) for k in ("roll", "pitch", "yaw"))
    q = [yaw[min(int(f * (len(yaw) - 1)), len(yaw) - 1)] - yaw[0] for f in (.25, .5, .75, 1.0)]
    out = [f"{os.path.basename(path)}: {len(t)} frames, {t[-1]:.1f} s",
           f"  roll  {roll.mean():+.1f} / {roll.std():.1f}  [{roll.min():.0f}, {roll.max():.0f}]   "
           f"pitch {pitch.mean():+.1f} / {pitch.std():.1f}  [{pitch.min():.0f}, {pitch.max():.0f}]",
           f"  yaw change at 25/50/75/100%: " + " ".join(f"{x:+.0f}" for x in q)]
    bad = np.where((abs(roll) > 45) | (abs(pitch) > 45))[0]
    if len(bad):
        pre = slice(0, max(bad[0], 1))
        out.append(f"  first >45 deg tilt at {t[bad[0]]:.1f} s; before it: roll std {roll[pre].std():.1f} "
                   f"[{roll[pre].min():.0f}, {roll[pre].max():.0f}], pitch std {pitch[pre].std():.1f}")
    else:
        out.append("  no fall (never past 45 deg)")
    if "volt" in d.dtype.names and not np.all(np.isnan(d["volt"])):
        out.append(f"  battery {np.nanmin(d['volt']):.2f} .. {np.nanmax(d['volt']):.2f} V")
    return "\n".join(out)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(summarize(p))
