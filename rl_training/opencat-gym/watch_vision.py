"""Local addition (not part of upstream ger01d/opencat-gym): visualise the sim's
forward "vision" -- the _scan_terrain ray fan that stands in for the camera +
detector. Draws the 9 rays in the GUI (green = clear, red = hit) and prints the
4-float terrain feature [present, dist_norm, bearing_norm, tall_flag] live.

The policy driving the robot is the normal vision-BLIND run20m_ppo -- it was
never trained on this feature, so it walks into things. The point is to see what
the vision layer computes, not to see avoidance (that policy doesn't exist yet).

MUST be run from your own terminal -- pybullet's GUI window does not appear when
launched from a background/detached process.

  python watch_vision.py                       # run20m_ppo among scattered boxes
  python watch_vision.py trained/run20m_slopefix_ppo
"""
import argparse
import time

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint", nargs="?", default="trained/run20m_ppo")
args = ap.parse_args()

import opencat_gym_env
opencat_gym_env.GUI_MODE = True
# Force the obstacle course on, full strength, every episode, and make the boxes
# tall enough to be worth seeing (and to trip tall_flag, threshold 0.055 m).
opencat_gym_env.DR_EVAL_FULL = True
opencat_gym_env.RANDOM_TERRAIN = 0.06
opencat_gym_env.RANDOM_TERRAIN_MAX_H = 0.06
from opencat_gym_env import (OpenCatGymEnv, TERRAIN_RANGE, TERRAIN_FOV_DEG)

env = OpenCatGymEnv()
obs, info = env.reset()

from stable_baselines3 import PPO
model = PPO.load(args.checkpoint)

import pybullet as p

FOV = np.deg2rad(TERRAIN_FOV_DEG)
BEARINGS = np.linspace(-FOV, FOV, 9)
_line_ids = [None] * 9
_txt_id = None


def _draw_scan():
    """Redraw the ray fan the same geometry _scan_terrain uses, colouring each
    ray by whether it hits non-ground, non-robot collision geometry."""
    global _line_ids, _txt_id
    base_pos, base_orn = p.getBasePositionAndOrientation(env.robot_id)
    yaw = p.getEulerFromQuaternion(base_orn)[2]
    ignore = {0, env.robot_id}
    for attr in ("_payload_id", "_head_id"):
        v = getattr(env, attr, None)
        if v is not None:
            ignore.add(v)
    z = base_pos[2] - 0.08 + 0.02
    cx = base_pos[0] + 0.05 * np.cos(yaw)
    cy = base_pos[1] + 0.05 * np.sin(yaw)
    froms = [[cx, cy, z]] * 9
    tos = [[cx + TERRAIN_RANGE * np.cos(yaw + b),
            cy + TERRAIN_RANGE * np.sin(yaw + b), z] for b in BEARINGS]
    for k, hit in enumerate(p.rayTestBatch(froms, tos)):
        blocked = hit[0] >= 0 and hit[0] not in ignore
        end = list(hit[3]) if blocked else tos[k]
        colour = [1, 0, 0] if blocked else [0, 0.9, 0]
        kw = dict(lineColorRGB=colour, lineWidth=2)
        if _line_ids[k] is None:
            _line_ids[k] = p.addUserDebugLine(froms[k], end, **kw)
        else:
            _line_ids[k] = p.addUserDebugLine(froms[k], end,
                                              replaceItemUniqueId=_line_ids[k], **kw)
    present, dist_n, bearing_n, tall = env._scan_terrain()
    label = (f"vision:  present={present:.0f}  dist={dist_n:.2f}  "
             f"bearing={bearing_n:+.2f}  tall={tall:.0f}")
    if _txt_id is None:
        _txt_id = p.addUserDebugText(label, [0, 0, 0.25], textColorRGB=[1, 1, 0],
                                     textSize=1.3)
    else:
        _txt_id = p.addUserDebugText(label, [0, 0, 0.25], textColorRGB=[1, 1, 0],
                                     textSize=1.3, replaceItemUniqueId=_txt_id)
    p.resetDebugVisualizerCamera(0.7, 50, -25, base_pos)


try:
    step = 0
    while True:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        _draw_scan()
        time.sleep(1 / 60)
        step += 1
        if step % 15 == 0:
            present, dist_n, bearing_n, tall = env._scan_terrain()
            print(f"step {step:5d}   present={present:.0f}  dist_norm={dist_n:.2f}  "
                  f"bearing_norm={bearing_n:+.2f}  tall_flag={tall:.0f}")
        if terminated or truncated:
            obs, info = env.reset()
            step = 0
except (KeyboardInterrupt, p.error):
    pass
finally:
    try:
        env.close()
    except p.error:
        pass
