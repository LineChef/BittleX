"""Local addition (not part of upstream ger01d/opencat-gym): loads a saved
checkpoint and replays it deterministically in the PyBullet GUI, so training
results can be watched visually rather than just read from reward logs.

Usage: python watch_trained.py trained/smoke_test_ppo
"""
import sys
import time

import opencat_gym_env
opencat_gym_env.GUI_MODE = True
from opencat_gym_env import OpenCatGymEnv

# Connect to the GUI (env's __init__ calls p.connect) before importing
# stable_baselines3/torch -- doing it after causes PyBullet's macOS Metal GUI
# thread to fail silently ("Not connected to physics server" on first step).
env = OpenCatGymEnv()
obs, info = env.reset()

from stable_baselines3 import PPO
checkpoint = sys.argv[1] if len(sys.argv) > 1 else "trained/smoke_test_ppo"
model = PPO.load(checkpoint)

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
