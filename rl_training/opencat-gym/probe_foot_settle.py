"""Foot-probing v2: deliberate commanded stop-and-settle, instead of an
opportunistic freeze of whatever pose the walk's natural gait cycle happens
to be in (probe_foot_test.py / probe_foot_gif.py's approach, closed
negative -- see docs/rl/foot-probing-log.md).

Walks normally until the front-left paw is within STOP_MARGIN_M of the
ledge edge, then commands a full stop (fwd=0) and lets the TRAINED POLICY
itself bring the robot to a settled stance (matches real deployment -- a
real stop command goes through the same policy) instead of freezing
mid-stride joint angles. Only once settled (low, stable tilt) does the
weight-shift -> lift -> reach -> search sequence begin.

    python probe_foot_settle.py trained/run20m_resid30_ppo --ledge-h 0.008
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

FL_SHOULDER, FL_KNEE = 0, 1
FR_SHOULDER, RB_HIP, LB_HIP = 2, 4, 6
PAW_LF, PAW_RF, PAW_RB, PAW_LB = 3, 6, 9, 12
EDGE_X = 0.11

def _build_argparser():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--ledge-h", type=float, default=0.008)
    ap.add_argument("--stop-margin-m", type=float, default=0.05,
                     help="command stop once the FL paw is within this much of the edge")
    ap.add_argument("--settle-steps", type=int, default=80)
    ap.add_argument("--reach-past-edge-m", type=float, default=0.030)
    ap.add_argument("--seed", type=int, default=7000)
    ap.add_argument("--shift-deg", type=float, default=15.0)
    ap.add_argument("--knee-flex-deg", type=float, default=40.0)
    ap.add_argument("--search-depth-m", type=float, default=0.10)
    ap.add_argument("--search-steps", type=int, default=80)
    ap.add_argument("--verbose", action="store_true")
    return ap


class _Defaults:
    """Module-import-safe stand-in for CLI args (only parsed in __main__)."""
    stop_margin_m = 0.02
    settle_steps = 80
    reach_past_edge_m = 0.030
    shift_deg = 15.0
    knee_flex_deg = 40.0
    search_depth_m = 0.10
    search_steps = 80


args = _Defaults()


def tilt(rid):
    bo = p.getBasePositionAndOrientation(rid)[1]
    return np.rad2deg(max(abs(x) for x in p.getEulerFromQuaternion(bo)[0:2]))


def full_com(rid):
    mass = p.getDynamicsInfo(rid, -1)[0]
    pos = p.getBasePositionAndOrientation(rid)[0]
    total_mass = mass
    weighted = np.array(pos) * mass
    for j in range(p.getNumJoints(rid)):
        m = p.getDynamicsInfo(rid, j)[0]
        wp = p.getLinkState(rid, j, computeForwardKinematics=True)[0]
        total_mass += m
        weighted += np.array(wp) * m
    return weighted / total_mass


def point_in_triangle(pt, a, b, c):
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = sign(pt, a, b), sign(pt, b, c), sign(pt, c, a)
    has_neg, has_pos = (d1 < 0 or d2 < 0 or d3 < 0), (d1 > 0 or d2 > 0 or d3 > 0)
    return not (has_neg and has_pos)


def run_episode(model, env, ledge_h, seed, verbose=False):
    if ledge_h > 0:
        _apply({"LEDGE_HEIGHT": ledge_h, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1})
    else:
        _apply({})
    np.random.seed(seed)
    obs, _ = env.reset()
    rid = env.robot_id
    env.set_command(fwd=0.10, yaw=0.0)
    setup_leg_tint(env)

    # --- Phase 1: walk until close to the edge, then command a stop ---
    for t in range(150):
        a, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, info = env.step(a)
        if term:
            return dict(result="fell_walking")
        paw_x = p.getLinkState(rid, PAW_LF)[0][0]
        if paw_x > EDGE_X - args.stop_margin_m:
            break
    else:
        return dict(result="never_reached_stop_point")

    env.set_command(fwd=0.0, yaw=0.0)

    # --- Phase 2: let the trained policy settle to a stop ---
    settled = False
    for s in range(args.settle_steps):
        a, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, info = env.step(a)
        if term:
            return dict(result="fell_settling")
        tl = tilt(rid)
        if verbose and s % 10 == 0:
            paw_x = p.getLinkState(rid, PAW_LF)[0][0]
            print(f"  settle step {s}: tilt={tl:.1f}, paw_x-edge={1000*(paw_x-EDGE_X):.1f}mm")
        if s > 20 and tl < 2.0:
            settled = True
            break
    if not settled:
        return dict(result="never_settled", final_tilt=round(tilt(rid), 1))

    paw_at_settle = p.getLinkState(rid, PAW_LF)[0]
    tilt_at_settle = tilt(rid)

    # --- Phase 3: weight-shift, check COM, then lift ---
    js_now = p.getJointStates(rid, env.joint_id)
    hold_targets = np.array([j[0] for j in js_now])

    fr = p.getLinkState(rid, PAW_RF)[0]
    rb = p.getLinkState(rid, PAW_RB)[0]
    lb = p.getLinkState(rid, PAW_LB)[0]
    com0 = full_com(rid)
    inside0 = point_in_triangle((com0[0], com0[1]), (fr[0], fr[1]), (rb[0], rb[1]), (lb[0], lb[1]))

    d = np.deg2rad(args.shift_deg)
    shift_targets = hold_targets.copy()
    shift_targets[FR_SHOULDER] -= d
    shift_targets[RB_HIP] -= d
    shift_targets[LB_HIP] -= d
    for _ in range(30):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, shift_targets, forces=np.ones(8) * 1.0)
        p.stepSimulation()
    hold_targets = shift_targets
    tilt_after_shift = tilt(rid)

    # Confirm the three stance feet are actually planted (real ground contact,
    # not just assumed from settling) before committing to lift the fourth --
    # give it a few extra settle steps if one isn't grounded yet, since a leg
    # that's merely hovering close to the floor won't show a contact point.
    stance_paws = (PAW_RF, PAW_RB, PAW_LB)
    for _extra in range(20):
        grounded = [bool(p.getContactPoints(bodyA=rid, linkIndexA=pw)) for pw in stance_paws]
        if all(grounded):
            break
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, shift_targets, forces=np.ones(8) * 1.0)
        p.stepSimulation()
    else:
        grounded = [bool(p.getContactPoints(bodyA=rid, linkIndexA=pw)) for pw in stance_paws]
    if not all(grounded):
        return dict(result="stance_not_grounded", grounded=dict(zip(("FR", "RB", "LB"), grounded)),
                    tilt_after_shift=round(tilt_after_shift, 1))

    # Direct knee-flexion lift, NOT an IK z-target: the settled standing pose
    # has the knee nearly straight (~0-3deg), a poorly-conditioned start for
    # an IK vertical-lift solve (confirmed directly: IK barely moved the paw,
    # ~1.7mm of 20mm intended, despite joints tracking their IK targets fine
    # -- a mechanical-advantage problem, not a tracking one). Bending the
    # knee directly is far more effective from this pose: -40deg gave ~25mm
    # of clean lift at <2deg tilt in isolation testing.
    paw_start = p.getLinkState(rid, PAW_LF)[0]
    knee_flex_rad = np.deg2rad(args.knee_flex_deg)
    lt = hold_targets.copy()
    for st in range(20):
        frac = (st + 1) / 20
        lt = hold_targets.copy()
        lt[FL_KNEE] = hold_targets[FL_KNEE] - knee_flex_rad * frac
        for _wait in range(10):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, lt, forces=np.ones(8) * 0.2)
            p.stepSimulation()
    hold_targets = lt
    clear_origin = p.getLinkState(rid, PAW_LF)[0]
    lift_mm = round((clear_origin[2] - paw_start[2]) * 1000, 1)

    # --- Phase 4: reach past the edge (aim far, stop once desired reached) ---
    far_x = clear_origin[0] + 0.10
    desired_x = EDGE_X + args.reach_past_edge_m
    for st in range(100):
        frac = (st + 1) / 100
        rp = [clear_origin[0] + (far_x - clear_origin[0]) * frac, clear_origin[1], clear_origin[2]]
        ikr = p.calculateInverseKinematics(rid, PAW_LF, rp)
        rt = hold_targets.copy()
        rt[FL_SHOULDER] = ikr[FL_SHOULDER]
        rt[FL_KNEE] = ikr[FL_KNEE]
        for _wait in range(10):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, rt, forces=np.ones(8) * 0.2)
            p.stepSimulation()
            if abs(p.getLinkState(rid, PAW_LF)[0][0] - rp[0]) < 0.003:
                break
        if p.getLinkState(rid, PAW_LF)[0][0] >= desired_x:
            break
    search_origin = p.getLinkState(rid, PAW_LF)[0]
    reach_mm = round((search_origin[0] - EDGE_X) * 1000, 1)
    tilt_after_reach = tilt(rid)

    # --- Phase 5: search down -- aim past the max search depth on purpose and
    # step patiently (matches the lift/reach fix: IK from a well-conditioned
    # pose needs room to converge gradually, not one coarse per-increment
    # jump). Stop the instant real contact is confirmed (ground truth, not
    # just tracking error) or progress plateaus with no contact (genuinely
    # out of reach -- the correct "no floor found" signal for a real cliff).
    far_z = search_origin[2] - args.search_depth_m
    prev_z = None
    contact_at = None
    confirmed = False
    for st in range(args.search_steps):
        frac = (st + 1) / args.search_steps
        tp = [search_origin[0], search_origin[1], search_origin[2] + (far_z - search_origin[2]) * frac]
        ik = p.calculateInverseKinematics(rid, PAW_LF, tp)
        targets = hold_targets.copy()
        targets[FL_SHOULDER] = ik[FL_SHOULDER]
        targets[FL_KNEE] = ik[FL_KNEE]
        for _wait in range(10):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, targets, forces=np.ones(8) * 0.2)
            p.stepSimulation()
            if abs(p.getLinkState(rid, PAW_LF)[0][2] - tp[2]) < 0.003:
                break
        cur_z = p.getLinkState(rid, PAW_LF)[0][2]
        confirmed = bool(p.getContactPoints(bodyA=rid, linkIndexA=PAW_LF))
        if confirmed:
            contact_at = round((search_origin[2] - cur_z) * 1000, 1)
            break
        if prev_z is not None and abs(cur_z - prev_z) < 0.0003 and st > 15:
            contact_at = round((search_origin[2] - cur_z) * 1000, 1)  # plateaued, no real contact
            break
        prev_z = cur_z

    return dict(result="ok", tilt_at_settle=round(tilt_at_settle, 1), com_inside_before_shift=inside0,
                tilt_after_shift=round(tilt_after_shift, 1), lift_mm=lift_mm,
                reach_mm=reach_mm, tilt_after_reach=round(tilt_after_reach, 1),
                contact_at_mm=contact_at, confirmed=confirmed, final_tilt=round(tilt(rid), 1))


if __name__ == "__main__":
    args = _build_argparser().parse_args()
    from stable_baselines3 import PPO
    env = OpenCatGymEnv()
    model = PPO.load(args.checkpoint)
    r = run_episode(model, env, args.ledge_h, args.seed, verbose=args.verbose)
    print(r)
    env.close()
