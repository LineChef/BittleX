"""R8 (resiliency campaign) -- aggressive command-transition probe. Reopened
2026-09-18: DROPPED in the original 2026-09-03 triage with no specific
technical objection recorded (checked git history -- the entry only
describes what it would test, no "why not" reasoning survived the doc's
2026-09-08 restructure/prune), and it directly matches this session's own
priority, so reopening rather than leaving it dropped by default.

We train speed *tracking* but never *transitions* -- every training episode
samples one command band and mostly holds it (CMD_RESAMPLE_PROB lets it
change mid-episode, but not on a forced schedule). This probe drives the
command through scripted schedules `set_command()` wasn't originally built
to be hammered with, using it exactly as intended (it already exists for
fixed-command eval, e.g. benchmark_gaits.py's cruise-forward pin) -- no env
code changes needed.

Modes:
  - reverse-slam: full forward for the first half, hard reverse for the second.
  - yaw-slam: cruise forward, yaw command flips sign every --interval steps.
  - stop-start: alternate walk/stand every --interval steps.
  - sustained-arc: fwd + a fixed nonzero yaw held for the WHOLE episode --
    does heading spiral or drift, not just does it fall.

    python resilience_command_dynamics.py trained/run20m_resid30_ppo
    python resilience_command_dynamics.py trained/run20m_resid30_ppo --episodes 12 --modes reverse-slam,yaw-slam
"""
import argparse
import json
import os

os.environ.setdefault("G2E_EPISODE_LENGTH", "400")

import numpy as np
import pybullet as p

import opencat_gym_env as E

E.GUI_MODE = False
E.DR_EVAL_FULL = True

from opencat_gym_env import OpenCatGymEnv, EPISODE_LENGTH, CMD_FWD_MAX, CMD_YAW_MAX
from stable_baselines3 import PPO

ap = argparse.ArgumentParser()
ap.add_argument("checkpoints", nargs="+")
ap.add_argument("--episodes", type=int, default=12)
ap.add_argument("--modes", default="reverse-slam,yaw-slam,stop-start,sustained-arc")
ap.add_argument("--interval", type=int, default=60)
ap.add_argument("--json-out", default=None)
args = ap.parse_args()
MODES = args.modes.split(",")


def _cmd_for(mode, t):
    if mode == "reverse-slam":
        return (CMD_FWD_MAX, 0.0) if t < EPISODE_LENGTH // 2 else (-0.09, 0.0)
    if mode == "yaw-slam":
        sign = 1.0 if (t // args.interval) % 2 == 0 else -1.0
        return (0.10, sign * CMD_YAW_MAX)
    if mode == "stop-start":
        walking = (t // args.interval) % 2 == 0
        return (0.10, 0.0) if walking else (0.0, 0.0)
    if mode == "sustained-arc":
        return (0.10, 0.25 * CMD_YAW_MAX)
    raise ValueError(mode)


def probe(ckpt, mode, n_episodes):
    m = PPO.load(ckpt)
    env = OpenCatGymEnv()
    falls = 0
    tilt_maxes, heading_drifts = [], []
    for s in range(n_episodes):
        np.random.seed(7000 + s)
        obs, _ = env.reset()
        fwd0, yaw0 = _cmd_for(mode, 0)
        env.set_command(fwd=fwd0, yaw=yaw0)
        tilt_max = 0.0
        cum_expected_heading = 0.0
        fell = False
        for t in range(EPISODE_LENGTH):
            fwd, yaw = _cmd_for(mode, t)
            env.set_command(fwd=fwd, yaw=yaw)
            cum_expected_heading += yaw / 80.0  # CONTROL_HZ=80
            a, _ = m.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(a)
            q = p.getBasePositionAndOrientation(env.robot_id)[1]
            rp = p.getEulerFromQuaternion(q)
            tilt_max = max(tilt_max, abs(rp[0]), abs(rp[1]))
            if term:
                fell = True
                break
        if mode == "sustained-arc" and not fell:
            actual_heading = p.getEulerFromQuaternion(
                p.getBasePositionAndOrientation(env.robot_id)[1])[2]
            heading_drifts.append(abs(actual_heading - cum_expected_heading))
        tilt_maxes.append(tilt_max)
        falls += fell
    env.close()
    return {
        "ckpt": ckpt, "mode": mode, "episodes": n_episodes,
        "falls": falls, "fall_rate": falls / n_episodes,
        "tilt_max_mean": float(np.mean(tilt_maxes)),
        "heading_drift_rad_mean": float(np.mean(heading_drifts)) if heading_drifts else None,
    }


if __name__ == "__main__":
    out = []
    for ckpt in args.checkpoints:
        for mode in MODES:
            r = probe(ckpt, mode, args.episodes)
            out.append(r)
            extra = f"  heading_drift={r['heading_drift_rad_mean']:.2f}rad" if r["heading_drift_rad_mean"] is not None else ""
            print(f"{ckpt:30s} {mode:15s} falls={r['fall_rate']:.0%}  tilt_max={r['tilt_max_mean']:.2f}{extra}")
    if args.json_out:
        json.dump(out, open(args.json_out, "w"), indent=1)
        print("wrote", args.json_out)
