"""Local addition (not part of upstream ger01d/opencat-gym): loads a saved
checkpoint and replays it deterministically in the PyBullet GUI, so training
results can be watched visually rather than just read from reward logs.

Usage:
  python watch_trained.py trained/smoke_test_ppo
  python watch_trained.py trained/auto_dr_iter1_ppo --dr-terrain 0.012   # on the obstacle course
  python watch_trained.py trained/auto_dr_iter1_ppo --dr-push 0.35       # with random shoves

Any --dr-* flag forces full-strength randomization (dr = 1) every episode.
"""
import argparse
import time

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint", nargs="?", default="trained/smoke_test_ppo")
ap.add_argument("--dr-friction", type=float, default=None)
ap.add_argument("--dr-mass", type=float, default=None)
ap.add_argument("--dr-gyro", type=float, default=None)
ap.add_argument("--dr-push", type=float, default=None)
ap.add_argument("--dr-terrain", type=float, default=None)
args = ap.parse_args()

import opencat_gym_env
opencat_gym_env.GUI_MODE = True
_dr = {"RANDOM_FRICTION": args.dr_friction, "RANDOM_MASS": args.dr_mass,
       "RANDOM_GYRO": args.dr_gyro, "RANDOM_PUSH": args.dr_push,
       "RANDOM_TERRAIN": args.dr_terrain}
if any(v is not None for v in _dr.values()):
    for k, v in _dr.items():
        if v is not None:
            setattr(opencat_gym_env, k, v)
    opencat_gym_env.DR_EVAL_FULL = True
    print("replay with DR forced on:", {k: getattr(opencat_gym_env, k) for k in _dr})
from opencat_gym_env import OpenCatGymEnv

# Connect to the GUI (env's __init__ calls p.connect) before importing
# stable_baselines3/torch -- doing it after causes PyBullet's macOS Metal GUI
# thread to fail silently ("Not connected to physics server" on first step).
env = OpenCatGymEnv()
obs, info = env.reset()

from stable_baselines3 import PPO
model = PPO.load(args.checkpoint)

import pybullet

try:
    while True:
        action, _state = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        time.sleep(1 / 60)
        if terminated or truncated:
            obs, info = env.reset()
except (KeyboardInterrupt, pybullet.error):
    pass  # Ctrl+C, or the GUI window was closed
finally:
    try:
        env.close()
    except pybullet.error:
        pass
