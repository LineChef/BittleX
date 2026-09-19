"""R2 (resiliency campaign) -- IMU bias / mount-tilt probe.

Sweeps IMU_BIAS_DEG (a persistent per-episode roll/pitch bias in what the
policy SEES, not the reward -- see opencat_gym_env.py's _imu_bias_euler)
across severity levels and measures fall rate / speed / tilt stats at each,
for one or more checkpoints. Reopened 2026-09-18 now that the real
Pi<->PiSugar connector is confirmed solid (R2 was DEFERRED pending exactly
that in the original robustness-backlog triage).

    python resilience_imu_bias.py trained/run20m_resid30_ppo
    python resilience_imu_bias.py trained/run20m_resid30_ppo --episodes 20 --levels 0,2,5,10,15
"""
import argparse
import json
import sys

import numpy as np
import pybullet as p

import opencat_gym_env as E

E.GUI_MODE = False
E.DR_EVAL_FULL = True

from opencat_gym_env import OpenCatGymEnv
from stable_baselines3 import PPO

ap = argparse.ArgumentParser()
ap.add_argument("checkpoints", nargs="+")
ap.add_argument("--episodes", type=int, default=20)
ap.add_argument("--levels", default="0,2,5,10,15,20",
                 help="comma-separated IMU_BIAS_DEG values to sweep (degrees)")
ap.add_argument("--steps", type=int, default=250)
ap.add_argument("--json-out", default=None)
args = ap.parse_args()
LEVELS = [float(x) for x in args.levels.split(",")]


def probe(ckpt, level, n_episodes):
    E.IMU_BIAS_DEG = level
    m = PPO.load(ckpt)
    env = OpenCatGymEnv()
    falls = 0
    speeds, tilt_maxes, biases_used = [], [], []
    for s in range(n_episodes):
        np.random.seed(5000 + s)
        obs, _ = env.reset()
        env.set_command(fwd=0.10, yaw=0.0)
        biases_used.append(np.rad2deg(env._imu_bias_euler).copy())
        fell = False
        tilt_max = 0.0
        x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        for _ in range(args.steps):
            a, _ = m.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(a)
            q = p.getBasePositionAndOrientation(env.robot_id)[1]
            rp = p.getEulerFromQuaternion(q)
            tilt_max = max(tilt_max, abs(rp[0]), abs(rp[1]))
            if term:
                fell = True
                break
        x1 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        n_steps = args.steps if not fell else env.step_counter
        speeds.append((x1 - x0) / max(1, n_steps) * 80.0)  # CONTROL_HZ=80
        tilt_maxes.append(tilt_max)
        falls += fell
    env.close()
    return {
        "ckpt": ckpt, "imu_bias_deg_level": level, "episodes": n_episodes,
        "falls": falls, "fall_rate": falls / n_episodes,
        "speed_mps_mean": float(np.mean(speeds)),
        "tilt_max_mean": float(np.mean(tilt_maxes)),
        "bias_applied_deg_mean_abs": float(np.mean(np.abs(biases_used))) if biases_used else 0.0,
    }


if __name__ == "__main__":
    out = []
    for ckpt in args.checkpoints:
        for level in LEVELS:
            r = probe(ckpt, level, args.episodes)
            out.append(r)
            print(f"{ckpt:30s} bias={level:5.1f}deg  falls={r['fall_rate']:.0%}  "
                  f"speed={r['speed_mps_mean']:.3f}  tilt_max={r['tilt_max_mean']:.2f}")
    if args.json_out:
        json.dump(out, open(args.json_out, "w"), indent=1)
        print("wrote", args.json_out)
