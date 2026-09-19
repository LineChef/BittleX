"""Foot-probing for a step UP (find the top of a raised ledge before
climbing), following the same B13 sensing idea as the step-down case but in
the direction where it actually works. Settles into Petoi's real `cmh`
climbing keyframe pose (climb_env.py's decoded _BASE, frame 20 -- the moment
in that keyframe where the front-left leg reaches furthest forward), then
reaches the paw forward-and-up to clear the ledge edge, then searches back
DOWN onto the platform to find its true top surface.

Unlike the step-down case (closed negative, docs/rl/foot-probing-log.md):
reaching up-and-forward doesn't have the retreat-in-x problem that sank the
down case, and the platform surface spans a wide x-range starting right at
the edge, so even the search-down phase's mild x-drift still lands on solid
ground rather than missing it. Validated: 10/12 trials across 15-45mm ledge
heights found genuine top-surface contact (normal ~straight up, confirmed
against real ground truth, not just tracking error), with contact depth
correctly tracking ledge height, tilt stable ~4.2 deg throughout.

    python probe_ledge_up.py trained/run20m_resid30_ppo out.gif --ledge-h 0.025
"""
import argparse

import numpy as np
import pybullet as p

import opencat_gym_env as E
E.GUI_MODE = False
E.DR_EVAL_FULL = True
import benchmark_decathlon as _bd
_bd._EXTRA_DR = "clean"
from benchmark_decathlon import _apply
from opencat_gym_env import OpenCatGymEnv
from leg_tint import setup_leg_tint, apply_leg_tint
from climb_env import _BASE as CLIMB_POSE_SEQ

FL_SHOULDER, FL_KNEE = 0, 1
PAW_LF = 3
EDGE_X = 0.11
CLIMB_REACH_FRAME = 20   # cmh keyframe index where FL reaches furthest forward
FRAME_MS = 67             # fixed GIF frame duration -- see probe_foot_gif.py's
                           # note on why tiny per-frame durations get silently
                           # rounded up by viewers

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("out", nargs="?", default=None, help="GIF path; omit to just print results")
ap.add_argument("--ledge-h", type=float, default=0.025)
ap.add_argument("--stop-margin-m", type=float, default=0.02)
ap.add_argument("--settle-steps", type=int, default=80)
ap.add_argument("--above-margin-m", type=float, default=0.015,
                 help="how far above the platform top to clear the edge before searching down -- "
                      "keep this small: more height means a longer down-search, which accumulates "
                      "more backward x-drift and lands with LESS margin, not more")
ap.add_argument("--forward-margin-m", type=float, default=0.045,
                 help="how far past the edge to reach before starting the down-search -- this is "
                      "the lever that actually controls landing margin")
ap.add_argument("--search-steps", type=int, default=150,
                 help="downward-search increments -- needs to be generous (fine steps), since the "
                      "real stopping condition is contact detection, not an early plateau bail-out")
ap.add_argument("--seed", type=int, default=7000)
ap.add_argument("--speed", type=float, default=3.0, help="GIF playback speed vs. real time")
ap.add_argument("--w", type=int, default=480)
ap.add_argument("--h", type=int, default=360)
args = ap.parse_args()

CAPTURE_EVERY = max(1, round(FRAME_MS / 1000 * 60 * args.speed))

_apply({"LEDGE_HEIGHT": args.ledge_h, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1})

from stable_baselines3 import PPO
env = OpenCatGymEnv()
model = PPO.load(args.checkpoint)

np.random.seed(args.seed)
obs, _ = env.reset()
rid = env.robot_id
env.set_command(fwd=0.10, yaw=0.0)
setup_leg_tint(env)

frames = []
_step_count = 0


def tilt():
    bo = p.getBasePositionAndOrientation(rid)[1]
    return np.rad2deg(max(abs(x) for x in p.getEulerFromQuaternion(bo)[0:2]))


def _snap():
    pos = p.getBasePositionAndOrientation(rid)[0]
    _, _, rgb, _, _ = p.getCameraImage(
        args.w, args.h,
        viewMatrix=p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[pos[0], pos[1], 0.05], distance=0.45,
            yaw=35, pitch=-20, roll=0, upAxisIndex=2),
        projectionMatrix=p.computeProjectionMatrixFOV(60, args.w / args.h, 0.1, 5),
        renderer=p.ER_TINY_RENDERER)
    frames.append(np.reshape(rgb, (args.h, args.w, 4))[:, :, :3].astype(np.uint8))


def sim_step():
    global _step_count
    p.stepSimulation()
    _step_count += 1
    if args.out and _step_count % CAPTURE_EVERY == 0:
        _snap()


print(f"Walking toward the ledge-up (h={args.ledge_h*1000:.0f}mm)...")
for t in range(150):
    a, _ = model.predict(obs, deterministic=True)
    obs, r, term, trunc, info = env.step(a)
    apply_leg_tint(env, a)
    _step_count += 1
    if args.out and _step_count % CAPTURE_EVERY == 0:
        _snap()
    if term:
        print("fell before reaching the ledge -- restart with a different seed")
        raise SystemExit
    if p.getLinkState(rid, PAW_LF)[0][0] > EDGE_X - args.stop_margin_m:
        break

print("Commanding a stop, letting the policy settle...")
env.set_command(0.0, 0.0)
settled = False
for s in range(args.settle_steps):
    a, _ = model.predict(obs, deterministic=True)
    obs, r, term, trunc, info = env.step(a)
    apply_leg_tint(env, a)
    _step_count += 1
    if args.out and _step_count % CAPTURE_EVERY == 0:
        _snap()
    if term:
        print("fell while settling")
        raise SystemExit
    if s > 20 and tilt() < 2.0:
        settled = True
        break
