"""Render the foot-probing prototype (proactive trigger -> freeze -> lift ->
forward-reach -> downward-search) to a GIF, since GUI mode doesn't produce a
visible window on this machine -- a file the user can just open, matching the
project's existing leg-tinting-GIF convention.

Captures at a fixed cadence (every CAPTURE_EVERY physics steps) with a fixed
per-frame duration, rather than one capture per step with a computed
duration -- GIF viewers commonly round any frame delay under ~30ms up to
~100ms (a legacy Netscape-era compatibility rule), which silently wrecked an
earlier version of this script's attempt at exact real-time playback via
tiny per-frame durations. A fixed ~67ms/frame cadence stays safely above
that rounding threshold everywhere.

    python probe_foot_gif.py trained/run20m_resid30_ppo out.gif --ledge-h 0.027
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

FL_SHOULDER, FL_KNEE, PAW_LF = 0, 1, 3
EDGE_X = 0.11
FRAME_MS = 67   # fixed display duration/frame -- safely above the ~30ms
                # rounding threshold many GIF viewers silently bump up to 100ms

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("out")
ap.add_argument("--ledge-h", type=float, default=0.027)
ap.add_argument("--search-depth-m", type=float, default=0.06)
ap.add_argument("--lift-force", type=float, default=0.2)
ap.add_argument("--reach-past-edge-m", type=float, default=0.035)
ap.add_argument("--seed", type=int, default=7000)
ap.add_argument("--w", type=int, default=480)
ap.add_argument("--h", type=int, default=360)
ap.add_argument("--hold-final-frames", type=int, default=15)
ap.add_argument("--speed", type=float, default=3.0,
                help="playback speed relative to real time -- the quasi-static "
                     "probe phases take many small physics steps for precision, "
                     "which is genuinely long in real time even at 1x")
args = ap.parse_args()

# frames-per-capture needed so FRAME_MS of playback = args.speed x that much real sim time
CAPTURE_EVERY = max(1, round(FRAME_MS / 1000 * 60 * args.speed))

if args.ledge_h > 0:
    _apply({"LEDGE_HEIGHT": args.ledge_h, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1})
else:
    _apply({})

from stable_baselines3 import PPO
env = OpenCatGymEnv()
model = PPO.load(args.checkpoint)

np.random.seed(args.seed)
obs, _ = env.reset()
env.set_command(fwd=0.10, yaw=0.0)
setup_leg_tint(env)
rid = env.robot_id

frames = []
durations = []
_step_count = 0


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
    durations.append(FRAME_MS)


def sim_step():
    """One physics step, capturing a frame every CAPTURE_EVERY steps."""
    global _step_count
    p.stepSimulation()
    _step_count += 1
    if _step_count % CAPTURE_EVERY == 0:
        _snap()


print(f"Walking toward the ledge (h={args.ledge_h*1000:.0f}mm)...")
for t in range(150):
    a, _ = model.predict(obs, deterministic=True)
    obs, r, term, trunc, info = env.step(a)
    apply_leg_tint(env, a)
    _step_count += 1
    if _step_count % CAPTURE_EVERY == 0:
        _snap()
    if term:
        print("fell before reaching the probe point -- restart with a different seed")
        raise SystemExit
    paw_x = p.getLinkState(rid, PAW_LF)[0][0]
    loaded = bool(p.getContactPoints(bodyA=rid, linkIndexA=PAW_LF))
    bo = p.getBasePositionAndOrientation(rid)[1]
    tilt = max(abs(x) for x in p.getEulerFromQuaternion(bo)[0:2])
    if (EDGE_X - 0.03) < paw_x <= EDGE_X and not loaded and tilt < np.deg2rad(5.0):
        break
print(f"  triggered at paw_x={paw_x:.3f}, tilt={np.rad2deg(tilt):.1f}deg")

print("Freezing pose...")
js_now = p.getJointStates(rid, env.joint_id)
hold_targets = np.array([j[0] for j in js_now])
paw_start = p.getLinkState(rid, PAW_LF)[0]
for _ in range(15):
    p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL,
                                 hold_targets, forces=np.ones(8) * 0.2)
    sim_step()

LIFT_M = 0.020
lift_steps = 15
for s in range(lift_steps):
    frac = (s + 1) / lift_steps
    clear_pos = [paw_start[0], paw_start[1], paw_start[2] + LIFT_M * frac]
    ik0 = p.calculateInverseKinematics(rid, PAW_LF, clear_pos)
    lift_targets = hold_targets.copy()
    lift_targets[FL_SHOULDER] = ik0[FL_SHOULDER]
    lift_targets[FL_KNEE] = ik0[FL_KNEE]
    for _wait in range(10):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL,
                                     lift_targets, forces=np.ones(8) * args.lift_force)
        sim_step()
        paw_now = p.getLinkState(rid, PAW_LF)[0]
        if abs(paw_now[2] - clear_pos[2]) < 0.002:
            break
clear_origin = p.getLinkState(rid, PAW_LF)[0]
print(f"Lift done: paw z {paw_start[2]:.4f} -> {clear_origin[2]:.4f} "
      f"({(clear_origin[2]-paw_start[2])*1000:.1f}mm of the intended {LIFT_M*1000:.0f}mm)")

reach_target_x = EDGE_X + args.reach_past_edge_m
print(f"Reaching forward past the edge (paw x {clear_origin[0]:.3f} -> {reach_target_x:.3f})...")
reach_steps = 15
for s in range(reach_steps):
    frac = (s + 1) / reach_steps
    reach_pos = [clear_origin[0] + (reach_target_x - clear_origin[0]) * frac,
                 clear_origin[1], clear_origin[2]]
    ikr = p.calculateInverseKinematics(rid, PAW_LF, reach_pos)
    reach_targets = hold_targets.copy()
    reach_targets[FL_SHOULDER] = ikr[FL_SHOULDER]
    reach_targets[FL_KNEE] = ikr[FL_KNEE]
    for _wait in range(10):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL,
                                     reach_targets, forces=np.ones(8) * args.lift_force)
        sim_step()
        paw_now = p.getLinkState(rid, PAW_LF)[0]
        if abs(paw_now[0] - reach_pos[0]) < 0.003:
            break
search_origin = p.getLinkState(rid, PAW_LF)[0]
print(f"Reach done: paw x {clear_origin[0]:.3f} -> {search_origin[0]:.3f} (target {reach_target_x:.3f}), "
      f"z {search_origin[2]:.4f}")

print("Searching downward for the floor...")
n_increments = 30
pos_tol = 0.003
contact_at = None
for s in range(n_increments):
    frac = (s + 1) / n_increments
    target_pos = [search_origin[0], search_origin[1],
                  search_origin[2] - args.search_depth_m * frac]
    ik = p.calculateInverseKinematics(rid, PAW_LF, target_pos)
    targets = hold_targets.copy()
    targets[FL_SHOULDER] = ik[FL_SHOULDER]
    targets[FL_KNEE] = ik[FL_KNEE]
    converged = False
    for _wait in range(10):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL,
                                     targets, forces=np.ones(8) * args.lift_force)
        sim_step()
        paw_now = p.getLinkState(rid, PAW_LF)[0]
        if abs(paw_now[2] - target_pos[2]) < pos_tol:
            converged = True
            break
    if not converged:
        contact_at = args.search_depth_m * frac * 1000
        confirmed = bool(p.getContactPoints(bodyA=rid, linkIndexA=PAW_LF))
        print(f"Stopped: resistance found at {contact_at:.1f}mm of search depth "
              f"(ground-truth contact confirmed: {confirmed})")
        break
if contact_at is None:
    print("Reached the full search depth without finding resistance.")

for _ in range(args.hold_final_frames):
    _snap()
    durations[-1] = 150  # deliberate pause at the end, not real sim time

env.close()

from PIL import Image
imgs = [Image.fromarray(f) for f in frames]
imgs[0].save(args.out, save_all=True, append_images=imgs[1:], duration=durations, loop=0, optimize=True)
total_s = sum(durations) / 1000
print(f"{args.out}: {len(imgs)} frames, ~{total_s:.1f}s playback")
