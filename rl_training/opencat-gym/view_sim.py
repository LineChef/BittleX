"""Local addition (not part of upstream ger01d/opencat-gym): opens the PyBullet
GUI and steps the environment with random actions so you can see the simulated
robot. No trained policy exists yet, so this is just random flailing -- useful
to confirm the simulated model/physics look right, not to preview a gait.
"""
import time

import opencat_gym_env
opencat_gym_env.GUI_MODE = True
from opencat_gym_env import OpenCatGymEnv
import pybullet

env = OpenCatGymEnv()
env.reset()

try:
    while True:
        obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
        time.sleep(1 / 60)
        if terminated or truncated:
            env.reset()
except (KeyboardInterrupt, pybullet.error):
    pass  # Ctrl+C, or the GUI window was closed
finally:
    try:
        env.close()
    except pybullet.error:
        pass
