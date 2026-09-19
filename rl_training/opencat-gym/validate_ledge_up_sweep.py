"""Validation sweep for probe_ledge_up.py's mechanism (climb-pose settle ->
reach forward+up -> search down onto the platform). Headless, no GIF -- just
the pass/fail + contact-normal data across a height x seed matrix.

    python validate_ledge_up_sweep.py trained/run20m_resid30_ppo
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
from leg_tint import setup_leg_tint
from climb_env import _BASE as CLIMB_POSE_SEQ

FL_SHOULDER, FL_KNEE = 0, 1
PAW_LF = 3
EDGE_X = 0.11
CLIMB_REACH_FRAME = 20

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("--heights-mm", default="10,15,20,25,30,35,40,45,50")
ap.add_argument("--seeds", default="7000,7001,7002,7003,7004")
ap.add_argument("--above-margin-m", type=float, default=0.030)
ap.add_argument("--search-steps", type=int, default=150)
args = ap.parse_args()


def tilt(rid):
    bo = p.getBasePositionAndOrientation(rid)[1]
    return np.rad2deg(max(abs(x) for x in p.getEulerFromQuaternion(bo)[0:2]))


def run(model, env, ledge_h, seed):
    _apply({"LEDGE_HEIGHT": ledge_h, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1})
    np.random.seed(seed)
    obs, _ = env.reset()
    rid = env.robot_id
    env.set_command(fwd=0.10, yaw=0.0)
    setup_leg_tint(env)
    for t in range(150):
        a, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, info = env.step(a)
        if term:
            return dict(result="fell_walking")
        if p.getLinkState(rid, PAW_LF)[0][0] > EDGE_X - 0.02:
            break
    else:
        return dict(result="never_reached_edge")

    env.set_command(0.0, 0.0)
    settled = False
    for s in range(80):
        a, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, info = env.step(a)
        if term:
            return dict(result="fell_settling")
        if s > 20 and tilt(rid) < 2.0:
            settled = True
            break
    if not settled:
        return dict(result="never_settled")

    js_now = p.getJointStates(rid, env.joint_id)
    hold_targets = np.array([j[0] for j in js_now])
    target_pose = CLIMB_POSE_SEQ[CLIMB_REACH_FRAME]
    for st in range(40):
        frac = (st + 1) / 40
        lt = hold_targets * (1 - frac) + target_pose * frac
        for _wait in range(5):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, lt, forces=np.ones(8) * 1.0)
            p.stepSimulation()
    hold_targets = target_pose.copy()
    for _ in range(20):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, hold_targets, forces=np.ones(8) * 1.0)
        p.stepSimulation()
    clear_origin = p.getLinkState(rid, PAW_LF)[0]
    tilt_climb_pose = tilt(rid)

    platform_top_z = ledge_h
    above_x = EDGE_X + 0.020
    above_z = platform_top_z + args.above_margin_m
    rt = hold_targets.copy()
    for st in range(100):
        frac = (st + 1) / 100
        rp = [clear_origin[0] + (above_x - clear_origin[0]) * frac, clear_origin[1],
              clear_origin[2] + (above_z - clear_origin[2]) * frac]
        ikr = p.calculateInverseKinematics(rid, PAW_LF, rp)
        rt = hold_targets.copy()
        rt[FL_SHOULDER] = ikr[FL_SHOULDER]
        rt[FL_KNEE] = ikr[FL_KNEE]
        for _wait in range(10):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, rt, forces=np.ones(8) * 0.5)
            p.stepSimulation()
            cur = p.getLinkState(rid, PAW_LF)[0]
            if abs(cur[0] - rp[0]) < 0.003 and abs(cur[2] - rp[2]) < 0.003:
                break
    hold_targets = rt
    clear_over = p.getLinkState(rid, PAW_LF)[0]
    tilt_after_reach = tilt(rid)

    search_depth = above_z - (platform_top_z - 0.015)
    far_z2 = clear_over[2] - search_depth
    kind, contact_z, contact_x_edge, normal = None, None, None, None
    for st in range(args.search_steps):
        frac = (st + 1) / args.search_steps
        tp = [clear_over[0], clear_over[1], clear_over[2] + (far_z2 - clear_over[2]) * frac]
        ik = p.calculateInverseKinematics(rid, PAW_LF, tp)
        targets = hold_targets.copy()
        targets[FL_SHOULDER] = ik[FL_SHOULDER]
        targets[FL_KNEE] = ik[FL_KNEE]
        for _wait in range(10):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, targets, forces=np.ones(8) * 0.5)
            p.stepSimulation()
            if abs(p.getLinkState(rid, PAW_LF)[0][2] - tp[2]) < 0.003:
                break
        cur = p.getLinkState(rid, PAW_LF)[0]
        cps = p.getContactPoints(bodyA=rid, linkIndexA=PAW_LF)
        if cps:
            cp = cps[0]
            nx, ny, nz = cp[7]
            kind = "TOP" if nz > 0.5 else ("FRONT" if abs(nx) > 0.5 else "OTHER")
            contact_z, contact_x_edge, normal = cur[2], round(1000 * (cur[0] - EDGE_X), 1), (round(nx, 2), round(ny, 2), round(nz, 2))
            break

    return dict(result="ok", kind=kind or "NONE", contact_z=round(contact_z, 4) if contact_z else None,
                x_edge_mm=contact_x_edge, normal=normal,
                tilt_climb_pose=round(tilt_climb_pose, 1), tilt_after_reach=round(tilt_after_reach, 1),
                final_tilt=round(tilt(rid), 1))


if __name__ == "__main__":
    from stable_baselines3 import PPO
    env = OpenCatGymEnv()
    model = PPO.load(args.checkpoint)

    heights = [float(x) / 1000 for x in args.heights_mm.split(",")]
    seeds = [int(x) for x in args.seeds.split(",")]

    n_ok, n_top, n_total = 0, 0, 0
    for h in heights:
        row = []
        for seed in seeds:
            r = run(model, env, h, seed)
            n_total += 1
            if r["result"] == "ok":
                n_ok += 1
                if r["kind"] == "TOP":
                    n_top += 1
            row.append(r)
        top_count = sum(1 for r in row if r.get("kind") == "TOP")
        print(f"ledge_up={h*1000:.0f}mm: {top_count}/{len(seeds)} TOP  " +
              " | ".join(f"{r.get('kind','ERR')}" + (f"@z{r['contact_z']:.3f}" if r.get("contact_z") else "")
                         for r in row))
    print(f"\nTotal: {n_top}/{n_total} genuine TOP-surface contacts")
    env.close()
