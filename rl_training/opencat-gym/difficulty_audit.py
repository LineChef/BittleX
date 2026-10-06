"""Does a policy find the higher difficulty levels harder? (2026-10-06)

    ../../.venv/bin/python difficulty_audit.py trained/Release_CandidateV2.1_ppo [--levels 0,0.25,0.5,0.75,1.0] [--episodes 60]

Runs the policy through the TRAINING sampler (the full V3 course: faults, ledges, snags, transitions, rubble, pushes ...) with the difficulty level pinned
(LEVEL_FIXED) and SCALE_ALL_HAZARDS on, 250-step episodes, commanded 0.10 m/s. Prints falls and speed per level. A working curriculum shows falls rising with the level,
and (almost) none at level 0.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = r'''
import sys, json
sys.path.insert(0, %r)
import g2_profile
env = g2_profile.env_for("faults", stage="s4_ledge")
env.update({"G2E_SCALE_ALL_HAZARDS": "1", "G2E_ADAPTIVE_LEVEL": "1"})
CAT, LV = %r, %r
env["G2E_LEVEL_START"] = "0"
if CAT == "all":
    env["G2E_LEVEL_FIXED"] = str(LV)
g2_profile.set_environ(env)
import numpy as np, pybullet as p
import opencat_gym_env as E
E.GUI_MODE = False
if CAT != "all":
    E.CATEGORY_OVERRIDE = {CAT: LV}
from opencat_gym_env import OpenCatGymEnv
from stable_baselines3 import PPO
m = PPO.load(%r)
e = OpenCatGymEnv(); e.set_command(fwd=0.10, yaw=0.0); e.set_ramp_steps(5e6)
falls, speeds, tilts = 0, [], []
for k in range(%d):
    np.random.seed(5000 + k)
    obs, _ = e.reset(seed=5000 + k)
    x0 = p.getBasePositionAndOrientation(e.robot_id)[0][0]
    peak, n = 0.0, 0
    while True:
        a, _ = m.predict(obs, deterministic=True)
        obs, r, te, tr, info = e.step(a)
        n += 1
        o = p.getBasePositionAndOrientation(e.robot_id)[1]
        rr, pp, _y = p.getEulerFromQuaternion(o)
        peak = max(peak, abs(rr), abs(pp))
        if te or tr:
            break
    falls += peak > 1.3
    speeds.append((p.getBasePositionAndOrientation(e.robot_id)[0][0] - x0) / (n / 80.0))
    tilts.append(peak)
print("RESULT " + json.dumps(dict(level=(e._dr if CAT == 'all' else LV), falls=falls / %d, speed=float(np.mean(speeds)), peak_tilt_med=float(np.median(tilts)), peak_tilt_p90=float(np.percentile(tilts, 90)))))
'''
ap = argparse.ArgumentParser()
ap.add_argument("policy")
ap.add_argument("--levels", default="0,0.25,0.5,0.75,1.0")
ap.add_argument("--episodes", type=int, default=60)
ap.add_argument("--category", default="all", help="all (LEVEL_FIXED) or terrain | ledge | slope | fault alone (the others at 0)")
a = ap.parse_args()
procs = [(lv, subprocess.Popen([sys.executable, "-c", CHILD % (HERE, a.category, lv, a.policy, a.episodes, a.episodes)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=HERE))
         for lv in [float(x) for x in a.levels.split(",")]]
print(f"{'level':>5s} {'falls':>6s} {'speed m/s':>10s} {'peak tilt med/p90 (rad)':>24s}   policy {a.policy}, {a.episodes} episodes per level")
for lv, pr in procs:
    out, err = pr.communicate()
    line = [l for l in out.splitlines() if l.startswith("RESULT ")]
    if not line:
        print(f"level {lv}: FAILED\n{err[-500:]}")
        continue
    r = json.loads(line[0][7:])
    print(f"{r['level']:5.2f} {r['falls']:6.0%} {r['speed']:10.3f} {r['peak_tilt_med']:11.2f}/{r['peak_tilt_p90']:5.2f}")
