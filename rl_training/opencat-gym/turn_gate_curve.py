"""Yaw against DISTANCE for the firmware turn gaits (and a plain straight walk) in the calibrated sim, open-loop with zero residual, to compare with the real runs (docs/rl/real-walk-log.md).

    G2E_LONG_EP_PROB=1 G2E_LONG_EP_LEN=9600 python turn_gate_curve.py [--feet 6] [--episodes 3] [--max-seconds 120]

Each episode runs until G2 has travelled `--feet` feet (default 6, so past the 4 feet where the real bend gets strong) or `--max-seconds` passes. The sim's own episode limit is 12.5 s; `G2E_LONG_EP_PROB=1` with `G2E_LONG_EP_LEN` (steps at 80 Hz) lifts it.
Prints, per episode, the yaw in degrees (firmware convention, + = right) at each foot of travel, how long it took, and whether the target distance was reached.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())
import turn_gate_probe as T          # sets the calibrated profile and the turn blend, same as the gate probe
import numpy as np
import pybullet as p

E = T.E
FT = 0.3048


def episode(env, seed, yaw_cmd, feet, max_seconds):
    env.reset(seed=seed)
    env.set_command(fwd=E.PHASE_RATE_NOM_CMD, yaw=yaw_cmd)
    pos0 = np.array(p.getBasePositionAndOrientation(env.robot_id)[0][:2])
    yaws, dist, n, term, trunc = [], [], 0, False, False
    while True:
        _, _, term, trunc, _ = env.step(np.zeros(8))
        n += 1
        pos, orn = p.getBasePositionAndOrientation(env.robot_id)
        yaws.append(p.getEulerFromQuaternion(orn)[2])
        dist.append(float(np.linalg.norm(np.array(pos[:2]) - pos0)))
        if term or trunc or dist[-1] >= feet * FT or n >= int(max_seconds * E.CONTROL_HZ):
            break
    u = -np.degrees(np.unwrap(np.array(yaws)))              # firmware convention: + = right turn
    u = u - u[0]
    dist = np.maximum.accumulate(np.array(dist))
    at_ft = {}
    for f in range(1, int(feet) + 1):
        i = int(np.searchsorted(dist, f * FT))
        if i < len(u):
            at_ft[f] = round(float(u[i]), 1)
    return dict(yaw_deg_at_ft=at_ft, feet_travelled=round(float(dist[-1]) / FT, 2), seconds=round(n / E.CONTROL_HZ, 1), final_yaw_deg=round(float(u[-1]), 1), reached=bool(dist[-1] >= feet * FT),
                ended_early=bool(term or trunc) and bool(dist[-1] < feet * FT))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--feet", type=float, default=6.0)
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--max-seconds", type=float, default=120.0)
    a = ap.parse_args()
    env = E.OpenCatGymEnv()
    t0 = time.time()
    for name, yc in (("wkF_straight", 0.0), ("wkL", E.CMD_YAW_MAX), ("wkR", -E.CMD_YAW_MAX)):
        for ep in range(a.episodes):
            print(json.dumps({"skill": name, "episode": ep, **episode(env, 1234 + ep, yc, a.feet, a.max_seconds)}), flush=True)
    print(json.dumps({"wall_seconds": round(time.time() - t0, 1)}), flush=True)
