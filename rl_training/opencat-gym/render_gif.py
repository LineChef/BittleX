"""Render one deterministic episode of a trained policy to an animated GIF.

Usage: python render_gif.py trained/auto_r2_iter3_ppo out.gif [--steps 240] [--stride 2]
"""
import argparse
import numpy as np
import pybullet as p

import opencat_gym_env
opencat_gym_env.GUI_MODE = False
from opencat_gym_env import OpenCatGymEnv

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("out")
ap.add_argument("--steps", type=int, default=240)
ap.add_argument("--stride", type=int, default=2)   # keep every Nth frame
ap.add_argument("--w", type=int, default=360)
ap.add_argument("--h", type=int, default=270)
# DR test overrides (same semantics as evaluate_policy.py): any --dr-* zeroes
# every DR knob, applies the ones passed, and forces full strength (dr = 1) so
# the GIF shows the policy on a specific held-out course.
ap.add_argument("--dr-friction", type=float, default=None)
ap.add_argument("--dr-mass", type=float, default=None)
ap.add_argument("--dr-gyro", type=float, default=None)
ap.add_argument("--dr-push", type=float, default=None)
ap.add_argument("--dr-terrain", type=float, default=None)
args = ap.parse_args()

_dr = {"RANDOM_FRICTION": args.dr_friction, "RANDOM_MASS": args.dr_mass,
       "RANDOM_GYRO": args.dr_gyro, "RANDOM_PUSH": args.dr_push,
       "RANDOM_TERRAIN": args.dr_terrain}
if any(v is not None for v in _dr.values()):
    for k in _dr:
        setattr(opencat_gym_env, k, 0.0)
    for k, v in _dr.items():
        if v is not None:
            setattr(opencat_gym_env, k, v)
    opencat_gym_env.DR_EVAL_FULL = True

from stable_baselines3 import PPO
env = OpenCatGymEnv()
model = PPO.load(args.checkpoint)
obs, _ = env.reset()
rid = env.robot_id

frames = []
for t in range(args.steps):
    action, _ = model.predict(obs, deterministic=True)
    obs, _, term, trunc, _ = env.step(action)
    if t % args.stride == 0:
        pos = p.getBasePositionAndOrientation(rid)[0]
        _, _, rgb, _, _ = p.getCameraImage(
            args.w, args.h,
            viewMatrix=p.computeViewMatrixFromYawPitchRoll(
                cameraTargetPosition=[pos[0], pos[1], 0.05], distance=0.55,
                yaw=50, pitch=-30, roll=0, upAxisIndex=2),
            projectionMatrix=p.computeProjectionMatrixFOV(60, args.w / args.h, 0.1, 5),
            renderer=p.ER_TINY_RENDERER)
        frames.append(np.reshape(rgb, (args.h, args.w, 4))[:, :, :3].astype(np.uint8))
    if term or trunc:
        obs, _ = env.reset()
        rid = env.robot_id
env.close()

from PIL import Image
imgs = [Image.fromarray(f) for f in frames]
imgs[0].save(args.out, save_all=True, append_images=imgs[1:],
             duration=int(1000 * args.stride / 50), loop=0, optimize=True)
print(f"{args.out}: {len(imgs)} frames")
