"""Climb via cmh's own scripted sequence as the PRIMARY motion, with a small
BOUNDED residual correction toward probe-verified footholds -- not a full
override (crawl_climb.py's approach, which discarded cmh's trajectory shape
entirely and looked sloppy/reactive rather than smooth). Same architecture
as the walk policy itself: joint_target = scripted_base + clipped_residual.

    python crawl_climb_residual.py trained/run20m_resid30_ppo out.gif --ledge-h 0.025
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
from climb_env import _BASE as CLIMB_POSE_SEQ, PAW as CLIMB_PAW_LINKS

FL_SHOULDER, FL_KNEE = 0, 1
FR_SHOULDER, FR_KNEE = 2, 3
RB_HIP, RB_KNEE = 4, 5
LB_HIP, LB_KNEE = 6, 7
PAW_LF, PAW_RF, PAW_RB, PAW_LB = 3, 6, 9, 12
EDGE_X = 0.11
CLIMB_REACH_FRAME = 20
FRAME_MS = 67
RESIDUAL_BOUND_DEG = 30   # matches climb_env.py's own RES_DEG scale

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("out", nargs="?", default=None)
ap.add_argument("--ledge-h", type=float, default=0.025)
ap.add_argument("--body-target-margin-m", type=float, default=0.10)
ap.add_argument("--settle-steps", type=int, default=80)
ap.add_argument("--above-margin-m", type=float, default=0.015)
ap.add_argument("--forward-margin-m", type=float, default=0.045)
ap.add_argument("--search-steps", type=int, default=150)
ap.add_argument("--seed", type=int, default=7000)
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
    frame = np.reshape(rgb, (args.h, args.w, 4))[:, :, :3].astype(np.uint8)
    frame[0, 0, 0] = len(frames) % 256
    frames.append(frame)


def sim_step():
    global _step_count
    p.stepSimulation()
    _step_count += 1
    if args.out and _step_count % CAPTURE_EVERY == 0:
        _snap()


def apply_residual(tgt, joint_pair, paw_link, anchor_pos):
    """Nudge tgt[joint_pair] toward the IK solution for anchor_pos, clipped
    to +/-RESIDUAL_BOUND_DEG of tgt's own (cmh) value -- a small correction,
    not a replacement."""
    if anchor_pos is None:
        return tgt
    ik = p.calculateInverseKinematics(rid, paw_link, anchor_pos)
    bound = np.deg2rad(RESIDUAL_BOUND_DEG)
    for j in joint_pair:
        delta = np.clip(ik[j] - tgt[j], -bound, bound)
        tgt[j] = tgt[j] + delta
    return tgt


def probe_leg_onto_platform(paw_link, shoulder_idx, knee_idx, hold_targets, anchors,
                             platform_top_z, forward_margin, above_margin,
                             lift_first=True, weight_shift=None):
    joints4 = {PAW_LF: (FL_SHOULDER, FL_KNEE), PAW_RF: (FR_SHOULDER, FR_KNEE),
               PAW_RB: (RB_HIP, RB_KNEE), PAW_LB: (LB_HIP, LB_KNEE)}

    def _with_anchors(tgt):
        for link, pos in anchors.items():
            sh, kn = joints4[link]
            ik = p.calculateInverseKinematics(rid, link, pos)
            tgt[sh] = ik[sh]
            tgt[kn] = ik[kn]
        return tgt

    if weight_shift is not None:
        shift_idx, shift_deg = weight_shift
        d = np.deg2rad(shift_deg)
        st_targets = hold_targets.copy()
        for idx in shift_idx:
            st_targets[idx] -= d
        for _ in range(30):
            tgt = _with_anchors(st_targets.copy())
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=np.ones(8) * 1.0)
            sim_step()
        hold_targets = st_targets

    paw_start = p.getLinkState(rid, paw_link)[0]
    if lift_first:
        lt = hold_targets.copy()
        for st in range(20):
            frac = (st + 1) / 20
            lt = hold_targets.copy()
            lt[knee_idx] = hold_targets[knee_idx] - np.deg2rad(40) * frac
            tgt = _with_anchors(lt.copy())
            for _wait in range(10):
                p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=np.ones(8) * 0.2)
                sim_step()
        hold_targets = lt
    paw_clear = p.getLinkState(rid, paw_link)[0]

    above_x = EDGE_X + forward_margin
    above_z = platform_top_z + above_margin
    rt = hold_targets.copy()
    for st in range(100):
        frac = (st + 1) / 100
        rp = [paw_clear[0] + (above_x - paw_clear[0]) * frac, paw_clear[1],
              paw_clear[2] + (above_z - paw_clear[2]) * frac]
        ikr = p.calculateInverseKinematics(rid, paw_link, rp)
        rt = hold_targets.copy()
        rt[shoulder_idx] = ikr[shoulder_idx]
        rt[knee_idx] = ikr[knee_idx]
        tgt = _with_anchors(rt.copy())
        for _wait in range(10):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=np.ones(8) * 0.5)
            sim_step()
            cur = p.getLinkState(rid, paw_link)[0]
            if abs(cur[0] - rp[0]) < 0.003 and abs(cur[2] - rp[2]) < 0.003:
                break
    hold_targets = rt
    paw_over = p.getLinkState(rid, paw_link)[0]

    search_depth = above_z - (platform_top_z - 0.015)
    far_z = paw_over[2] - search_depth
    for st in range(args.search_steps):
        frac = (st + 1) / args.search_steps
        tp = [paw_over[0], paw_over[1], paw_over[2] + (far_z - paw_over[2]) * frac]
        ik = p.calculateInverseKinematics(rid, paw_link, tp)
        targets = hold_targets.copy()
        targets[shoulder_idx] = ik[shoulder_idx]
        targets[knee_idx] = ik[knee_idx]
        tgt = _with_anchors(targets.copy())
        for _wait in range(10):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=np.ones(8) * 0.5)
            sim_step()
            if abs(p.getLinkState(rid, paw_link)[0][2] - tp[2]) < 0.003:
                break
        cps = p.getContactPoints(bodyA=rid, linkIndexA=paw_link)
        if cps:
            cp = cps[0]
            nx, ny, nz = cp[7]
            cur = p.getLinkState(rid, paw_link)[0]
            x_margin_mm = 1000 * (cur[0] - EDGE_X)
            solid = nz > 0.9 and x_margin_mm > 5
            print(f"  contact: normal=({nx:.2f},{ny:.2f},{nz:.2f}), x-margin={x_margin_mm:.1f}mm, "
                  f"tilt={tilt():.1f} -> {'SOLID' if solid else 'marginal'}")
            return targets, cur, solid
    print("  no contact found")
    return hold_targets, None, False


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
    bx_now = p.getBasePositionAndOrientation(rid)[0][0]
    if bx_now > EDGE_X - args.body_target_margin_m:
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

platform_top_z = args.ledge_h
print("Probing FL onto the platform (establishes the first verified anchor)...")
hold_targets, fl_anchor, fl_solid = probe_leg_onto_platform(
    PAW_LF, FL_SHOULDER, FL_KNEE, hold_targets, {}, platform_top_z,
    args.forward_margin_m, args.above_margin_m)
if fl_anchor is None:
    print("FL never found the platform -- aborting")
    raise SystemExit
print(f"FL secured: {'SOLID' if fl_solid else 'marginal'}")

# --- Main climb: replay cmh's OWN full sequence tick by tick (its real
# shape, including the 3x loop -- not skipped this time), with a small
# BOUNDED residual nudging FL toward its verified anchor. FR/RB/LB start
# with no anchor (residual = 0, pure cmh) and pick one up once probed
# mid-sequence, same as the walk policy's own base+residual architecture.
fr_anchor = None
rb_anchor = None
lb_anchor = None
ANCHOR_FORCE = 4.0
flipped = False
fr_probed = False
for t in range(CLIMB_REACH_FRAME + 1, len(CLIMB_POSE_SEQ)):
    tgt = CLIMB_POSE_SEQ[t].copy()
    tgt = apply_residual(tgt, (FL_SHOULDER, FL_KNEE), PAW_LF, fl_anchor)
    tgt = apply_residual(tgt, (FR_SHOULDER, FR_KNEE), PAW_RF, fr_anchor)
    tgt = apply_residual(tgt, (RB_HIP, RB_KNEE), PAW_RB, rb_anchor)
    tgt = apply_residual(tgt, (LB_HIP, LB_KNEE), PAW_LB, lb_anchor)
    f = np.ones(8) * 3.2
    for idx in (FL_SHOULDER, FL_KNEE, FR_SHOULDER, FR_KNEE, RB_HIP, RB_KNEE, LB_HIP, LB_KNEE):
        f[idx] = ANCHOR_FORCE
    for _ in range(4):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=f.tolist())
        sim_step()
    hold_targets = tgt
    tl = tilt()
    if t % 15 == 0:
        bx = p.getBasePositionAndOrientation(rid)[0][0]
        print(f"  tick {t}: body_x={bx:.4f}, tilt={tl:.1f}, "
              f"FL={'anchored' if fl_anchor is not None else '-'} "
              f"FR={'anchored' if fr_anchor is not None else '-'}")
    if tl > 68.8:
        print(f"FLIPPED at tick {t}")
        flipped = True
        break

    # once FL's own local loop has had a little room to settle, probe FR
    if not fr_probed and t >= CLIMB_REACH_FRAME + 15:
        print(f"  probing FR at tick {t} (FL residual-anchored)...")
        hold_targets, fr_new, fr_solid = probe_leg_onto_platform(
            PAW_RF, FR_SHOULDER, FR_KNEE, hold_targets, {PAW_LF: fl_anchor}, platform_top_z,
            args.forward_margin_m, args.above_margin_m, weight_shift=([RB_HIP, LB_HIP], 15))
        fr_probed = True
        if fr_new is not None:
            fr_anchor = fr_new
            print(f"  FR secured: {'SOLID' if fr_solid else 'marginal'}")
        else:
            print("  FR never found the platform -- continuing without an FR anchor")

    # once we're deep enough into the sequence that the rear legs are
    # closing in on the edge (per the FK trace done earlier), probe them
    if rb_anchor is None and t >= 150:
        rb_cur = p.getLinkState(rid, PAW_RB)[0]
        if rb_cur[0] > EDGE_X - 0.15:
            print(f"  probing RB at tick {t}...")
            hold_targets, rb_new, rb_solid = probe_leg_onto_platform(
                PAW_RB, RB_HIP, RB_KNEE, hold_targets, {PAW_LF: fl_anchor, PAW_RF: fr_anchor}, platform_top_z,
                max(args.forward_margin_m, (EDGE_X - rb_cur[0]) + 0.02), args.above_margin_m, lift_first=False)
            if rb_new is not None:
                rb_anchor = rb_new
                print(f"  RB secured: {'SOLID' if rb_solid else 'marginal'}")
    if lb_anchor is None and rb_anchor is not None and t >= 150:
        lb_cur = p.getLinkState(rid, PAW_LB)[0]
        if lb_cur[0] > EDGE_X - 0.15:
            print(f"  probing LB at tick {t}...")
            hold_targets, lb_new, lb_solid = probe_leg_onto_platform(
                PAW_LB, LB_HIP, LB_KNEE, hold_targets,
                {PAW_LF: fl_anchor, PAW_RF: fr_anchor, PAW_RB: rb_anchor}, platform_top_z,
                max(args.forward_margin_m, (EDGE_X - lb_cur[0]) + 0.02), args.above_margin_m, lift_first=False)
            if lb_new is not None:
                lb_anchor = lb_new
                print(f"  LB secured: {'SOLID' if lb_solid else 'marginal'}")

if not flipped:
    for _ in range(40):
        tgt = hold_targets.copy()
        tgt = apply_residual(tgt, (FL_SHOULDER, FL_KNEE), PAW_LF, fl_anchor)
        tgt = apply_residual(tgt, (FR_SHOULDER, FR_KNEE), PAW_RF, fr_anchor)
        tgt = apply_residual(tgt, (RB_HIP, RB_KNEE), PAW_RB, rb_anchor)
        tgt = apply_residual(tgt, (LB_HIP, LB_KNEE), PAW_LB, lb_anchor)
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=np.ones(8) * 4.0)
        sim_step()
    paws = [p.getLinkState(rid, j)[0] for j in CLIMB_PAW_LINKS]
    labels = ["FL", "FR", "RB", "LB"]
    on_top_each = {lbl: (pz > platform_top_z - 0.02 and px > EDGE_X - 0.02) for lbl, (px, py, pz) in zip(labels, paws)}
    on_top = sum(on_top_each.values())
    bx = p.getBasePositionAndOrientation(rid)[0][0]
    print(f"FINAL: {on_top}/4 paws on-top {on_top_each}, body_x={bx:.4f}, tilt={tilt():.1f}")

if args.out and frames:
    for _ in range(30):
        _snap()
env.close()

if args.out and frames:
    from PIL import Image
    imgs = [Image.fromarray(f) for f in frames]
    imgs[0].save(args.out, save_all=True, append_images=imgs[1:], duration=FRAME_MS, loop=0, optimize=False)
    print(f"{args.out}: {len(imgs)} frames, ~{len(imgs)*FRAME_MS/1000:.1f}s")
