"""Gait-friction campaign -- pinned-command speed sweep. The primary
pass/fail signal per docs/rl/gait-friction-log.md: does mean residual usage
at creep/cruise/fast speeds actually drop after the amplitude-scaling fix,
compared to the ~7-8deg baseline -- not just "did fall rate stay flat."

Pins cmd_fwd at fixed points across the trained range (flat, calm ground --
no disturbance, matching the campaign's own reprioritized target of ordinary
everyday walking, not stress conditions) and reports mean/max residual
degree usage plus actual-vs-commanded speed tracking, for one or more
checkpoints so a clean before/after comparison is one command.

    python gaitfriction_speed_sweep.py trained/run20m_resid30_ppo trained/gaitfriction_r1_ppo
"""
import argparse
import json

import numpy as np
import pybullet as p

import opencat_gym_env as E

E.GUI_MODE = False
E.DR_EVAL_FULL = False   # flat, calm ground -- no disturbance, per this campaign's own target

from opencat_gym_env import OpenCatGymEnv
from stable_baselines3 import PPO

SPEEDS = [0.02, 0.04, 0.055, 0.08, 0.10, 0.12, 0.115, 0.13, 0.15]
BANDS = {0.02: "creep", 0.04: "creep", 0.055: "creep", 0.08: "cruise", 0.10: "cruise",
         0.12: "cruise", 0.115: "fast", 0.13: "fast", 0.15: "fast"}

ap = argparse.ArgumentParser()
ap.add_argument("checkpoints", nargs="+")
ap.add_argument("--episodes", type=int, default=6)
ap.add_argument("--steps", type=int, default=200)
ap.add_argument("--json-out", default=None)
args = ap.parse_args()


def probe(ckpt, cmd):
    scale_deg = float(getattr(E, "RESIDUAL_SCALE_DEG", 22))
    # PHASE_RATE_CORRECTION_ENABLED must match what each checkpoint was actually
    # trained under -- only gaitfriction_r5+ were trained WITH the correction;
    # everything else (including run20m_resid30_ppo) needs it off, or they get
    # evaluated against a reference they never trained against.
    E.PHASE_RATE_CORRECTION_ENABLED = any(tag in ckpt for tag in ("gaitfriction_r5",))
    m = PPO.load(ckpt)
    env = OpenCatGymEnv()
    rms_all, speeds = [], []
    falls = 0
    for s in range(args.episodes):
        np.random.seed(8000 + s)
        obs, _ = env.reset()
        env.set_command(fwd=cmd, yaw=0.0)
        x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        fell = False
        ep_rms = []
        for t in range(args.steps):
            a, _ = m.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(a)
            action_deg = np.abs(np.clip(np.asarray(a), -1.0, 1.0)) * scale_deg
            ep_rms.append(float(np.sqrt(np.mean(action_deg ** 2))))
            if term:
                fell = True
                break
        x1 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        n_steps = len(ep_rms)
        speeds.append((x1 - x0) / max(1, n_steps) * 80.0)
        rms_all.extend(ep_rms)
        falls += fell
    env.close()
    return {
        "cmd": cmd, "band": BANDS[cmd], "falls": falls, "fall_rate": falls / args.episodes,
        "residual_rms_mean": float(np.mean(rms_all)),
        "speed_mps_mean": float(np.mean(speeds)),
        "speed_err_mean": float(np.mean(speeds) - cmd),
    }


if __name__ == "__main__":
    out = {}
    for ckpt in args.checkpoints:
        rows = [probe(ckpt, c) for c in SPEEDS]
        out[ckpt] = rows
        print(f"\n=== {ckpt} ===")
        for band in ("creep", "cruise", "fast"):
            band_rows = [r for r in rows if r["band"] == band]
            mean_rms = np.mean([r["residual_rms_mean"] for r in band_rows])
            mean_err = np.mean([r["speed_err_mean"] for r in band_rows])
            falls = sum(r["falls"] for r in band_rows)
            print(f"  {band:8s} residual_rms={mean_rms:.2f}deg  speed_err={mean_err:+.3f}m/s  falls={falls}")
        for r in rows:
            print(f"    cmd={r['cmd']:.3f} ({r['band']:6s})  rms={r['residual_rms_mean']:.2f}deg  "
                  f"speed={r['speed_mps_mean']:.3f} (err {r['speed_err_mean']:+.3f})  falls={r['falls']}")
    if args.json_out:
        json.dump(out, open(args.json_out, "w"), indent=1)
        print("\nwrote", args.json_out)
