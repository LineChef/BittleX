"""Goal-directed locomotion eval (Phase A gate instrument).

Drives a checkpoint to goals at fixed bearings and reports whether it turns to
face and reaches them, plus a no-goal block that checks straight-line walking
survived. Set the same G2E_* flags the checkpoint was trained with.

  G2E_GOAL_MODE=1 G2E_TERRAIN_FEATURE=1 G2E_EPISODE_LENGTH=1200 \
    python benchmark_goal.py trained/goalA_ppo --episodes 12 --json-out /tmp/goalA.json
"""
import argparse
import json

import numpy as np
import pybullet as p

import opencat_gym_env
from opencat_gym_env import OpenCatGymEnv, GOAL_STANDOFF, CONTROL_HZ
from stable_baselines3 import PPO

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("--episodes", type=int, default=12)
ap.add_argument("--dist", type=float, default=1.5)
ap.add_argument("--seed0", type=int, default=7000)
ap.add_argument("--json-out", default=None)
args = ap.parse_args()

BEARINGS_DEG = [0, 45, 90, 135, 180]

model = PPO.load(args.checkpoint, device="cpu")
env = OpenCatGymEnv()
CAP = int(getattr(opencat_gym_env, "EPISODE_LENGTH", 1200))


def spawn_xy():
    return np.array(p.getBasePositionAndOrientation(env.robot_id)[0][:2])


def run_goal(bearing_rad):
    reached = steps_r = fell = 0
    finals, effs = [], []
    for e in range(args.episodes):
        np.random.seed(args.seed0 + int(np.degrees(bearing_rad)) * 97 + e)
        env.set_goal(bearing_rad, args.dist)
        obs, _ = env.reset()
        p0 = spawn_xy()
        path = 0.0
        prev = p0.copy()
        got = None
        for t in range(CAP):
            a, _ = model.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(a)
            cur = spawn_xy()
            path += float(np.linalg.norm(cur - prev)); prev = cur
            d = info.get("goal_dist_m", 9.9)
            if d < GOAL_STANDOFF and got is None:
                got = t + 1
            if term and t + 1 < CAP and got is None:
                fell += 1
                break
            if trunc:
                break
        final_d = env.set_goal and info.get("goal_dist_m", 9.9)
        finals.append(final_d)
        if got is not None:
            reached += 1
            steps_r += got
            straight = args.dist - GOAL_STANDOFF
            effs.append(straight / max(path, 1e-6))
    n = args.episodes
    return dict(
        bearing_deg=round(float(np.degrees(bearing_rad)), 0),
        reach_rate=round(reached / n, 3),
        mean_steps_to_reach=round(steps_r / reached, 1) if reached else None,
        mean_final_dist_m=round(float(np.mean(finals)), 3),
        path_efficiency=round(float(np.mean(effs)), 3) if effs else None,
        fall_rate=round(fell / n, 3),
    )


def run_nogoal():
    drifts, speeds, fell = [], [], 0
    for e in range(args.episodes):
        np.random.seed(args.seed0 + 5000 + e)
        env.set_goal("none")
        env.set_command(fwd=0.10, yaw=0.0)
        obs, _ = env.reset()
        yaw0 = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])[2]
        xs = [spawn_xy()[0]]
        for t in range(CAP):
            a, _ = model.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(a)
            xs.append(spawn_xy()[0])
            if term and t + 1 < CAP:
                fell += 1
                break
            if trunc:
                break
        yaw1 = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])[2]
        drifts.append(abs(np.degrees((yaw1 - yaw0 + np.pi) % (2 * np.pi) - np.pi)))
        speeds.append((xs[-1] - xs[0]) / (len(xs) / CONTROL_HZ))
    env.set_goal(None); env.set_command(fwd=None, yaw=None)
    return dict(heading_drift_deg=round(float(np.mean(drifts)), 1),
               fwd_speed_mps=round(float(np.mean(speeds)), 3),
               fall_rate=round(fell / args.episodes, 3))


results = {"checkpoint": args.checkpoint, "episodes": args.episodes,
           "goals": [run_goal(np.radians(b)) for b in BEARINGS_DEG],
           "no_goal_cruise": run_nogoal()}
env.close()

print(f"\n### {args.checkpoint}   ({args.episodes} ep/cell, goal dist {args.dist} m)")
print(f"{'bearing':>8}{'reach':>8}{'steps':>8}{'final_m':>9}{'path_eff':>9}{'fell':>7}")
for g in results["goals"]:
    print(f"{g['bearing_deg']:>7.0f}d{g['reach_rate']:>8}{str(g['mean_steps_to_reach']):>8}"
          f"{g['mean_final_dist_m']:>9}{str(g['path_efficiency']):>9}{g['fall_rate']:>7}")
c = results["no_goal_cruise"]
print(f"\n  no-goal cruise:  heading drift {c['heading_drift_deg']} deg   "
      f"fwd {c['fwd_speed_mps']} m/s   fell {c['fall_rate']}")

if args.json_out:
    with open(args.json_out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {args.json_out}")
