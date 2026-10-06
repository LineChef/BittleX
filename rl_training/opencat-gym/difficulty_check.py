"""Difficulty-scaling check (2026-10-06): what does the TRAINING sampler generate at a fixed difficulty level?

    ../../.venv/bin/python difficulty_check.py [--levels 0,0.25,0.5,0.75,1.0] [--episodes 150]

One subprocess per level (the knobs are read at import). The training course is the full V3 mix: V3 recipe + faults lever + all stage hazards (ledges 20%, snags 20%,
transitions with a 12 mm step 25%) with ADAPTIVE_LEVEL's LEVEL_FIXED pinning the level and SCALE_ALL_HAZARDS on. For each level, over many episode resets (no stepping):
the tallest static obstacle top above the floor (m), the ledge height, the ground-tilt magnitude (deg), the share of episodes with a stuck servo / weak joint / yaw push,
the overheat cutback depth, and the commanded push scale. Level 0 must be a passable floor; every severity must rise with the level.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = r'''
import os, sys, json
sys.path.insert(0, %r)
import g2_profile
env = g2_profile.env_for("faults", stage="s4_ledge")
env.update({"G2E_SCALE_ALL_HAZARDS": "1", "G2E_ADAPTIVE_LEVEL": "1", "G2E_SNAG_OBSTACLE_PROB": "0.2"})
CAT, LV = %r, %r
env["G2E_LEVEL_START"] = "0"                               # the stage settings would start the generic randomization at 0.8
if CAT == "all":
    env["G2E_LEVEL_FIXED"] = str(LV)
g2_profile.set_environ(env)
import numpy as np, pybullet as p
import opencat_gym_env as E
E.GUI_MODE = False
if CAT != "all":
    E.CATEGORY_OVERRIDE = {CAT: LV}                        # this category alone at the level, the others at 0
e = E.OpenCatGymEnv()
calls = {"obst": 0, "rub": 0, "snag": 0}
_o, _r, _g = e._scatter_obstacles, e._scatter_rubble, e._scatter_snags
def _wo(*a, **k): calls["obst"] = a[0] if a else 1; return _o(*a, **k)
def _wr(*a, **k): calls["rub"] = a[0] if a else 1; return _r(*a, **k)
def _wg(*a, **k): calls["snag"] = 1; return _g(*a, **k)
e._scatter_obstacles, e._scatter_rubble, e._scatter_snags = _wo, _wr, _wg
box_cap, rub_cap, snag_h, ledge, tilt, stuck, weak, yawpush, cut, stepm, n = [], [], [], [], [], 0, 0, 0, [], [], %d
cap_stuck = []
for k in range(n):
    calls.update(obst=0, rub=0, snag=0)
    e.reset(seed=k)
    box_cap.append(min(calls["obst"], E.RANDOM_TERRAIN_MAX_H) if calls["obst"] else 0.0)
    rub_cap.append(E.RUBBLE_MAX_H * max(0.15, e._d_terrain) if calls["rub"] else 0.0)
    snag_h.append(E.SNAG_HEIGHT_M * (0.4 + 0.6 * e._d_terrain) if calls["snag"] else 0.0)
    ledge.append(float(e._ledge_h))
    tilt.append(float(np.degrees(max(abs(e._slope_rp[0]), abs(e._slope_rp[1])))))
    stuck += e._motor_max is not None
    if e._motor_max is not None:
        cap_stuck.append(float(np.degrees(e._motor_max.min())))
    weak += bool((e._torque_scale < 0.99).any())
    yawpush += abs(e._drift_torque) > 0
    cut.append(float(1.0 - e._torque_scale.min()))
tops = [max(a, b, c) for a, b, c in zip(box_cap, rub_cap, snag_h)]
q = lambda v, f: float(np.percentile(v, f))
print("RESULT " + json.dumps(dict(level=(e._dr if CAT == 'all' else LV), obstacle_top_med=q([t for t in tops if t > 0] or [0], 50), obstacle_top_p90=q(tops, 90), obstacle_top_max=max(tops), stuck_cap_med=q(cap_stuck or [50], 50),
      ledge_med=q([l for l in ledge if l > 0] or [0], 50), ledge_max=max(ledge), episodes_with_ledge=float(np.mean(np.array(ledge) > 0)),
      tilt_p90=q(tilt, 90), tilt_max=max(tilt), stuck=stuck / n, weak_or_cut=weak / n, yawpush=yawpush / n, cutback_p90=q(cut, 90))))
'''
ap = argparse.ArgumentParser()
ap.add_argument("--levels", default="0,0.25,0.5,0.75,1.0")
ap.add_argument("--episodes", type=int, default=150)
ap.add_argument("--category", default="all", help="all (LEVEL_FIXED, everything together) or terrain | ledge | slope | fault (that category alone, the others at 0)")
a = ap.parse_args()
procs = []
for lv in [float(x) for x in a.levels.split(",")]:
    procs.append((lv, subprocess.Popen([sys.executable, "-c", CHILD % (HERE, a.category, lv, a.episodes)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=HERE)))
rows = []
for lv, pr in procs:
    out, err = pr.communicate()
    line = [l for l in out.splitlines() if l.startswith("RESULT ")]
    if not line:
        print(f"level {lv}: FAILED\n{err[-600:]}")
        continue
    rows.append(json.loads(line[0][7:]))
print(f"{'level':>5s} {'small-hazard cap med/p90/max (mm)':>27s} {'ledge med/max (mm)':>19s} {'ledge eps':>9s} {'tilt p90/max (deg)':>19s} {'stuck':>6s} {'weak':>6s} {'yaw push':>8s} {'cutback p90':>11s} {'stuck cap':>9s}")
for r in rows:
    print(f"{r['level']:5.2f} {1000*r['obstacle_top_med']:8.1f}/{1000*r['obstacle_top_p90']:5.1f}/{1000*r['obstacle_top_max']:5.1f} {1000*r['ledge_med']:10.1f}/{1000*r['ledge_max']:6.1f} "
          f"{r['episodes_with_ledge']:9.0%} {r['tilt_p90']:10.1f}/{r['tilt_max']:6.1f} {r['stuck']:6.0%} {r['weak_or_cut']:6.0%} {r['yawpush']:8.0%} {r['cutback_p90']:11.2f} {r['stuck_cap_med']:9.1f}")
