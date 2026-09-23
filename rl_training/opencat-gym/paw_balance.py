"""Per-paw ground contact: does the gait use all four legs? (2026-09-23)

Every learned gait so far limps -- one paw on the ground ~13-17 % of steps vs
41-61 % for the scripted wkF walk. Flat ground, payload on, G2's realistic
mass/calibration, learned gait through the real control path.

    python paw_balance.py trained/hw1_20m_ppo trained/checkpoints/hw2_20m_3000000_steps
"""
import argparse

import numpy as np
import pybullet as p

import opencat_gym_env as E
E.GUI_MODE = False
E.DR_EVAL_FULL = True
import benchmark_decathlon as B
from benchmark_gaits import _load_learned

PAWS = {3: "FL", 6: "FR", 9: "BR", 12: "BL"}


def measure(ck, episodes=4, steps=320):
    B._apply({})
    E.ROUGH_TERRAIN, E.TORQUE_CUTBACK, E.ADAPTIVE_PUSH = 0.0, 0.0, False
    E.BODY_MASS_SCALE, E.IMU_BIAS_DEG, E.JOINT_OFFSET_DEG = 1.12, 2.0, 2.0
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"
    E.EPISODE_LENGTH = steps + 5
    m = _load_learned(ck)
    env = E.OpenCatGymEnv()
    hit = {l: 0 for l in PAWS}
    n = 0
    for s in range(episodes):
        np.random.seed(3000 + s)
        obs, _ = env.reset()
        env.set_command(fwd=0.10, yaw=0.0)
        for _ in range(steps):
            obs, *_ = env.step(m.predict(obs, deterministic=True)[0])
            n += 1
            for l in PAWS:
                if any(c[2] != env.robot_id for c in p.getContactPoints(bodyA=env.robot_id, linkIndexA=l)):
                    hit[l] += 1
    env.close()
    return {PAWS[l]: hit[l] / n for l in PAWS}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoints", nargs="+")
    args = ap.parse_args()
    for ck in args.checkpoints:
        r = measure(ck)
        print(f"{ck}: " + "  ".join(f"{k} {v*100:3.0f}%" for k, v in r.items())
              + f"  | least-used {min(r.values())*100:.0f}% (scripted wkF: 41 %)", flush=True)
