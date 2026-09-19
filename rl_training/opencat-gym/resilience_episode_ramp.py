"""R9 (resiliency campaign) -- within-episode degradation probe: latency and
torque (battery/thermal sag) both ramp UP over the course of one long
episode, instead of being fixed per-episode like CMD_LATENCY_STEPS /
TORQUE_CUTBACK normally are. Reframed from the original static-offset idea
to this ramping form per docs/rl/resiliency-log.md ("more realistic than a
static offset").

Mechanism (both done externally from the probe, no env code changes needed
since neither is reward-affecting logic the env itself must sample):
  - latency: extra zero-action frames inserted into env._act_buf as the
    episode progresses, growing the FIFO lag from 0 up to --max-latency.
  - torque: env._torque_scale linearly decayed from 1.0 down to
    (1 - --max-torque-drop) by episode end, applied every step.

Runs long episodes (default 800 steps, ~10s @ 80Hz -- G2E_EPISODE_LENGTH)
so there's room for a ramp and for splitting results into quarters to see
*when* degradation shows up, not just whether it does.

    python resilience_episode_ramp.py trained/run20m_resid30_ppo
    python resilience_episode_ramp.py trained/run20m_resid30_ppo --episodes 12 --levels mild,moderate,severe
"""
import argparse
import json
import os

os.environ.setdefault("G2E_EPISODE_LENGTH", "800")

import numpy as np
import pybullet as p

import opencat_gym_env as E

E.GUI_MODE = False
E.DR_EVAL_FULL = True

from opencat_gym_env import OpenCatGymEnv, EPISODE_LENGTH
from stable_baselines3 import PPO

LEVEL_PARAMS = {
    "none":     {"max_latency": 0, "max_torque_drop": 0.0},
    "mild":     {"max_latency": 2, "max_torque_drop": 0.15},
    "moderate": {"max_latency": 4, "max_torque_drop": 0.35},
    "severe":   {"max_latency": 8, "max_torque_drop": 0.55},
}

ap = argparse.ArgumentParser()
ap.add_argument("checkpoints", nargs="+")
ap.add_argument("--episodes", type=int, default=12)
ap.add_argument("--levels", default="none,mild,moderate,severe")
ap.add_argument("--json-out", default=None)
args = ap.parse_args()
LEVELS = args.levels.split(",")


def _set_latency(env, target_frames):
    cur = len(env._act_buf)
    if target_frames > cur:
        for _ in range(target_frames - cur):
            env._act_buf.insert(0, np.zeros(8))
    elif target_frames < cur:
        del env._act_buf[0:cur - target_frames]


def probe(ckpt, level, n_episodes):
    params = LEVEL_PARAMS[level]
    m = PPO.load(ckpt)
    env = OpenCatGymEnv()
    falls = 0
    quarter_speed = [[], [], [], []]
    for s in range(n_episodes):
        np.random.seed(6000 + s)
        obs, _ = env.reset()
        env.set_command(fwd=0.10, yaw=0.0)
        env._act_buf = []
        q_start_x = [None, None, None, None]
        q_idx = 0
        x_prev = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        fell = False
        for t in range(EPISODE_LENGTH):
            frac = t / EPISODE_LENGTH
            env._torque_scale = np.ones(8) * (1.0 - params["max_torque_drop"] * frac)
            _set_latency(env, round(params["max_latency"] * frac))
            new_q = min(3, int(frac * 4))
            if new_q != q_idx or q_start_x[new_q] is None:
                q_idx = new_q
                if q_start_x[q_idx] is None:
                    q_start_x[q_idx] = x_prev
            a, _ = m.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(a)
            x_prev = p.getBasePositionAndOrientation(env.robot_id)[0][0]
            if term:
                fell = True
                break
        x_end = [q_start_x[i + 1] if i + 1 < 4 and q_start_x[i + 1] is not None else x_prev
                 for i in range(4)]
        for i in range(4):
            if q_start_x[i] is not None:
                span = (x_end[i] - q_start_x[i])
                steps_in_q = EPISODE_LENGTH / 4
                quarter_speed[i].append(span / steps_in_q * 80.0)
        falls += fell
    env.close()
    q_means = [float(np.mean(qs)) if qs else None for qs in quarter_speed]
    return {
        "ckpt": ckpt, "level": level, "episodes": n_episodes,
        "max_latency_steps": params["max_latency"], "max_torque_drop": params["max_torque_drop"],
        "falls": falls, "fall_rate": falls / n_episodes,
        "speed_by_quarter_mps": q_means,
        "degradation_q4_vs_q1_pct": (
            (q_means[3] - q_means[0]) / q_means[0] * 100.0
            if q_means[0] not in (None, 0) and q_means[3] is not None else None
        ),
    }


if __name__ == "__main__":
    out = []
    for ckpt in args.checkpoints:
        for level in LEVELS:
            r = probe(ckpt, level, args.episodes)
            out.append(r)
            q = r["speed_by_quarter_mps"]
            qstr = " ".join(f"{v:.3f}" if v is not None else "--" for v in q)
            print(f"{ckpt:30s} {level:9s} falls={r['fall_rate']:.0%}  "
                  f"speed/quarter=[{qstr}]  "
                  f"Q4-vs-Q1={r['degradation_q4_vs_q1_pct']:.0f}%" if r['degradation_q4_vs_q1_pct'] is not None
                  else f"{ckpt:30s} {level:9s} falls={r['fall_rate']:.0%}  speed/quarter=[{qstr}]")
    if args.json_out:
        json.dump(out, open(args.json_out, "w"), indent=1)
        print("wrote", args.json_out)
