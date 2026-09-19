"""Render a few step-down-ledge episodes back to back into one GIF, holding
extra frames after each fall so the failure is actually visible (not just
the last pre-fall frame), for visually inspecting the D-ledge-2/D-ledge-3
100%-fall-despite-contact finding from resilience_dose_response.py.

    python render_ledge_falls.py trained/run20m_resid30_ppo out.gif --ledge-h 0.030 --n 3
"""
import argparse
import numpy as np
import pybullet as p

import opencat_gym_env
opencat_gym_env.GUI_MODE = False
opencat_gym_env.DR_EVAL_FULL = True
from opencat_gym_env import OpenCatGymEnv
from leg_tint import setup_leg_tint, apply_leg_tint

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("out")
ap.add_argument("--ledge-h", type=float, default=0.030)
ap.add_argument("--n", type=int, default=3, help="episodes to string together")
ap.add_argument("--steps", type=int, default=180)
ap.add_argument("--hold-frames", type=int, default=25, help="extra frames held after a fall")
ap.add_argument("--stride", type=int, default=2)
ap.add_argument("--w", type=int, default=360)
ap.add_argument("--h", type=int, default=270)
ap.add_argument("--payload-off", action="store_true", default=True)
ap.add_argument("--seed0", type=int, default=9000)
args = ap.parse_args()

import benchmark_decathlon as _bd
_bd._EXTRA_DR = "clean" if args.payload_off else "full"
from benchmark_decathlon import _apply
_apply({"LEDGE_HEIGHT": args.ledge_h, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1})

from stable_baselines3 import PPO
env = OpenCatGymEnv()
model = PPO.load(args.checkpoint)

frames = []


def _capture(rid):
    pos = p.getBasePositionAndOrientation(rid)[0]
    _, _, rgb, _, _ = p.getCameraImage(
        args.w, args.h,
        viewMatrix=p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[pos[0], pos[1], 0.05], distance=0.55,
            yaw=50, pitch=-30, roll=0, upAxisIndex=2),
        projectionMatrix=p.computeProjectionMatrixFOV(60, args.w / args.h, 0.1, 5),
        renderer=p.ER_TINY_RENDERER)
    return np.reshape(rgb, (args.h, args.w, 4))[:, :, :3].astype(np.uint8)


fell_count = 0
for ep in range(args.n):
    np.random.seed(args.seed0 + ep)
    obs, _ = env.reset()
    env.set_command(fwd=0.10, yaw=0.0)
    rid = env.robot_id
    setup_leg_tint(env)
    fell = False
    for t in range(args.steps):
        action, _ = model.predict(obs, deterministic=True)
        obs, _, term, trunc, _ = env.step(action)
        apply_leg_tint(env, action)
        if t % args.stride == 0:
            frames.append(_capture(rid))
        if term:
            fell = True
            break
    if fell:
        fell_count += 1
        for _ in range(args.hold_frames):   # hold the fallen pose so it's visible
            frames.append(_capture(rid))
env.close()
print(f"{fell_count}/{args.n} episodes fell (ledge_h={args.ledge_h*1000:.0f}mm)")

from PIL import Image
imgs = [Image.fromarray(f) for f in frames]
imgs[0].save(args.out, save_all=True, append_images=imgs[1:],
             duration=int(1000 * args.stride / 50), loop=0, optimize=True)
print(f"{args.out}: {len(imgs)} frames")
