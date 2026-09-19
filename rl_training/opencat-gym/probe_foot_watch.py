"""GUI replay of the foot-probing prototype (probe_foot_test.py's mechanism,
watchable) -- walks to a step-down ledge, lifts the front-left paw clear,
then quasi-statically searches downward for the true floor, pausing at each
sub-step so the motion (and the torque struggle currently being debugged) is
visible in real time.

    python probe_foot_watch.py trained/run20m_resid30_ppo --ledge-h 0.027
    python probe_foot_watch.py trained/run20m_resid30_ppo --ledge-h 0 --lift-force 1.0
"""
import argparse
import time

import numpy as np
import pybullet as p

import opencat_gym_env as E
E.GUI_MODE = True
E.DR_EVAL_FULL = True
import benchmark_decathlon as _bd
_bd._EXTRA_DR = "clean"
from benchmark_decathlon import _apply
from opencat_gym_env import OpenCatGymEnv
from leg_tint import setup_leg_tint, apply_leg_tint

FL_SHOULDER, FL_KNEE, PAW_LF = 0, 1, 3
EDGE_X = 0.11

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("--ledge-h", type=float, default=0.027)
ap.add_argument("--search-depth-m", type=float, default=0.06)
ap.add_argument("--lift-force", type=float, default=0.2,
                 help="force limit (Nm) for the lift+probe motion -- try higher to test the torque hypothesis")
ap.add_argument("--seed", type=int, default=7000)
args = ap.parse_args()

if args.ledge_h > 0:
    _apply({"LEDGE_HEIGHT": args.ledge_h, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1})
else:
    _apply({})

# Connect to the GUI (env's __init__ calls p.connect) before importing
# stable_baselines3/torch -- doing it after causes PyBullet's macOS Metal GUI
# thread to fail silently (matches watch_trained.py's documented fix).
env = OpenCatGymEnv()

from stable_baselines3 import PPO
model = PPO.load(args.checkpoint)

import pybullet_data
_checker_path = pybullet_data.getDataPath() + "/checker_blue.png"


def _fix_floor():
    try:
        tex = p.loadTexture(_checker_path)
        p.changeVisualShape(0, -1, rgbaColor=[1, 1, 1, 1], textureUniqueId=tex)
    except Exception:
        pass


np.random.seed(args.seed)
obs, _ = env.reset()
env.set_command(fwd=0.10, yaw=0.0)
setup_leg_tint(env)
_fix_floor()
rid = env.robot_id

print(f"Walking toward the ledge (h={args.ledge_h*1000:.0f}mm)...")
# PROACTIVE trigger, not reactive: stop while the paw is still APPROACHING
# the edge (not yet crossed it) and the body is still level -- confirmed
# directly (watched it happen) that triggering after the paw crosses the
# edge is often already too late, since the whole body starts pitching
# into the gap well before that point (tilt was already 17deg/8.8deg the
# moment the old "crossed + unloaded" trigger fired). Triggering earlier
# is the actual fix for "the probe needs to happen before commit."
for t in range(150):
    a, _ = model.predict(obs, deterministic=True)
    obs, r, term, trunc, info = env.step(a)
    apply_leg_tint(env, a)
    time.sleep(1 / 60)
    if term:
        print("fell before reaching the probe point -- restart with a different seed")
        raise SystemExit
    paw_x = p.getLinkState(rid, PAW_LF)[0][0]
    loaded = bool(p.getContactPoints(bodyA=rid, linkIndexA=PAW_LF))
    bo = p.getBasePositionAndOrientation(rid)[1]
    tilt = max(abs(a) for a in p.getEulerFromQuaternion(bo)[0:2])
    if (EDGE_X - 0.03) < paw_x <= EDGE_X and not loaded and tilt < np.deg2rad(5.0):
        break

print("At probe point. Freezing pose, then lifting the front-left paw...")
js_now = p.getJointStates(rid, env.joint_id)
hold_targets = np.array([j[0] for j in js_now])
paw_start = p.getLinkState(rid, PAW_LF)[0]

for _ in range(15):
    p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL,
                                 hold_targets, forces=np.ones(8) * 0.2)
    p.stepSimulation()
    time.sleep(1 / 60)

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
        p.stepSimulation()
        time.sleep(1 / 60)
        paw_now = p.getLinkState(rid, PAW_LF)[0]
        if abs(paw_now[2] - clear_pos[2]) < 0.002:
            break
clear_origin = p.getLinkState(rid, PAW_LF)[0]
print(f"Lift done: paw z {paw_start[2]:.4f} -> {clear_origin[2]:.4f} "
      f"({(clear_origin[2]-paw_start[2])*1000:.1f}mm of the intended 20mm)")

# Reach forward past the edge before searching down -- with the proactive
# trigger, the paw freezes BEFORE crossing EDGE_X, so a straight-down
# search from here just re-finds the platform it's still standing on
# (confirmed: found "resistance" at 4mm, trivially, on solid ground).
# The probe only tells us anything about the step ahead if it reaches
# past the edge line first.
REACH_PAST_EDGE_M = 0.035
reach_target_x = EDGE_X + REACH_PAST_EDGE_M
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
        p.stepSimulation()
        time.sleep(1 / 60)
        paw_now = p.getLinkState(rid, PAW_LF)[0]
        if abs(paw_now[0] - reach_pos[0]) < 0.003:
            break
search_origin = p.getLinkState(rid, PAW_LF)[0]
print(f"Reach done: paw x {clear_origin[0]:.3f} -> {search_origin[0]:.3f} "
      f"(z {search_origin[2]:.4f})")

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
        p.stepSimulation()
        time.sleep(1 / 60)
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

print("Holding final pose for 20s so you can look (window may need to be brought to front)...")
for _ in range(1200):
    p.stepSimulation()
    time.sleep(1 / 60)
env.close()
