"""Log the raw residual-action magnitude per step, alongside tilt, so the
"does the policy actually deviate from the scripted gait, and when" question
can be shown rather than just described. Forces an obstacle+push scenario by
default so a disturbance actually happens in the episode.

Usage:
  python action_trace.py trained/run20m_ppo --json-out trace_run20m.json
"""
import argparse
import json

import numpy as np
import pybullet as p

import opencat_gym_env
opencat_gym_env.GUI_MODE = False
from opencat_gym_env import OpenCatGymEnv

EPISODE_CAP = 250

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--dr-terrain", type=float, default=0.012)
    ap.add_argument("--dr-push", type=float, default=0.35)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    from stable_baselines3 import PPO

    # Force a real disturbance scenario (obstacles + shoves), zeroing every
    # other DR knob first so training config doesn't leak in -- same pattern
    # as evaluate_policy.py's --dr-* handling.
    for k in ("RANDOM_FRICTION", "RANDOM_MASS", "RANDOM_GYRO", "RANDOM_PUSH", "RANDOM_TERRAIN"):
        setattr(opencat_gym_env, k, 0.0)
    setattr(opencat_gym_env, "RANDOM_TERRAIN", args.dr_terrain)
    setattr(opencat_gym_env, "RANDOM_PUSH", args.dr_push)
    opencat_gym_env.DR_EVAL_FULL = True

    scale_deg = float(getattr(opencat_gym_env, "RESIDUAL_SCALE_DEG", 22))

    env = OpenCatGymEnv()
    model = PPO.load(args.checkpoint)

    obs, _ = env.reset(seed=args.seed)
    trace = {"step": [], "action_deg_rms": [], "action_deg_max": [],
             "tilt_deg": [], "r_imitation": []}
    steps = 0
    while True:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        steps += 1

        # SB3's Gaussian policy isn't squashed to the action_space box, so the
        # raw sampled action can exceed +/-1 before the env's own final hard
        # joint-angle clip (BOUND_ANG=110deg) catches it -- clip here too so
        # this reflects the nominal per-joint degree budget, not a raw value
        # that can read above the ceiling.
        action_deg = np.abs(np.clip(np.asarray(action), -1.0, 1.0)) * scale_deg
        _, orn = p.getBasePositionAndOrientation(env.robot_id)
        roll, pitch, _ = p.getEulerFromQuaternion(orn)
        trace["step"].append(steps)
        trace["action_deg_rms"].append(float(np.sqrt(np.mean(action_deg ** 2))))
        trace["action_deg_max"].append(float(np.max(action_deg)))
        trace["tilt_deg"].append(float(np.degrees(max(abs(roll), abs(pitch)))))
        trace["r_imitation"].append(float(info.get("r_imitation", 0.0)))

        if terminated or truncated or steps >= EPISODE_CAP:
            break

    trace["checkpoint"] = args.checkpoint
    trace["residual_scale_deg"] = scale_deg
    trace["fell"] = bool(terminated and steps < EPISODE_CAP)
    with open(args.json_out, "w") as f:
        json.dump(trace, f)
    print(f"wrote {args.json_out}  ({steps} steps, fell={trace['fell']}, "
          f"mean action_deg_rms={np.mean(trace['action_deg_rms']):.3f}, "
          f"max action_deg_max={np.max(trace['action_deg_max']):.3f})")
