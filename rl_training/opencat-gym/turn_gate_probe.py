"""V3 turning gate (docs/rl/v3-retrain-plan.md Phase 1): how fast does the calibrated sim turn the firmware turn gaits wkL / wkR open-loop (zero residual)?

    G2E_TURN_BLEND=1 python turn_gate_probe.py [--episodes 6] [--seconds 10]

Compare with the real rates (docs/rl/real-walk-log.md, firmware turn runs): the gate passes when the sim turns each at >= 50% of the real rate.
Prints JSON; rates are in the FIRMWARE convention (+ = right turn), so wkL is negative.
"""
import argparse
import json
import os

import g2_profile
for k, v in g2_profile.CALIBRATION.items():
    os.environ.setdefault(k, v)
os.environ.setdefault("G2E_TURN_BLEND", "1")
os.environ.setdefault("G2E_PAYLOAD_PROFILE", "case")
import numpy as np
import pybullet as p

import drift_probe                        # sets BASE_ENV, flat calm T1.1 env (benchmark_decathlon._apply)
import opencat_gym_env as E

REAL = {"wkL": -12.1, "wkR": 18.6}       # deg/s, firmware convention, mean of 3 real runs each


def run(yaw_cmd, episodes, seconds):
    env = E.OpenCatGymEnv()
    rates = []
    for ep in range(episodes):
        env.reset(seed=1234 + ep)
        env.set_command(fwd=E.PHASE_RATE_NOM_CMD, yaw=yaw_cmd)      # nominal cadence = the firmware gait's (the phase does not advance at fwd 0)
        yaws, n = [], 0
        while True:
            _, _, term, trunc, _ = env.step(np.zeros(8))
            n += 1
            yaws.append(p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])[2])
            if term or trunc or n >= int(seconds * E.CONTROL_HZ):
                break
        u = np.degrees(np.unwrap(np.array(yaws)))
        t = np.arange(len(u)) / E.CONTROL_HZ
        rates.append(-float(np.polyfit(t, u, 1)[0]))        # sim + = left; firmware + = right
    return rates


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=6)
    ap.add_argument("--seconds", type=float, default=10.0)
    a = ap.parse_args()
    out = {}
    for name, yc in (("wkL", E.CMD_YAW_MAX), ("wkR", -E.CMD_YAW_MAX)):
        r = run(yc, a.episodes, a.seconds)
        m = float(np.mean(r))
        out[name] = dict(sim_deg_s=round(m, 1), real_deg_s=REAL[name], ratio=round(m / REAL[name], 2), per_episode=[round(x, 1) for x in r])
    out["gate_pass"] = all(v["ratio"] >= 0.5 for v in (out["wkL"], out["wkR"]))
    print(json.dumps(out))
