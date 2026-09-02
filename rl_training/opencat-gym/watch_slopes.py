"""Local addition (not part of upstream ger01d/opencat-gym): replay a trained
checkpoint on DETERMINISTIC, clearly-visible ground slopes so the slope-handling
behaviour can be watched. Forces `SLOPE_FIXED_RP` and cycles uphill / downhill /
side-slope / training-style random tilt; disables the slip-patch and deformable-
ground knobs so only the slope is in play. Camera follows the robot.

Usage:
  python watch_slopes.py trained/cov_r1_slope_ppo
"""
import argparse
import time
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint", nargs="?", default="trained/cov_r1_slope_ppo")
args = ap.parse_args()

import opencat_gym_env
opencat_gym_env.GUI_MODE = True
# isolate the slope: turn off everything else the coverage loop may have left on
opencat_gym_env.SLIP_PATCH = 0.0
opencat_gym_env.DEFORM_GROUND = 0.0
opencat_gym_env.START_POSE_JITTER = 0.0
opencat_gym_env.STUCK_FOOT_PROB = 0.0
opencat_gym_env.SUSTAINED_FORCE = 0.0
opencat_gym_env.IMPULSE_PUSH = 0.0
opencat_gym_env.RANDOM_PUSH = 0.0
opencat_gym_env.RANDOM_TERRAIN = 0.0
opencat_gym_env.DR_EVAL_FULL = True

from opencat_gym_env import OpenCatGymEnv
import pybullet as p

D = np.deg2rad
# (label, (roll_rad, pitch_rad) or None for training-style random +/-10 both axes)
SLOPES = [
    ("UPHILL  +14 deg pitch", (0.0, D(14))),
    ("DOWNHILL -14 deg pitch", (0.0, D(-14))),
    ("SIDE-SLOPE +12 deg roll", (D(12), 0.0)),
    ("RANDOM tilt (training-style, +/-10 roll & pitch)", None),
]

env = OpenCatGymEnv()

from stable_baselines3 import PPO
model = PPO.load(args.checkpoint)

p.configureDebugVisualizerCamera if False else None


def set_slope(entry):
    label, rp = entry
    if rp is None:
        m = D(10.0)
        opencat_gym_env.SLOPE_FIXED_RP = (float(np.random.uniform(-m, m)),
                                          float(np.random.uniform(-m, m)))
        opencat_gym_env.SLOPE_MAX_DEG = 10.0
    else:
        opencat_gym_env.SLOPE_FIXED_RP = rp
    print(f"\n>>> {label}   (slope_rp deg = "
          f"{np.round(np.degrees(opencat_gym_env.SLOPE_FIXED_RP), 1)})", flush=True)


i = 0
set_slope(SLOPES[0])
obs, info = env.reset()
try:
    while True:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        pos = p.getBasePositionAndOrientation(env.robot_id)[0]
        p.resetDebugVisualizerCamera(cameraDistance=0.42, cameraYaw=50,
                                     cameraPitch=-22,
                                     cameraTargetPosition=[pos[0], pos[1], pos[2]])
        time.sleep(1 / 60)
        if terminated or truncated:
            print(f"    episode end: {'FELL' if terminated else 'survived full length'}",
                  flush=True)
            i = (i + 1) % len(SLOPES)
            set_slope(SLOPES[i])
            obs, info = env.reset()
except (KeyboardInterrupt, p.error):
    pass
finally:
    try:
        env.close()
    except p.error:
        pass
