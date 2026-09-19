"""Test: does starting the real `cmh` climb sequence from a PROPERLY SEATED
front-left foot (found via the validated probe_ledge_up.py mechanism) let the
climb actually complete, where Phase F's climb_env.py runs never confirmed
solid initial footing (b3-logged as "front paw can't reach forward and up",
vision-in-gait.md Phase F)?

Sequence: walk -> stop -> settle -> climb-pose (cmh frame 20) -> probe
forward+up -> search down onto the platform (same as probe_ledge_up.py) ->
if solid contact found, blend into cmh frame 21 and play out the REST of the
real keyframe sequence (all 8 joints, matches climb_env.py's scripted base)
to see whether the whole-body climb actually completes.

    python probe_then_climb.py trained/run20m_resid30_ppo out.gif --ledge-h 0.025
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
from climb_env import _BASE as CLIMB_POSE_SEQ, PAW as CLIMB_PAW_LINKS, BOUND as CLIMB_BOUND, RES_DEG

FL_SHOULDER, FL_KNEE = 0, 1
PAW_LF = 3
EDGE_X = 0.11
CLIMB_REACH_FRAME = 20
JOINT_FORCE = 3.2   # matches climb_env.py's scripted-base force
FRAME_MS = 67
ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("out", nargs="?", default=None)
ap.add_argument("--ledge-h", type=float, default=0.025)
ap.add_argument("--stop-margin-m", type=float, default=0.02)
ap.add_argument("--settle-steps", type=int, default=80)
ap.add_argument("--above-margin-m", type=float, default=0.015)
ap.add_argument("--forward-margin-m", type=float, default=0.045)
ap.add_argument("--search-steps", type=int, default=150)
ap.add_argument("--seed", type=int, default=7000)
ap.add_argument("--climb-resume-tick", type=int, default=165,
                 help="which tick of the real cmh sequence to resume into after the probe finds "
                      "footing -- NOT the reach frame (20): the sequence loops through a 'reach and "
                      "adjust' phase 3x (ticks 6-165, 92% of the whole sequence) before the actual "
                      "'haul the body up and over' commit motion, which is only ticks ~165-171. Our "
                      "probe already accomplishes what the loop exists to do, so resume just before "
                      "the real commit, not partway into redundant loop iterations.")
ap.add_argument("--residual-checkpoint", default=None,
                 help="trained climb_env.py PPO checkpoint (e.g. trained/climb_r5) -- if given, "
                      "uses its residual on top of the scripted base instead of pure scripted playback, "
                      "matching how climb_env.py's ClimbEnv was actually designed to run")
ap.add_argument("--speed", type=float, default=3.0)
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
            cameraTargetPosition=[pos[0], pos[1], 0.05], distance=0.5,
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
        print("fell before reaching the ledge")
        raise SystemExit
    if p.getLinkState(rid, PAW_LF)[0][0] > EDGE_X - args.stop_margin_m:
        break

print("Commanding a stop, letting the policy settle...")
env.set_command(0.0, 0.0)
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
        break

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

print("Reaching forward and up to clear the edge...")
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

print("Searching down onto the platform...")
search_depth = above_z - (platform_top_z - 0.015)
far_z2 = clear_over[2] - search_depth
solid = False
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
        solid = nz > 0.9 and x_margin_mm > 5
        print(f"contact: normal=({nx:.2f},{ny:.2f},{nz:.2f}), x-margin={x_margin_mm:.1f}mm -> "
              f"{'SOLID' if solid else 'marginal'}")
        hold_targets = targets
        break
else:
    print("no contact found -- can't test the climb continuation, aborting")
    if args.out:
        for _ in range(15):
            _snap()
    raise SystemExit

if not solid:
    print("footing wasn't solid -- continuing anyway to see what the climb does with marginal footing")

fl_anchor = cur   # the verified world position where FL found real contact -- hold this fixed
                  # through the crawl-advance phase below, instead of trusting cmh's own
                  # unverified FL trajectory for that phase.

print("Foot is seated -- blending into the crawl-advance phase...")
crawl_start_tick = CLIMB_REACH_FRAME + 1
blend_target = CLIMB_POSE_SEQ[crawl_start_tick].copy()
ik0 = p.calculateInverseKinematics(rid, PAW_LF, fl_anchor)
blend_target[FL_SHOULDER] = ik0[FL_SHOULDER]
blend_target[FL_KNEE] = ik0[FL_KNEE]
for st in range(15):
    frac = (st + 1) / 15
    lt = hold_targets * (1 - frac) + blend_target * frac
    for _wait in range(5):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, lt, forces=np.ones(8) * JOINT_FORCE)
        sim_step()

print("Settling before starting the crawl-advance...")
for s in range(60):
    p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, blend_target, forces=np.ones(8) * JOINT_FORCE)
    sim_step()
    bo = p.getBaseVelocity(rid)
    if s > 15 and np.linalg.norm(bo[0]) < 0.02 and np.linalg.norm(bo[1]) < 0.15:
        print(f"  settled after {s} steps, tilt={tilt():.1f}")
        break
else:
    print(f"  never fully settled within budget, tilt={tilt():.1f} -- continuing anyway")

# --- Crawl-advance: replay the real cmh sequence's OTHER 3 legs (the actual
# designed body-advancing motion) while FL stays IK-locked to the verified
# anchor instead of following cmh's own -- unverified -- FL trajectory for
# this phase. This is the fix for the "body never got close to the ledge"
# finding: skipping straight to the commit motion (ticks ~166-171) skipped
# the part of cmh that walks the body forward, so there was nothing for the
# final haul-up motion to act on.
commit_start_tick = args.climb_resume_tick
print(f"Crawl-advancing (ticks {crawl_start_tick}->{commit_start_tick}, FL anchored at verified contact)...")
flipped = False
for t in range(crawl_start_tick, commit_start_tick):
    tgt = CLIMB_POSE_SEQ[t].copy()
    ik = p.calculateInverseKinematics(rid, PAW_LF, fl_anchor)
    tgt[FL_SHOULDER] = ik[FL_SHOULDER]
    tgt[FL_KNEE] = ik[FL_KNEE]
    for _ in range(4):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=np.ones(8) * JOINT_FORCE)
        sim_step()
    bo = p.getBasePositionAndOrientation(rid)[1]
    rp = p.getEulerFromQuaternion(bo)
    if max(abs(rp[0]), abs(rp[1])) > 1.2:
        print(f"FLIPPED during crawl-advance at tick {t} -- aborting")
        flipped = True
        break
if not flipped:
    bx = p.getBasePositionAndOrientation(rid)[0][0]
    print(f"  crawl-advance done: body x={bx:.4f} (ledge front at x={EDGE_X:.3f}), tilt={tilt():.1f}")

    print("Settling before the final commit...")
    for s in range(60):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, CLIMB_POSE_SEQ[commit_start_tick - 1],
                                     forces=np.ones(8) * JOINT_FORCE)
        sim_step()
        bo = p.getBaseVelocity(rid)
        if s > 15 and np.linalg.norm(bo[0]) < 0.02 and np.linalg.norm(bo[1]) < 0.15:
            print(f"  settled after {s} steps, tilt={tilt():.1f}")
            break

next_tick = commit_start_tick

residual_model = None
last_action = np.zeros(8, np.float32)
if args.residual_checkpoint:
    print(f"Loading trained climb residual: {args.residual_checkpoint}")
    from stable_baselines3 import PPO as _PPO
    residual_model = _PPO.load(args.residual_checkpoint)


def _proj_gravity(quat):
    x, y, z, w = quat
    return np.array([-2.0 * (x * z - w * y), -2.0 * (y * z + w * x), -(1.0 - 2.0 * (x * x + y * y))])


PROFILE_X = np.linspace(0.03, 0.18, 6)


def _height_profile(bx):
    out = []
    for dx in PROFILE_X:
        hit = p.rayTest([bx + dx, 0.0, 0.30], [bx + dx, 0.0, -0.20])[0]
        z = hit[3][2] if hit[0] >= 0 else 0.0
        out.append(np.clip(z / 0.08, 0.0, 1.5))
    return np.array(out)


def _climb_obs(action, t):
    (bx, by, bz), quat = p.getBasePositionAndOrientation(rid)
    _, ang = p.getBaseVelocity(rid)
    js = [p.getJointState(rid, j)[0] for j in env.joint_id]
    prog = np.clip((bx - EDGE_X) / 0.20, -1.0, 1.5)
    base_phase = min(1.0, t / len(CLIMB_POSE_SEQ))
    return np.concatenate([
        quat, np.clip(np.array(ang) * 0.1, -1, 1), np.clip(_proj_gravity(quat), -1, 1),
        np.array(js) / CLIMB_BOUND, action, _height_profile(bx), [prog, base_phase],
    ]).astype(np.float32)


if not flipped:
    for t in range(next_tick, len(CLIMB_POSE_SEQ)):
        if residual_model is not None:
            obs_climb = _climb_obs(last_action, t)
            action, _ = residual_model.predict(obs_climb, deterministic=True)
            last_action = action
            tgt = np.clip(CLIMB_POSE_SEQ[t] + action * np.deg2rad(RES_DEG), -CLIMB_BOUND, CLIMB_BOUND)
        else:
            tgt = CLIMB_POSE_SEQ[t]
        for _ in range(4):   # FRAME_SKIP, matches climb_env.py's 240Hz sim / 4 = 60Hz control
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=np.ones(8) * JOINT_FORCE)
            sim_step()
        bo = p.getBasePositionAndOrientation(rid)[1]
        rp = p.getEulerFromQuaternion(bo)
        if max(abs(rp[0]), abs(rp[1])) > 1.2:
            print(f"FLIPPED at tick {t}/{len(CLIMB_POSE_SEQ)} -- climb failed (body rolled/pitched over)")
            flipped = True
            break
    if not flipped:
        # hold the final pose a moment so the result is visible
        for _ in range(60):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, CLIMB_POSE_SEQ[-1], forces=np.ones(8) * JOINT_FORCE)
            sim_step()
        paws = [p.getLinkState(rid, j)[0] for j in CLIMB_PAW_LINKS]
        on_top = sum(1 for (px, py, pz) in paws if pz > platform_top_z - 0.02 and px > EDGE_X - 0.02)
        bx = p.getBasePositionAndOrientation(rid)[0][0]
        print(f"Sequence complete. {on_top}/4 paws reading as on-top-of-ledge height, body x={bx:.3f}, "
              f"final tilt={tilt():.1f}")

if args.out and frames:
    for _ in range(15):
        _snap()
env.close()

if args.out and frames:
    from PIL import Image
    imgs = [Image.fromarray(f) for f in frames]
    durations = [FRAME_MS] * (len(imgs) - 15) + [150] * 15
    imgs[0].save(args.out, save_all=True, append_images=imgs[1:], duration=durations, loop=0, optimize=True)
    print(f"{args.out}: {len(imgs)} frames")