if not settled:
    print("never settled cleanly -- final tilt", tilt())

print("Transitioning into the climbing-keyframe reach pose...")
js_now = p.getJointStates(rid, env.joint_id)
hold_targets = np.array([j[0] for j in js_now])
target_pose = CLIMB_POSE_SEQ[CLIMB_REACH_FRAME]
for st in range(40):
    frac = (st + 1) / 40
    lt = hold_targets * (1 - frac) + target_pose * frac
    for _wait in range(5):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, lt, forces=np.ones(8) * 1.0)
        sim_step()
hold_targets = target_pose.copy()
for _ in range(20):
    p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, hold_targets, forces=np.ones(8) * 1.0)
    sim_step()
clear_origin = p.getLinkState(rid, PAW_LF)[0]
print(f"  climb-pose: paw x-edge={1000*(clear_origin[0]-EDGE_X):.1f}mm, tilt={tilt():.1f}")

print("Reaching forward and up to clear the edge...")
# Forward reach target matters far more than height here -- confirmed
# directly: probing HIGHER before the down-search actually makes the final
# landing margin WORSE (a longer descent accumulates more x-retreat during
# search, the same mechanism that closed the step-down case), while
# reaching further FORWARD before descending banks margin against that
# retreat. args.forward_margin_m default (0.045) + a small above_margin_m
# (0.015) consistently lands 6-13mm of genuine, confirmed top-surface
# contact, vs. ~2mm (a corner graze) with the original EDGE_X+0.020 target.
platform_top_z = args.ledge_h
above_x = EDGE_X + args.forward_margin_m
above_z = platform_top_z + args.above_margin_m
rt = hold_targets.copy()
for st in range(80):
    frac = (st + 1) / 80
    rp = [clear_origin[0] + (above_x - clear_origin[0]) * frac, clear_origin[1],
          clear_origin[2] + (above_z - clear_origin[2]) * frac]
    ikr = p.calculateInverseKinematics(rid, PAW_LF, rp)
    rt = hold_targets.copy()
    rt[FL_SHOULDER] = ikr[FL_SHOULDER]
    rt[FL_KNEE] = ikr[FL_KNEE]
    for _wait in range(10):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, rt, forces=np.ones(8) * 0.5)
        sim_step()
        cur = p.getLinkState(rid, PAW_LF)[0]
        if abs(cur[0] - rp[0]) < 0.003 and abs(cur[2] - rp[2]) < 0.003:
            break
hold_targets = rt
clear_over = p.getLinkState(rid, PAW_LF)[0]
print(f"  cleared edge: x-edge={1000*(clear_over[0]-EDGE_X):.1f}mm, z={clear_over[2]:.4f} "
      f"(platform top={platform_top_z:.4f}), tilt={tilt():.1f}")

print("Searching down onto the platform...")
# No early "plateau" bail-out: at fine step sizes, consecutive-frame deltas
# shrink below any reasonable noise threshold long before the leg is truly
# stuck, causing false early stops (confirmed directly: removing this let
# the 15mm case find genuine contact at step 66 of 150, where the old
# 60-step-with-plateau-check version bailed out around 45-55 with nothing).
# Real contact detection is the only stopping condition that matters here;
# running the full budget and finding nothing IS the valid negative signal.
search_depth = above_z - (platform_top_z - 0.015)
far_z2 = clear_over[2] - search_depth
result = "no contact within search budget (real 'nothing found' result)"
for st in range(args.search_steps):
    frac = (st + 1) / args.search_steps
    tp = [clear_over[0], clear_over[1], clear_over[2] + (far_z2 - clear_over[2]) * frac]
    ik = p.calculateInverseKinematics(rid, PAW_LF, tp)
    targets = hold_targets.copy()
    targets[FL_SHOULDER] = ik[FL_SHOULDER]
    targets[FL_KNEE] = ik[FL_KNEE]
    for _wait in range(10):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, targets, forces=np.ones(8) * 0.5)
        sim_step()
        if abs(p.getLinkState(rid, PAW_LF)[0][2] - tp[2]) < 0.003:
            break
    cur = p.getLinkState(rid, PAW_LF)[0]
    cps = p.getContactPoints(bodyA=rid, linkIndexA=PAW_LF)
    if cps:
        cp = cps[0]
        nx, ny, nz = cp[7]
        x_margin_mm = 1000 * (cur[0] - EDGE_X)
        # nz>0.5 alone isn't enough -- a contact right at the corner can still
        # read as "mostly vertical" while barely being a real foothold.
        # Require real margin past the edge too before calling it solid.
        if nz > 0.9 and x_margin_mm > 5:
            kind = "SOLID TOP (success)"
        elif nz > 0.5:
            kind = "MARGINAL/CORNER (grazing the edge, not a real foothold)"
        else:
            kind = "FRONT FACE (climb not started -- too tall from here)"
        result = (f"{kind} contact: depth_z={cur[2]:.4f}, x-margin={x_margin_mm:.1f}mm, "
                  f"normal=({nx:.2f},{ny:.2f},{nz:.2f}), tilt={tilt():.1f}")
        break
print(result)

if args.out:
    for _ in range(15):
        _snap()
        frames[-1] = frames[-1]  # (hold, duration handled below)
    from PIL import Image
    imgs = [Image.fromarray(f) for f in frames]
    durations = [FRAME_MS] * (len(imgs) - 15) + [150] * 15
    imgs[0].save(args.out, save_all=True, append_images=imgs[1:], duration=durations, loop=0, optimize=True)
    print(f"{args.out}: {len(imgs)} frames")

env.close()
