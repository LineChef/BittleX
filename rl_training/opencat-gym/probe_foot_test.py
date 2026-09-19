"""Proprioceptive foot-probing prototype (behaviour-ideas B13 addendum,
2026-09-18): can a deliberate, slow leg-extension motion detect a step-down's
true depth using only joint-tracking-error feedback (commanded vs actual
angle under position control) -- the same signal real feedback servos could
eventually provide, here read instantly/perfectly from PyBullet -- before the
robot commits body weight onto that foot?

Pure sensing-mechanism test, not an integrated behavior yet: walks the
trained policy up to a step-down ledge, freezes it, then manually sweeps one
front leg's knee joint through a slow downward search while every other
joint holds its last commanded angle. Records how far the search had to
extend before tracking error revealed contact, across several ledge depths.
If the search depth needed tracks the true drop depth, the sensing mechanism
works in principle -- if the robot topples just holding a 3-leg stance during
the probe, that's an important finding about whether this is mechanically
viable for Bittle's morphology at all, not just a failed measurement.

    python probe_foot_test.py trained/run20m_resid30_ppo
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
from stable_baselines3 import PPO

# env.joint_id = [1, 2, 4, 5, 7, 8, 10, 11] (confirmed directly, not assumed):
# pybullet joint indices, order [shoulder_left, elbow_left, shoulder_right,
# elbow_right, hip_right, knee_right, hip_left, knee_left] -- so index 0/1 in
# THAT array are the front-left shoulder+knee. Real paw link indices (matches
# opencat_gym_env.py's own paw_contact code, order [LF, RF, RB, LB]) are
# SEPARATE body-wide link indices (3, 6, 9, 12), not env.joint_id entries --
# first bug in this prototype: checked contacts on env.joint_id[1]'s own link
# and always got zero, even mid-collision, since the real foot tip is a fixed
# child link (3) one segment further out.
FL_SHOULDER, FL_KNEE = 0, 1   # indices into env.joint_id
PAW_LF = 3                    # body-wide link index, the actual foot tip

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("--heights", default="0,0.020,0.027,0.030,0.045")
ap.add_argument("--episodes", type=int, default=6)
ap.add_argument("--search-depth-m", type=float, default=0.06,
                 help="max extra downward reach to search, metres (world-space, via IK)")
ap.add_argument("--search-steps", type=int, default=30,
                 help="sub-steps over which the search sweeps --search-depth-m")
ap.add_argument("--converge-tol-deg", type=float, default=2.0,
                 help="per-joint tracking-error threshold (deg) that counts as 'converged, no contact'")
args = ap.parse_args()
HEIGHTS = [float(x) for x in args.heights.split(",")]


def probe_episode(model, env, ledge_h, seed):
    np.random.seed(seed)
    obs, _ = env.reset()
    env.set_command(fwd=0.10, yaw=0.0)
    rid = env.robot_id
    last_cmd = None
    toppled_before_probe = False
    EDGE_X = 0.11  # opencat_gym_env.py's own ledge-edge x position
    for t in range(150):
        a, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, info = env.step(a)
        last_cmd = a
        if term:
            toppled_before_probe = True
            break
        # Trigger on the PROBING PAW's own x crossing the real edge, not the
        # body's -- the paw extends well ahead of the body, so "body barely
        # past start" left the paw still over the upper platform every time
        # (confirmed directly: every ledge height found the same 4mm contact
        # depth, i.e. always landing on the near surface, never the drop).
        # Also require the FL paw to already be unloaded (mid-swing, not
        # touching ground) before freezing -- lifting a leg that's still
        # bearing real body weight, while the other 3 stay rigidly frozen
        # rather than actively rebalancing, can ask for something no static
        # 3-leg stance can actually support. Confirmed directly: holding all
        # 4 legs at their exact current pose is rock-stable (sub-1deg drift
        # over 20 steps); it's specifically lifting FL from a *loaded* stance
        # that failed. Triggering only once the normal gait has already
        # unloaded that leg on its own sidesteps the whole problem.
        paw_x = p.getLinkState(rid, PAW_LF)[0][0]
        fl_loaded = bool(p.getContactPoints(bodyA=rid, linkIndexA=PAW_LF))
        if paw_x > EDGE_X + 0.01 and not fl_loaded:
            break
    if toppled_before_probe:
        return {"toppled_before_probe": True}

    # Freeze: hold everything except FL_KNEE at its CURRENT ACTUAL position
    # (read back, not the last commanded target) -- "stay exactly where you
    # physically are" is far more stable than "keep moving toward wherever
    # you were being commanded", which can be well off if caught mid-swing.
    # This was the actual bug in the first pass: holding stale commanded
    # targets let the body visibly "settle" for several sub-steps, and that
    # settling dynamics coupled into the probed joint's own tracking error,
    # masking the real ledge-contact signal.
    js_now = p.getJointStates(env.robot_id, env.joint_id)
    hold_targets = np.array([j[0] for j in js_now])
    paw_start = p.getLinkState(env.robot_id, PAW_LF)[0]

    # Settle: hold this exact pose for a few steps before measuring anything,
    # so any residual transient from the freeze itself clears first.
    for _ in range(10):
        p.setJointMotorControlArray(env.robot_id, env.joint_id, p.POSITION_CONTROL,
                                     hold_targets, forces=np.ones(8) * 0.2)
        p.stepSimulation()
        bp, bo = p.getBasePositionAndOrientation(env.robot_id)
        rp = p.getEulerFromQuaternion(bo)
        if max(abs(rp[0]), abs(rp[1])) > 1.0:
            return {"toppled_before_probe": False, "toppled_during_settle": True,
                    "toppled_during_probe": False, "contact_at_mm": None, "max_tracking_err_deg": None}

    # Lift first: the paw was already resting at ground level from the
    # approach walk, so searching "down" from there is asking for something
    # already physically impossible from step one -- a real probe happens
    # during a swing, starting from a cleared foot, not a grounded one.
    # Clear to PAW_Z_TARGET (0.020, the same swing-clearance height the
    # trained gait already targets) directly above the start x/y first.
    #
    # A single big IK jump here (confirmed directly, twice) is unreliable:
    # one-shot IK solves as if the whole body could move to help reach the
    # target, so applying only the FL-leg slice of that solution while
    # holding the other 6 joints fixed left it unable to actually get there
    # (<1mm of real lift in 20 steps despite a 20mm target, free space, no
    # contact). Anchoring that single IK call fixed the lift in isolation
    # but made the *search* loop's small increments noisier when applied
    # there too. Resolving both by using the same incremental, unanchored,
    # per-step approach that already works well for the search -- many small
    # IK-recomputed steps instead of one big one, which stays local to the
    # FL chain on its own without needing the anchoring hack at all.
    LIFT_M = 0.020
    lift_steps = 15
    for s in range(lift_steps):
        frac = (s + 1) / lift_steps
        clear_pos = [paw_start[0], paw_start[1], paw_start[2] + LIFT_M * frac]
        ik0 = p.calculateInverseKinematics(env.robot_id, PAW_LF, clear_pos)
        lift_targets = hold_targets.copy()
        lift_targets[FL_SHOULDER] = ik0[FL_SHOULDER]
        lift_targets[FL_KNEE] = ik0[FL_KNEE]
        for _wait in range(10):
            p.setJointMotorControlArray(env.robot_id, env.joint_id, p.POSITION_CONTROL,
                                         lift_targets, forces=np.ones(8) * 0.2)
            p.stepSimulation()
            paw_now = p.getLinkState(env.robot_id, PAW_LF)[0]
            if abs(paw_now[2] - clear_pos[2]) < 0.002:
                break
    search_origin = p.getLinkState(env.robot_id, PAW_LF)[0]

    # Quasi-static search, coordinated 2-joint (shoulder+knee) via IK: for
    # each increment, ask "what shoulder+knee angles put the paw at
    # (x0, y0, z0 - depth)" from the CLEARED position, command those
    # (holding the other 6 joints fixed), and WAIT for the paw's own WORLD
    # POSITION (not raw joint angle -- IK can find joint solutions that look
    # locally consistent without the paw actually reaching the Cartesian
    # target, confirmed directly: joint tracking error stayed small the
    # whole sweep while the paw physically never moved, already pinned at
    # the floor) to converge close to the target. Position error is still a
    # hardware-realizable signal -- forward kinematics from joint feedback,
    # not a new sensor -- just one computation step past the raw angles.
    n_increments = args.search_steps
    pos_tol = 0.003  # 3mm
    max_wait = 10
    contact_at = None
    toppled_during_probe = False
    max_err = 0.0
    contact_paw_confirmed = None
    for s in range(n_increments):
        frac = (s + 1) / n_increments
        target_pos = [search_origin[0], search_origin[1],
                      search_origin[2] - args.search_depth_m * frac]
        # NOT anchored with currentPositions here, unlike the lift above --
        # confirmed directly: anchoring each small search increment on the
        # previous pose let IK settle for "good enough" local solutions that
        # didn't actually require reaching the new z target, regressing the
        # accurate 27/30mm results back to the same shallow false-positive
        # every height showed before. Anchoring helps a big single jump
        # (free space, far from any local optimum); it hurts small steps
        # searching for a genuine boundary.
        ik = p.calculateInverseKinematics(env.robot_id, PAW_LF, target_pos)
        targets = hold_targets.copy()
        targets[FL_SHOULDER] = ik[FL_SHOULDER]
        targets[FL_KNEE] = ik[FL_KNEE]
        converged = False
        for _wait in range(max_wait):
            p.setJointMotorControlArray(env.robot_id, env.joint_id, p.POSITION_CONTROL,
                                         targets, forces=np.ones(8) * 0.2)
            p.stepSimulation()
            paw_now = p.getLinkState(env.robot_id, PAW_LF)[0]
            pos_err = abs(paw_now[2] - target_pos[2])
            if pos_err < pos_tol:
                converged = True
                break
        max_err = max(max_err, pos_err)
        bp, bo = p.getBasePositionAndOrientation(env.robot_id)
        rp = p.getEulerFromQuaternion(bo)
        if max(abs(rp[0]), abs(rp[1])) > 1.0:  # ~57deg, treat as fallen
            toppled_during_probe = True
            break
        if not converged and contact_at is None:
            contact_at = args.search_depth_m * frac * 1000  # mm of extra downward reach searched before resistance
            contact_paw_confirmed = bool(p.getContactPoints(bodyA=env.robot_id, linkIndexA=PAW_LF))
            break  # found it -- real deployment would stop and decide here too

    return {
        "toppled_before_probe": False,
        "toppled_during_probe": toppled_during_probe,
        "contact_at_mm": contact_at,
        "max_tracking_err_deg": max_err,
        "contact_paw_confirmed": contact_paw_confirmed,
    }


if __name__ == "__main__":
    m = PPO.load(args.checkpoint)
    print(f"{'ledge_h_mm':>10} {'topple_before':>14} {'topple_during':>14} {'contact_at_mm':>14} {'n_no_contact':>13} {'paw_confirmed':>14}")
    for h in HEIGHTS:
        if h > 0:
            _apply({"LEDGE_HEIGHT": h, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1})
        else:
            _apply({})
        env = OpenCatGymEnv()
        results = [probe_episode(m, env, h, 7000 + s) for s in range(args.episodes)]
        env.close()
        tb = sum(r.get("toppled_before_probe", False) for r in results)
        td = sum(r.get("toppled_during_probe", False) for r in results)
        contacts = [r["contact_at_mm"] for r in results if r.get("contact_at_mm") is not None]
        no_contact = sum(1 for r in results if not r.get("toppled_before_probe") and r.get("contact_at_mm") is None)
        confirmed = sum(1 for r in results if r.get("contact_paw_confirmed"))
        mean_contact = np.mean(contacts) if contacts else None
        print(f"{h*1000:10.0f} {tb:14d} {td:14d} "
              f"{(f'{mean_contact:.1f}' if mean_contact is not None else '--'):>14} {no_contact:13d} "
              f"{confirmed:14d}/{len(contacts)}")
