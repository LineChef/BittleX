"""Periodic-replant crawl controller for climbing a step-up ledge, built from
validated pieces: probe-verified front-foot placement (probe_ledge_up.py's
mechanism, applied to both front legs) + a body-advance phase where the rear
legs step forward on known flat ground while both front feet stay IK-anchored
to their verified footholds, then probe-verified rear-foot placement onto the
platform.

Replaces the earlier probe_then_climb.py attempts (pure scripted continuation,
trained residual, rigid single-leg anchor) which all failed because they
either skipped body advancement entirely or tried to advance the body while
keeping ONE leg rigidly fixed (which just rotates the body around that point
instead of translating it -- see docs/rl/foot-probing-log.md round 3).

    python crawl_climb.py trained/run20m_resid30_ppo out.gif --ledge-h 0.025
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
from climb_env import _BASE as CLIMB_POSE_SEQ, PAW as CLIMB_PAW_LINKS, FRAME_SKIP, STANCE

FL_SHOULDER, FL_KNEE = 0, 1
FR_SHOULDER, FR_KNEE = 2, 3
RB_HIP, RB_KNEE = 4, 5
LB_HIP, LB_KNEE = 6, 7
PAW_LF, PAW_RF, PAW_RB, PAW_LB = 3, 6, 9, 12
EDGE_X = 0.11
CLIMB_REACH_FRAME = 20
FRAME_MS = 67
SLIDE_DEPTH_M = 0.025   # how far to slide forward onto the platform after first contact

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint")
ap.add_argument("out", nargs="?", default=None)
ap.add_argument("--ledge-h", type=float, default=0.025)
ap.add_argument("--stop-margin-m", type=float, default=0.02)
ap.add_argument("--body-target-margin-m", type=float, default=0.05,
                 help="stop when the BODY (not just the paw) is this close to the edge -- the paw-only "
                      "trigger left the body ~85-110mm back, which is most of why one loop pass wasn't "
                      "enough distance for the rear legs to ever reach the platform")
ap.add_argument("--settle-steps", type=int, default=80)
ap.add_argument("--above-margin-m", type=float, default=0.015)
ap.add_argument("--forward-margin-m", type=float, default=0.045,
                 help="how far past the edge each leg reaches before searching down. Tried 60mm "
                      "(farther reach, matching the reference climb) combined with the rest of "
                      "tonight's changes -- didn't hold up reliably in combination; reverted to the "
                      "validated value pending a more isolated follow-up.")
ap.add_argument("--search-steps", type=int, default=150)
ap.add_argument("--seed", type=int, default=7000)
ap.add_argument("--speed", type=float, default=3.0)
ap.add_argument("--w", type=int, default=480)
ap.add_argument("--h", type=int, default=360)
ap.add_argument("--skip-pull-step", action="store_true",
                 help="skip the pull-and-step phase, go straight from secured front feet into the push-commit")
ap.add_argument("--loop-end", type=int, default=60,
                 help="unused, kept for backward compat")
ap.add_argument("--n-passes", type=int, default=2,
                 help="unused, kept for backward compat")
ap.add_argument("--n-cycles", type=int, default=15,
                 help="max pull+tuck-swing-extend cycles before falling back to the tail push. "
                      "With the tuck-swing-extend rear-leg motion + probe-and-plant finish, 3 "
                      "test seeds all converged (both rear legs planted, no tail needed) within "
                      "3-4 cycles -- 15 leaves real safety margin without wasting runtime.")
ap.add_argument("--replant-every", type=int, default=5,
                 help="re-probe the front feet forward every N cycles, resetting accumulated knee "
                      "flex -- with the drag+probe breakthrough converging in just 3 cycles, the "
                      "default of 5 never fires even once, so front-knee flex accumulates unchecked "
                      "(traced directly to a body-height collapse -- see the session checkpoint doc)")
ap.add_argument("--pull-deg-per-cycle", type=float, default=6,
                 help="front-knee retraction per pull sub-phase (degrees) -- the drag strength")
ap.add_argument("--max-knee-flex-deg", type=float, default=30,
                 help="cap on accumulated front-knee flexion between replants")
ap.add_argument("--tuck-knee-deg", type=float, default=45,
                 help="rear-leg tuck-swing-extend motion, phase 1: how tight the knee tucks in")
ap.add_argument("--swing-hip-deg", type=float, default=-28,
                 help="rear-leg tuck-swing-extend motion, phase 2: how far the hip swings the "
                      "still-tucked leg forward")
ap.add_argument("--rear-step-every", type=int, default=1,
                 help="only do an active rear-leg tuck-swing-extend step every N cycles. 3 was tried "
                      "(matching 'drag mostly, step occasionally') but never closed enough distance "
                      "to trigger the probe-and-plant finish within n-cycles; 1 (step every cycle) "
                      "converges in just 3-4 cycles total and reliably skips the tail push entirely.")
ap.add_argument("--step-scale", type=float, default=1.3,
                 help="amplitude multiplier on the rear-leg swing's relative delta from cmh's own "
                      "swing shape. 1.0 (cmh's literal amplitude) plateaus around a 150mm pre-tail "
                      "gap; counterintuitively, LARGER scales (1.6-2.5) plateau even earlier (~130mm) "
                      "-- 1.3 is the value that actually keeps closing distance with more cycles "
                      "instead of saturating. 2/3 test seeds converge to a 36-61mm pre-tail gap at "
                      "1.3/40 (tilt 7-9.6 deg); one seed (7003) hits a seed-specific plateau around "
                      "125mm regardless of scale -- not yet resolved, see the checkpoint doc.")
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
    # Force every frame to be byte-distinct: during settle/hold phases the
    # camera and pose don't change, so consecutive frames are often
    # pixel-identical -- GIF/Pillow silently drops/merges those (confirmed
    # directly, persists even with optimize=False) and corrupts the merged
    # frame's duration to a large bogus value. A single deterministic pixel
    # tick (invisible in practice, top-left corner) prevents any merge.
    frame[0, 0, 0] = len(frames) % 256
    frames.append(frame)


def sim_step():
    global _step_count
    p.stepSimulation()
    _step_count += 1
    if args.out and _step_count % CAPTURE_EVERY == 0:
        _snap()


def probe_leg_onto_platform(paw_link, shoulder_idx, knee_idx, hold_targets, anchors,
                             platform_top_z, forward_margin, above_margin,
                             lift_first=True, weight_shift=None, do_slide=True,
                             anchor_force=0.5):
    """Lift+reach+search one leg onto the platform, holding any already-secured
    legs (in `anchors`: {link: world_pos}) fixed via continuous IK throughout.
    Returns (hold_targets, new_anchor_pos_or_None, solid_bool).

    `anchor_force`: how firmly the ALREADY-anchored legs (not the leg being
    probed, which always searches gently at 0.5) are held. The default 0.5
    matches the original front-leg-probing behavior; found directly (by
    extracting and looking at replay frames, not just trusting tilt) that
    0.5 is nowhere near firm enough once the anchored legs are already
    bearing real body weight at an extreme knee angle -- the body sags
    noticeably during a ~100-150+ step search at that softness, causing a
    straight-down collapse that stayed invisible to tilt (which only
    measures orientation, not height). Pass a firmer value (2.5-3.0) for
    any probe call happening after the front legs are already load-bearing.
    """
    def _probe_forces(probe_force=0.5):
        f = np.ones(8) * probe_force   # the leg actively searching stays gentle
        for link in anchors:
            sh, kn = {PAW_LF: (FL_SHOULDER, FL_KNEE), PAW_RF: (FR_SHOULDER, FR_KNEE),
                      PAW_RB: (RB_HIP, RB_KNEE), PAW_LB: (LB_HIP, LB_KNEE)}[link]
            f[sh] = anchor_force
            f[kn] = anchor_force
        return f.tolist()

    def _with_anchors(tgt):
        for link, pos in anchors.items():
            if pos is None:
                continue   # that leg never found the platform -- nothing to anchor to
            sh, kn = {PAW_LF: (FL_SHOULDER, FL_KNEE), PAW_RF: (FR_SHOULDER, FR_KNEE),
                      PAW_RB: (RB_HIP, RB_KNEE), PAW_LB: (LB_HIP, LB_KNEE)}[link]
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
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=_probe_forces(1.0))
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
                p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=_probe_forces(0.2))
                sim_step()
        hold_targets = lt
    paw_clear = p.getLinkState(rid, paw_link)[0]

    # Safety cap for both the reach and search-down phases below: without
    # this, reaching for an ABSOLUTE world-x target (above_x) on a repeat
    # call -- e.g. the same-side leverage advance, called on a leg that's
    # already been secured/dragged forward once and has less natural "slack"
    # left -- can saturate the knee at its physical joint limit (confirmed
    # directly: all 3 test seeds hit exactly ~90deg). That's what was
    # leaving the robot sitting on its belly once all four feet were secured.
    SAFE_KNEE_LIMIT_DEG = 89

    above_x = EDGE_X + forward_margin
    above_z = platform_top_z + above_margin
    rt = hold_targets.copy()
    for st in range(100):
        frac = (st + 1) / 100
        rp = [paw_clear[0] + (above_x - paw_clear[0]) * frac, paw_clear[1],
              paw_clear[2] + (above_z - paw_clear[2]) * frac]
        ikr = p.calculateInverseKinematics(rid, paw_link, rp)
        if abs(np.degrees(ikr[knee_idx])) > SAFE_KNEE_LIMIT_DEG:
            break   # would over-flex the knee to reach this -- stop, use the last good position
        rt = hold_targets.copy()
        rt[shoulder_idx] = ikr[shoulder_idx]
        rt[knee_idx] = ikr[knee_idx]
        tgt = _with_anchors(rt.copy())
        for _wait in range(10):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=_probe_forces())
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
        if abs(np.degrees(ik[knee_idx])) > SAFE_KNEE_LIMIT_DEG:
            break   # would over-flex the knee to reach this -- stop, use the last good position
        targets = hold_targets.copy()
        targets[shoulder_idx] = ik[shoulder_idx]
        targets[knee_idx] = ik[knee_idx]
        tgt = _with_anchors(targets.copy())
        for _wait in range(10):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=_probe_forces())
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

            # First contact usually lands shallow (near the edge, sometimes
            # under 5mm or even negative) -- the achieved x drifts short of
            # the commanded target under contact forces, matching an earlier
            # finding this leg's IK naturally retreats in x as it searches
            # deeper. A shallow foothold has almost no margin before a jerky
            # movement knocks it back off, which was directly reported as
            # the thing destabilizing the whole sequence. Now that contact
            # height is known, slide forward along the (now known-safe)
            # surface to a deeper, more secure resting point instead of
            # settling for wherever first contact happened.
            if nz > 0.7 and do_slide:
                # Safety cap: without this, the slide can walk the knee all
                # the way to its physical joint limit (~90deg, confirmed
                # directly -- all 3 test seeds hit EXACTLY that value) when
                # the requested slide target is slightly out of natural
                # reach, especially on a repeat call (e.g. the same-side
                # leverage advance) where the leg has already used up some
                # of its reach. That's what was causing the robot to end up
                # sitting on its belly once all four feet were secured.
                SAFE_KNEE_LIMIT_DEG = 89
                slide_target_x = cur[0] + SLIDE_DEPTH_M
                for _sst in range(20):
                    sfrac = (_sst + 1) / 20
                    sp = [cur[0] + (slide_target_x - cur[0]) * sfrac, cur[1], cur[2]]
                    sik = p.calculateInverseKinematics(rid, paw_link, sp)
                    if abs(np.degrees(sik[knee_idx])) > SAFE_KNEE_LIMIT_DEG:
                        break   # would over-flex the knee to reach this -- stop, use the last good position
                    starg = hold_targets.copy()
                    starg[shoulder_idx] = sik[shoulder_idx]
                    starg[knee_idx] = sik[knee_idx]
                    stgt = _with_anchors(starg.copy())
                    for _wait in range(6):
                        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, stgt, forces=_probe_forces())
                        sim_step()
                    scps = p.getContactPoints(bodyA=rid, linkIndexA=paw_link)
                    if not scps:
                        break   # slid off the edge of the platform -- stop, use the last good position
                    targets = starg
                cur = p.getLinkState(rid, paw_link)[0]
                x_margin_mm = 1000 * (cur[0] - EDGE_X)
                fcps = p.getContactPoints(bodyA=rid, linkIndexA=paw_link)
                fnz = fcps[0][7][2] if fcps else nz
                solid = fnz > 0.9 and x_margin_mm > 5
                print(f"  slid deeper: x-margin={x_margin_mm:.1f}mm, tilt={tilt():.1f} -> "
                      f"{'SOLID' if solid else 'marginal'}")
                return targets, cur, solid

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
print("Probing FL onto the platform...")
# Tried extending RB during this probe (matching the reference climb's
# one-leg-extended lean before the first foot placement) -- even a small
# -8deg shift held up alone, but broke down when combined with everything
# else tonight. Worth revisiting in isolation; reverted for now.
hold_targets, fl_anchor, fl_solid = probe_leg_onto_platform(
    PAW_LF, FL_SHOULDER, FL_KNEE, hold_targets, {}, platform_top_z,
    args.forward_margin_m, args.above_margin_m)
if fl_anchor is None:
    print("FL never found the platform -- aborting")
    raise SystemExit
print(f"FL secured: {'SOLID' if fl_solid else 'marginal'}")

print("Probing FR onto the platform (FL held anchored)...")
hold_targets, fr_anchor, fr_solid = probe_leg_onto_platform(
    PAW_RF, FR_SHOULDER, FR_KNEE, hold_targets, {PAW_LF: fl_anchor}, platform_top_z,
    args.forward_margin_m, args.above_margin_m,
    weight_shift=([RB_HIP, LB_HIP], 15))
if fr_anchor is None:
    print("FR never found the platform -- aborting")
    raise SystemExit
print(f"FR secured: {'SOLID' if fr_solid else 'marginal'}, "
      f"body_z={p.getBasePositionAndOrientation(rid)[0][2]:.4f}")

ANCHOR_FORCE = 3.0
PUSH_FORCE = 6.5
REAR_JOINTS_IDX = [RB_HIP, RB_KNEE, LB_HIP, LB_KNEE]
FRONT_JOINTS_IDX = [FL_SHOULDER, FL_KNEE, FR_SHOULDER, FR_KNEE]
RESIDUAL_BOUND_DEG = 30   # same bound as the walk policy's own scripted-base residual


RATE_LIMIT_DEG = 4.0   # max change per call to _with_front_ik's front targets
_front_ik_prev = {}


def _with_front_ik(tgt, fl_pos, fr_pos):
    # Full override -- used during the crawl loop, where the front feet must
    # be PRECISELY fixed each cycle to generate real pull-leverage. Tried a
    # bounded residual here too (matching the walk gait's scripted-base
    # architecture) but it regressed badly (2/4, propulsion stalled): body
    # pose shifts fast enough during the rear-leg swing that a +/-30deg
    # residual can't track the anchor tightly enough, so the front feet
    # gradually drift off their foothold instead of staying planted.
    #
    # Rate-limited on top of the full solve: re-solving IK fresh every call
    # toward a STATIC anchor should be continuous, but PyBullet's IK solver
    # can occasionally jump between qualitatively different joint solutions
    # near certain configurations -- a real discontinuous snap even though
    # the cartesian target never moved. That snap is what knocks an already-
    # solid front foot loose and destabilizes the rest of the sequence
    # (reported directly: jerkiness between movements costs the stable
    # footing already achieved on top of the platform). Clamping the
    # per-call change keeps the anchor precise (it still converges toward
    # the true IK solution, just gradually) without permitting a snap.
    ik_fl = p.calculateInverseKinematics(rid, PAW_LF, fl_pos)
    ik_fr = p.calculateInverseKinematics(rid, PAW_RF, fr_pos)
    raw = {FL_SHOULDER: ik_fl[FL_SHOULDER], FL_KNEE: ik_fl[FL_KNEE],
           FR_SHOULDER: ik_fr[FR_SHOULDER], FR_KNEE: ik_fr[FR_KNEE]}
    bound = np.deg2rad(RATE_LIMIT_DEG)
    limited = {}
    for j, v in raw.items():
        prev = _front_ik_prev.get(j, v)
        limited[j] = prev + np.clip(v - prev, -bound, bound)
    # Tried an absolute cap on the knee here too, reasoning it would stop
    # the runaway squat -- it broke anchor tracking instead (flip by cycle
    # 3, every seed): the knee genuinely needs to reach ~90deg at some
    # points to hold the anchor precisely as the body's pitch shifts through
    # the tuck-swing-extend cycles. The ~90deg knee angle isn't a bug in the
    # anchor tracking itself -- it's a real consequence of how much the body
    # moves during the maneuver. Fix belongs in the final standing
    # transition (uncrouching FROM ~90deg safely), not here.
    _front_ik_prev.update(limited)
    tgt[FL_SHOULDER], tgt[FL_KNEE] = limited[FL_SHOULDER], limited[FL_KNEE]
    tgt[FR_SHOULDER], tgt[FR_KNEE] = limited[FR_SHOULDER], limited[FR_KNEE]
    return tgt


def _with_front_residual(tgt, fl_pos, fr_pos):
    # BOUNDED residual toward the verified anchor, not a full override --
    # matches the walk gait's own architecture (scripted base + clipped
    # residual). Used only in the tail phase below, where tgt is ALREADY
    # cmh's own real trajectory for that tick -- this keeps cmh's shape as
    # the primary driver and only nudges by up to RESIDUAL_BOUND_DEG to
    # keep the front feet from drifting off their verified foothold.
    # Validated in isolation (crawl_climb_residual.py): stable, no flip,
    # tilt settles low, smoother than a full IK snap every substep.
    ik_fl = p.calculateInverseKinematics(rid, PAW_LF, fl_pos)
    ik_fr = p.calculateInverseKinematics(rid, PAW_RF, fr_pos)
    bound = np.deg2rad(RESIDUAL_BOUND_DEG)
    for j in (FL_SHOULDER, FL_KNEE):
        tgt[j] = tgt[j] + np.clip(ik_fl[j] - tgt[j], -bound, bound)
    for j in (FR_SHOULDER, FR_KNEE):
        tgt[j] = tgt[j] + np.clip(ik_fr[j] - tgt[j], -bound, bound)
    return tgt


def _rear_force(rear_level):
    f = np.ones(8) * 3.2
    for idx in REAR_JOINTS_IDX:
        f[idx] = rear_level
    for idx in FRONT_JOINTS_IDX:
        f[idx] = ANCHOR_FORCE
    return f.tolist()


def _foot_slipped(paw_link, anchor_pos, tol=0.01):
    cur = p.getLinkState(rid, paw_link)[0]
    return np.hypot(cur[0] - anchor_pos[0], cur[1] - anchor_pos[1]) > tol


print("Extending the rear legs for leverage (front feet already secured) -- "
      "a firm, braced push against the ground rather than jumping straight "
      "into small stepping increments. Force ramps in gradually (not a snap "
      "to full stiffness) to avoid a jerky transition out of the probe phase.")
REAR_EXTEND_HIP_DEG = 35
REAR_EXTEND_KNEE_DEG = 20
REAR_EXTEND_STEPS = 40
extend_targets = hold_targets.copy()
extend_targets[RB_HIP] += np.deg2rad(REAR_EXTEND_HIP_DEG)
extend_targets[LB_HIP] += np.deg2rad(REAR_EXTEND_HIP_DEG)
extend_targets[RB_KNEE] += np.deg2rad(REAR_EXTEND_KNEE_DEG)
extend_targets[LB_KNEE] += np.deg2rad(REAR_EXTEND_KNEE_DEG)
lt = hold_targets.copy()
for st in range(REAR_EXTEND_STEPS):
    frac = (st + 1) / REAR_EXTEND_STEPS
    lt = hold_targets * (1 - frac) + extend_targets * frac
    tgt = _with_front_ik(lt.copy(), fl_anchor, fr_anchor)
    f = np.ones(8) * 1.0
    rear_f = 1.0 + 2.0 * frac   # ramp 1.0 -> 3.0, not a snap to full stiffness
    for idx in REAR_JOINTS_IDX:
        f[idx] = rear_f
    for idx in FRONT_JOINTS_IDX:
        f[idx] = ANCHOR_FORCE
    for _wait in range(6):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=f.tolist())
        sim_step()
hold_targets = _with_front_ik(lt.copy(), fl_anchor, fr_anchor)
fl_anchor = p.getLinkState(rid, PAW_LF)[0]
fr_anchor = p.getLinkState(rid, PAW_RF)[0]
tl = tilt()
bx, _by, bz = p.getBasePositionAndOrientation(rid)[0]
print(f"  extended: body_x={bx:.4f}, tilt={tl:.1f}, body_z={bz:.4f}")
if tl > 68.8:
    print("FLIPPED during rear-leg extension -- aborting")
    if args.out and frames:
        for _ in range(15):
            _snap()
    env.close()
    raise SystemExit

print("Repeated pull+step (small increments, many cycles): the reference-gait "
      "loop advances the body only ~30-40mm per pass and hits a front-leg "
      "reach ceiling after just one, but the rear legs need to close ~100mm+ "
      "to reach the platform -- that's genuinely more distance than one or "
      "two keyframe-sequence passes were ever going to cover; it needs real "
      "repeated walking. Using the validated pull mechanism (clean, "
      "monotonic, zero-slip earlier today) with SMALLER per-cycle increments "
      "so flexion never has to build up unboundedly, periodically re-probing "
      "the front feet forward to reset it and keep advancing the anchor.")

N_CYCLES = args.n_cycles
PULL_DEG_PER_CYCLE = args.pull_deg_per_cycle
REPLANT_EVERY = args.replant_every
MAX_KNEE_FLEX_DEG = args.max_knee_flex_deg
# The full 6->60 stance+swing loop was tried and destabilized badly (tilt hit
# 180deg by cycle 3): replaying cmh's "stance/push" portion while the front
# feet are RIGIDLY anchored reproduces the exact "rigid anchor + rear push
# rotates the body instead of translating it" failure mode from earlier this
# session. Using just the swing/place portion (lift, move forward, place
# down) instead -- the propulsion keeps coming from the proven front-pull
# mechanism; this only gives the rear legs cmh's real swing SHAPE in place of
# the hand-built flex/flex/reset motion.
REAR_GAIT_START, REAR_GAIT_END = 39, 60
PROBE_ATTEMPT_THRESHOLD_M = 0.08
flipped = False
_flex_since_replant = 0.0
rb_anchor = None
lb_anchor = None
for cyc in range(N_CYCLES):
    this_pull = min(PULL_DEG_PER_CYCLE, max(0.0, MAX_KNEE_FLEX_DEG - _flex_since_replant))
    lt = hold_targets.copy()
    if this_pull > 0:
        for st in range(10):
            frac = (st + 1) / 10
            lt = hold_targets.copy()
            lt[FL_KNEE] = hold_targets[FL_KNEE] - np.deg2rad(this_pull) * frac
            lt[FR_KNEE] = hold_targets[FR_KNEE] - np.deg2rad(this_pull) * frac
            for _wait in range(6):
                # rear legs held FIRM (2.5, not the original soft 1.0) during
                # the pull -- keeps them standing tall/extended instead of
                # sagging while the front does its work, matching the
                # reference climb's tall stance throughout the pull.
                p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, lt, forces=_rear_force(2.5))
                sim_step()
        _flex_since_replant += this_pull
    hold_targets = lt
    fl_anchor = p.getLinkState(rid, PAW_LF)[0]
    fr_anchor = p.getLinkState(rid, PAW_RF)[0]

    # Once a rear leg is close enough, plant it directly with the SAME
    # validated probe mechanism the front legs use (reach forward, search
    # down, confirm real contact) instead of an invented stepping shape --
    # matches the reference climb precisely: one rear leg kicks forward
    # until it hits the ledge and plants there, which then brings the body
    # (and the other rear leg) close enough to plant too. Naming convention:
    # PAW_LF/PAW_RF/PAW_RB/PAW_LB = Left-Front/Right-Front/Right-Back/
    # Left-Back, so same-side pairs are (LF,LB) and (RF,RB).
    #
    # Pure front-pull alone (removing the swing-step entirely) was tried and
    # plateaued far short of the platform (~145mm, WORSE than with swing-
    # stepping) -- the rear legs are still bearing real weight/friction after
    # the extend phase and actively resist being dragged rather than sliding
    # freely, so drag alone isn't enough propulsion in this sim. Swing-
    # stepping (every REAR_STEP_EVERY cycles) stays as the real propulsion;
    # the probe-and-plant below is the FINISHING move once a leg is
    # genuinely in reach, not a replacement for stepping.
    rb_cur = p.getLinkState(rid, PAW_RB)[0]
    lb_cur = p.getLinkState(rid, PAW_LB)[0]
    if rb_anchor is None and (EDGE_X - rb_cur[0]) < PROBE_ATTEMPT_THRESHOLD_M:
        margin = max(args.forward_margin_m, (EDGE_X - rb_cur[0]) + 0.02)
        hold_targets, rb_new, rb_solid = probe_leg_onto_platform(
            PAW_RB, RB_HIP, RB_KNEE, hold_targets, {PAW_LF: fl_anchor, PAW_RF: fr_anchor},
            platform_top_z, margin, args.above_margin_m, lift_first=True, anchor_force=2.5)
        if rb_new is not None and rb_solid:
            rb_anchor = rb_new
            print(f"  RB planted at cycle {cyc}: {1000*(rb_anchor[0]-EDGE_X):.0f}mm past the edge")
            # Same-side front leg (RF/FR) advances deeper for more leverage
            # once its rear partner has purchase -- directly observed in the
            # reference climb as a big part of how it gains the pull-up.
            fr_cur = p.getLinkState(rid, PAW_RF)[0]
            fr_margin = max(args.forward_margin_m, (fr_cur[0] - EDGE_X) + 0.02)
            hold_targets, fr_new, fr_solid = probe_leg_onto_platform(
                PAW_RF, FR_SHOULDER, FR_KNEE, hold_targets, {PAW_LF: fl_anchor, PAW_RB: rb_anchor},
                platform_top_z, fr_margin, args.above_margin_m, lift_first=False, do_slide=False, anchor_force=2.5)
            if fr_new is not None:
                fr_anchor = fr_new
                print(f"  FR (same side as RB) advanced for leverage: "
                      f"{'SOLID' if fr_solid else 'marginal'}")
    elif rb_anchor is not None and lb_anchor is None and (EDGE_X - lb_cur[0]) < PROBE_ATTEMPT_THRESHOLD_M:
        margin = max(args.forward_margin_m, (EDGE_X - lb_cur[0]) + 0.02)
        hold_targets, lb_new, lb_solid = probe_leg_onto_platform(
            PAW_LB, LB_HIP, LB_KNEE, hold_targets, {PAW_LF: fl_anchor, PAW_RF: fr_anchor, PAW_RB: rb_anchor},
            platform_top_z, margin, args.above_margin_m, lift_first=True, anchor_force=2.5)
        if lb_new is not None and lb_solid:
            lb_anchor = lb_new
            print(f"  LB planted at cycle {cyc}: {1000*(lb_anchor[0]-EDGE_X):.0f}mm past the edge")
            # Same-side front leg (LF/FL) advances deeper for more leverage.
            fl_cur = p.getLinkState(rid, PAW_LF)[0]
            fl_margin = max(args.forward_margin_m, (fl_cur[0] - EDGE_X) + 0.02)
            hold_targets, fl_new, fl_solid = probe_leg_onto_platform(
                PAW_LF, FL_SHOULDER, FL_KNEE, hold_targets, {PAW_RF: fr_anchor, PAW_RB: rb_anchor, PAW_LB: lb_anchor},
                platform_top_z, fl_margin, args.above_margin_m, lift_first=False, do_slide=False, anchor_force=2.5)
            if fl_new is not None:
                fl_anchor = fl_new
                print(f"  FL (same side as LB) advanced for leverage: "
                      f"{'SOLID' if fl_solid else 'marginal'}")
    elif cyc % args.rear_step_every == 0:
        # Three distinct, sequential phases (user's direct description of
        # the reference climb's rear-leg motion), replacing the cmh-swing-
        # shape blend which moved hip and knee together throughout:
        #   1. TUCK: knee flexes in as tight as possible, hip stays put.
        #   2. SWING: hip rotates the whole (still-tucked) leg forward,
        #      knee stays tucked -- ground clearance is maximal here since
        #      the foot is pulled in close to the body.
        #   3. EXTEND: only now does the knee swing back down/out, and
        #      THIS is the actual power stroke that propels the body
        #      forward -- held at a firmer force than the first two phases
        #      since it's doing real work against the ground, not just
        #      repositioning.
        rear_base = hold_targets.copy()
        SUPPORT_FORCE = 1.0
        TUCK_KNEE_DEG = args.tuck_knee_deg
        SWING_HIP_DEG = args.swing_hip_deg
        PHASE_STEPS = 15

        tucked = rear_base.copy()
        tucked[RB_KNEE] = rear_base[RB_KNEE] + np.deg2rad(TUCK_KNEE_DEG)
        tucked[LB_KNEE] = rear_base[LB_KNEE] + np.deg2rad(TUCK_KNEE_DEG)
        for st in range(PHASE_STEPS):
            frac = (st + 1) / PHASE_STEPS
            tgt = rear_base * (1 - frac) + tucked * frac
            tgt = _with_front_ik(tgt.copy(), fl_anchor, fr_anchor)
            for _wait in range(FRAME_SKIP):
                p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=_rear_force(SUPPORT_FORCE))
                sim_step()
        print(f"    tuck: body_x={p.getBasePositionAndOrientation(rid)[0][0]:.4f}, tilt={tilt():.1f}")

        swung = tucked.copy()
        swung[RB_HIP] = tucked[RB_HIP] - np.deg2rad(SWING_HIP_DEG)
        swung[LB_HIP] = tucked[LB_HIP] - np.deg2rad(SWING_HIP_DEG)
        for st in range(PHASE_STEPS):
            frac = (st + 1) / PHASE_STEPS
            tgt = tucked * (1 - frac) + swung * frac
            tgt = _with_front_ik(tgt.copy(), fl_anchor, fr_anchor)
            for _wait in range(FRAME_SKIP):
                p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=_rear_force(SUPPORT_FORCE))
                sim_step()
        print(f"    swing: body_x={p.getBasePositionAndOrientation(rid)[0][0]:.4f}, tilt={tilt():.1f}")

        extended = swung.copy()
        extended[RB_KNEE] = rear_base[RB_KNEE]
        extended[LB_KNEE] = rear_base[LB_KNEE]
        for st in range(PHASE_STEPS):
            frac = (st + 1) / PHASE_STEPS
            tgt = swung * (1 - frac) + extended * frac
            tgt = _with_front_ik(tgt.copy(), fl_anchor, fr_anchor)
            for _wait in range(FRAME_SKIP):
                p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=_rear_force(SUPPORT_FORCE * 2))
                sim_step()
        hold_targets = tgt
        print(f"    extend/propel: body_x={p.getBasePositionAndOrientation(rid)[0][0]:.4f}, tilt={tilt():.1f}")

    tl = tilt()
    bx, _by, bz = p.getBasePositionAndOrientation(rid)[0]
    print(f"  cycle {cyc}: body_x={bx:.4f}, body_z={bz:.4f}, tilt={tl:.1f}, "
          f"FL_slip={_foot_slipped(PAW_LF, fl_anchor)}, FR_slip={_foot_slipped(PAW_RF, fr_anchor)}")
    if tl > 68.8:
        print(f"FLIPPED at cycle {cyc}")
        flipped = True
        break

    if rb_anchor is not None and lb_anchor is not None:
        bz_here = p.getBasePositionAndOrientation(rid)[0][2]
        print(f"  Both rear legs planted via drag+probe at cycle {cyc} -- "
              f"skipping the explosive tail push entirely. "
              f"body_z={bz_here:.4f}m (clearance above platform={bz_here-platform_top_z:.4f}m)")
        break

    if (cyc + 1) % REPLANT_EVERY == 0 and cyc + 1 < N_CYCLES:
        print(f"  re-planting front feet (reset flexion, advance anchor) after cycle {cyc}...")
        fl_cur = p.getLinkState(rid, PAW_LF)[0]
        fl_margin = max(args.forward_margin_m, (fl_cur[0] - EDGE_X) + 0.015)
        hold_targets, fl_new, fl_solid2 = probe_leg_onto_platform(
            PAW_LF, FL_SHOULDER, FL_KNEE, hold_targets, {PAW_RF: fr_anchor}, platform_top_z,
            fl_margin, args.above_margin_m, lift_first=False)
        if fl_new is not None:
            fl_anchor = fl_new
        fr_cur = p.getLinkState(rid, PAW_RF)[0]
        fr_margin = max(args.forward_margin_m, (fr_cur[0] - EDGE_X) + 0.015)
        hold_targets, fr_new, fr_solid2 = probe_leg_onto_platform(
            PAW_RF, FR_SHOULDER, FR_KNEE, hold_targets, {PAW_LF: fl_anchor}, platform_top_z,
            fr_margin, args.above_margin_m, lift_first=False)
        if fr_new is not None:
            fr_anchor = fr_new
        bx = p.getBasePositionAndOrientation(rid)[0][0]
        print(f"    re-planted: body_x={bx:.4f}, tilt={tilt():.1f}, "
              f"FL={'ok' if fl_new is not None else 'stuck'}, FR={'ok' if fr_new is not None else 'stuck'}")
        _flex_since_replant = 0.0   # fresh anchor -- knee is no longer artificially bent

if flipped:
    if args.out and frames:
        for _ in range(15):
            _snap()
    env.close()
    raise SystemExit

# The in-loop probe check runs at the TOP of each cycle using the position
# from the END of the previous cycle -- so if the last cycle's step is what
# finally brought a leg into range, there's no next cycle left to actually
# try the probe. One more attempt here, on the final position, catches that.
rb_cur = p.getLinkState(rid, PAW_RB)[0]
lb_cur = p.getLinkState(rid, PAW_LB)[0]
if rb_anchor is None and (EDGE_X - rb_cur[0]) < PROBE_ATTEMPT_THRESHOLD_M:
    margin = max(args.forward_margin_m, (EDGE_X - rb_cur[0]) + 0.02)
    hold_targets, rb_new, rb_solid = probe_leg_onto_platform(
        PAW_RB, RB_HIP, RB_KNEE, hold_targets, {PAW_LF: fl_anchor, PAW_RF: fr_anchor},
        platform_top_z, margin, args.above_margin_m, lift_first=True)
    if rb_new is not None and rb_solid:
        rb_anchor = rb_new
        print(f"  RB planted (final check): {1000*(rb_anchor[0]-EDGE_X):.0f}mm past the edge")
        fr_cur = p.getLinkState(rid, PAW_RF)[0]
        fr_margin = max(args.forward_margin_m, (fr_cur[0] - EDGE_X) + 0.02)
        hold_targets, fr_new, fr_solid = probe_leg_onto_platform(
            PAW_RF, FR_SHOULDER, FR_KNEE, hold_targets, {PAW_LF: fl_anchor, PAW_RB: rb_anchor},
            platform_top_z, fr_margin, args.above_margin_m, lift_first=False)
        if fr_new is not None:
            fr_anchor = fr_new
if rb_anchor is not None and lb_anchor is None and (EDGE_X - lb_cur[0]) < PROBE_ATTEMPT_THRESHOLD_M:
    margin = max(args.forward_margin_m, (EDGE_X - lb_cur[0]) + 0.02)
    hold_targets, lb_new, lb_solid = probe_leg_onto_platform(
        PAW_LB, LB_HIP, LB_KNEE, hold_targets, {PAW_LF: fl_anchor, PAW_RF: fr_anchor, PAW_RB: rb_anchor},
        platform_top_z, margin, args.above_margin_m, lift_first=True)
    if lb_new is not None and lb_solid:
        lb_anchor = lb_new
        print(f"  LB planted (final check): {1000*(lb_anchor[0]-EDGE_X):.0f}mm past the edge")
        fl_cur = p.getLinkState(rid, PAW_LF)[0]
        fl_margin = max(args.forward_margin_m, (fl_cur[0] - EDGE_X) + 0.02)
        hold_targets, fl_new, fl_solid = probe_leg_onto_platform(
            PAW_LF, FL_SHOULDER, FL_KNEE, hold_targets, {PAW_RF: fr_anchor, PAW_RB: rb_anchor, PAW_LB: lb_anchor},
            platform_top_z, fl_margin, args.above_margin_m, lift_first=False)
        if fl_new is not None:
            fl_anchor = fl_new

rb_pre_tail = p.getLinkState(rid, PAW_RB)[0]
lb_pre_tail = p.getLinkState(rid, PAW_LB)[0]
print(f"  PRE-TAIL: RB is {1000*(EDGE_X-rb_pre_tail[0]):.0f}mm behind the edge, "
      f"LB is {1000*(EDGE_X-lb_pre_tail[0]):.0f}mm behind -- how far the crawl "
      f"loop got them on its own, before the tail's push contributes anything.")

labels = ["FL", "FR", "RB", "LB"]
if rb_anchor is not None and lb_anchor is not None:
    print("  Both rear legs already planted via drag+probe -- no tail push needed.")
else:
    print("Tail step-up (cmh's own real tick-by-tick path, not a shortcut, but "
          "executed much more slowly at moderate force instead of the raw "
          "explosive 4-steps-per-tick/force-6.5 burst)...")
    TICK_SUBSTEPS = 8   # was 4 -- same path, ~2x slower (16 was tried and made
                        # things WORSE -- more time for the body to tip before
                        # the joints catch up, confirmed: one seed hit 168deg
                        # tilt where the original fast version never did)
    for ti, t in enumerate(range(166, len(CLIMB_POSE_SEQ))):
        tgt = _with_front_ik(CLIMB_POSE_SEQ[t].copy(), fl_anchor, fr_anchor)
        f = _rear_force(min(PUSH_FORCE, 2.0 + (PUSH_FORCE - 2.0) * (ti + 1) / 4))
        for _ in range(TICK_SUBSTEPS):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=f)
            sim_step()
        tl = tilt()
        if tl > 68.8:
            print(f"FLIPPED during push at tick {t}")
            flipped = True
            break
    hold_targets = tgt
    bx = p.getBasePositionAndOrientation(rid)[0][0]
    print(f"  push done: body_x={bx:.4f}, tilt={tilt():.1f}")

    # Front legs got here via probe-and-verify, not cmh's blind trajectory --
    # the rear legs need the same treatment now that the natural-gait advance
    # has brought the body close. cmh's own tail motion pushes the rear paws
    # BACKWARD relative to the body (a launch, not a placement -- confirmed
    # via the earlier FK trace), so it was never going to land them on the
    # platform precisely; reuse the same validated probe mechanism instead.
    fl_anchor = p.getLinkState(rid, PAW_LF)[0]
    fr_anchor = p.getLinkState(rid, PAW_RF)[0]
    if rb_anchor is None:
        rb_start = p.getLinkState(rid, PAW_RB)[0]
        rear_forward_margin = max(args.forward_margin_m, (EDGE_X - rb_start[0]) + 0.020)
        print(f"  RB starts {1000*(EDGE_X-rb_start[0]):.0f}mm behind the edge -- using "
              f"{1000*rear_forward_margin:.0f}mm forward margin instead of the front legs' "
              f"{1000*args.forward_margin_m:.0f}mm")
        print("Probing RB onto the platform (front feet held anchored)...")
        hold_targets2, rb_anchor, rb_solid = probe_leg_onto_platform(
            PAW_RB, RB_HIP, RB_KNEE, hold_targets, {PAW_LF: fl_anchor, PAW_RF: fr_anchor}, platform_top_z,
            rear_forward_margin, args.above_margin_m)
        if rb_anchor is not None:
            print(f"RB secured: {'SOLID' if rb_solid else 'marginal'}")
            hold_targets = hold_targets2
        else:
            print("RB never found the platform")
    if rb_anchor is not None and lb_anchor is None:
        lb_start = p.getLinkState(rid, PAW_LB)[0]
        lb_forward_margin = max(args.forward_margin_m, (EDGE_X - lb_start[0]) + 0.020)
        print("Probing LB onto the platform (front feet + RB held anchored)...")
        hold_targets2, lb_anchor, lb_solid = probe_leg_onto_platform(
            PAW_LB, LB_HIP, LB_KNEE, hold_targets,
            {PAW_LF: fl_anchor, PAW_RF: fr_anchor, PAW_RB: rb_anchor}, platform_top_z,
            lb_forward_margin, args.above_margin_m)
        if lb_anchor is not None:
            print(f"LB secured: {'SOLID' if lb_solid else 'marginal'}")
            hold_targets = hold_targets2
        else:
            print("LB never found the platform")

def _with_all_four_ik(tgt):
    anchors4 = {PAW_LF: fl_anchor, PAW_RF: fr_anchor, PAW_RB: rb_anchor, PAW_LB: lb_anchor}
    joints4 = {PAW_LF: (FL_SHOULDER, FL_KNEE), PAW_RF: (FR_SHOULDER, FR_KNEE),
               PAW_RB: (RB_HIP, RB_KNEE), PAW_LB: (LB_HIP, LB_KNEE)}
    for link, anchor in anchors4.items():
        if anchor is None:
            continue
        sh, kn = joints4[link]
        ik = p.calculateInverseKinematics(rid, link, anchor)
        tgt[sh] = ik[sh]
        tgt[kn] = ik[kn]
    return tgt


# Tried extra _with_front_ik settle calls here, reasoning the knee was
# stuck at an old transient-tilt extreme and hadn't had enough calls to walk
# back down -- disproven directly: even 40 more calls at tilt fully settled
# to 9.2deg still needed ~90deg knee flex. The REAL explanation: the rear
# legs have genuinely lifted the body much higher by this point (that's
# their whole leverage purpose), so the OLD front anchor -- captured early,
# near platform level -- is now almost directly below the shoulder, which
# geometrically requires near-max knee fold to reach. Not a tracking bug.

js = p.getJointStates(rid, env.joint_id)
fl_knee_deg = np.degrees(js[FL_KNEE][0])
fr_knee_deg = np.degrees(js[FR_KNEE][0])
print(f"  front knee flex before standing: FL={fl_knee_deg:.1f}deg FR={fr_knee_deg:.1f}deg "
      f"(accumulated across the initial secure, the slide-deeper depth fix, and the same-side "
      f"leverage advance -- far more than the pull mechanism's own 30deg cap alone accounts for)")
print("Standing tall now that all four feet are secured on the platform -- "
      "un-crouching the front knee IN PLACE (toward a fixed target angle) "
      "was tried, in one continuous motion and in several smaller stages; "
      "both left the robot tilted 44-55deg, not standing. The knee angle "
      "isn't really the thing to fix directly -- the STALE ANCHOR is: "
      "fl_anchor/fr_anchor were captured back when the body was still low, "
      "and the rear-leg extension has genuinely lifted the body a lot since "
      "then, so holding that same old anchor forces the extreme fold. "
      "Re-establishing a FRESH front anchor now, with the paw already on "
      "the platform and the body at its current (taller) height, should "
      "naturally settle on a much more reasonable knee angle instead of "
      "fighting the old one.")
fl_cur = p.getLinkState(rid, PAW_LF)[0]
fl_margin = max(0.01, (fl_cur[0] - EDGE_X))
hold_targets, fl_new, fl_solid = probe_leg_onto_platform(
    PAW_LF, FL_SHOULDER, FL_KNEE, hold_targets, {PAW_RF: fr_anchor, PAW_RB: rb_anchor, PAW_LB: lb_anchor},
    platform_top_z, fl_margin, args.above_margin_m, lift_first=False, do_slide=False, anchor_force=2.5)
if fl_new is not None:
    fl_anchor = fl_new
fr_cur = p.getLinkState(rid, PAW_RF)[0]
fr_margin = max(0.01, (fr_cur[0] - EDGE_X))
hold_targets, fr_new, fr_solid = probe_leg_onto_platform(
    PAW_RF, FR_SHOULDER, FR_KNEE, hold_targets, {PAW_LF: fl_anchor, PAW_RB: rb_anchor, PAW_LB: lb_anchor},
    platform_top_z, fr_margin, args.above_margin_m, lift_first=False, do_slide=False, anchor_force=2.5)
if fr_new is not None:
    fr_anchor = fr_new
js = p.getJointStates(rid, env.joint_id)
print(f"  fresh front anchors: FL_KNEE={np.degrees(js[FL_KNEE][0]):.1f}deg "
      f"FR_KNEE={np.degrees(js[FR_KNEE][0]):.1f}deg, "
      f"body_x={p.getBasePositionAndOrientation(rid)[0][0]:.4f}, tilt={tilt():.1f}")

# A single 5deg knee-only change (tested directly) immediately spiked tilt
# to 22.6 -- this ~90deg-knee configuration is a fragile, marginal
# equilibrium, not a robust stand; changing the knee IN PLACE (without
# moving the foot) isn't the right lever. Repositioning the FOOT itself
# closer to the body instead: less reach required means less knee fold
# naturally, tracked via fresh IK toward a pulled-back anchor (not a direct
# joint-angle edit), so hip and knee move together in a way that's
# geometrically consistent instead of fighting each other.
# Pulling the front anchor backward (horizontal) was tried and made the
# knee angle slightly WORSE (90.2 -> 90.8deg) -- the real driver isn't
# horizontal distance, it's VERTICAL: the body sits tall (the rear-leg
# extension's own job) while the front foot is still down near platform
# height, so the front knee has to fold to bridge that height gap no matter
# where the foot sits horizontally. Letting the REAR legs settle down a
# little too (undoing part of their own extension) should let the whole
# body genuinely lower, which should un-fold the front knee as a natural
# side effect -- rather than fighting the front leg in isolation while the
# rear insists on holding the body up tall.
# REAL root cause, now confirmed (not guessed): body_z was ALREADY down to
# 0.0542m by the moment RB's own probe fires (traced tick by tick: 0.1020 ->
# 0.1017 -> 0.0819 -> 0.0542m across the pull cycles) -- BEFORE any of this
# "standing" code runs at all, and unaffected by a firmer anchor-hold-force
# fix (tested directly, identical numbers with or without it). The pull
# mechanism's own front-knee retraction is what's doing this: it's the
# actual propulsion source (folding the knee generates the pull leverage),
# and folding a leg mechanically shortens it, which necessarily lowers the
# body -- a real, expected side effect of how this propulsion works, not a
# bug. So earlier fixes aimed at "why is the knee at 90deg" or "why isn't
# the anchor holding firmly" were addressing the wrong layer entirely.
#
# The real fix is a genuine stand-up push: since all four feet are now
# resting on solid, FLAT platform ground (unlike anywhere during the climb
# itself, where the geometry was actively changing), a SYNCHRONIZED
# extension of all four legs together should be far safer than adjusting
# one leg in isolation against the others -- much closer to how a real
# quadruped recovers from a crouch (push up on every leg at once, not one
# at a time). Very small per-step increments, watching both tilt AND height
# gain, aborting early if tilt rises.
print("Synchronized stand-up push: extending all four legs together (front "
      "knee straightens, rear hip+knee extend further) in small increments, "
      "since a full crouch recovery on one leg at a time either destabilized "
      "or had no effect -- pushing up on all four together, like a real "
      "quadruped would, since all four feet are now on solid flat ground. "
      "Done in MULTIPLE STAGES with a settle between each, so tilt has a "
      "chance to recover before the next push adds more, rather than one "
      "continuous push that has to stop the moment tilt crosses a threshold.")
STANDUP_FRONT_KNEE_DEG_PER_STAGE = 12
STANDUP_REAR_HIP_DEG_PER_STAGE = 5
STANDUP_REAR_KNEE_DEG_PER_STAGE = 4
STANDUP_STAGES = 4
STANDUP_STEPS_PER_STAGE = 15
SETTLE_STEPS_PER_STAGE = 20
TILT_ABORT = 20
z0 = p.getBasePositionAndOrientation(rid)[0][2]
cur = hold_targets.copy()
for _stage in range(STANDUP_STAGES):
    start = cur.copy()
    target = cur.copy()
    target[FL_KNEE] -= np.deg2rad(STANDUP_FRONT_KNEE_DEG_PER_STAGE)
    target[FR_KNEE] -= np.deg2rad(STANDUP_FRONT_KNEE_DEG_PER_STAGE)
    target[RB_HIP] += np.deg2rad(STANDUP_REAR_HIP_DEG_PER_STAGE)
    target[LB_HIP] += np.deg2rad(STANDUP_REAR_HIP_DEG_PER_STAGE)
    target[RB_KNEE] += np.deg2rad(STANDUP_REAR_KNEE_DEG_PER_STAGE)
    target[LB_KNEE] += np.deg2rad(STANDUP_REAR_KNEE_DEG_PER_STAGE)
    stage_cur = start.copy()
    for _sstep in range(STANDUP_STEPS_PER_STAGE):
        frac = (_sstep + 1) / STANDUP_STEPS_PER_STAGE
        nxt = start * (1 - frac) + target * frac
        for _wait in range(6):
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, nxt, forces=np.ones(8) * 2.0)
            sim_step()
        if tilt() > TILT_ABORT:
            break
        stage_cur = nxt
    # settle at firm force before the next stage, letting tilt recover
    for _wait in range(SETTLE_STEPS_PER_STAGE):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, stage_cur, forces=np.ones(8) * 2.5)
        sim_step()
    z_now = p.getBasePositionAndOrientation(rid)[0][2]
    print(f"    standup stage {_stage+1}/{STANDUP_STAGES}: body_z={z_now:.4f} "
          f"(+{1000*(z_now-z0):.0f}mm), tilt={tilt():.1f}")
    cur = stage_cur
    if tilt() > TILT_ABORT:
        print(f"    tilt still over {TILT_ABORT}deg after settling -- stopping the stand-up push here")
        break
z_final = p.getBasePositionAndOrientation(rid)[0][2]
print(f"  stand-up push done: body_z={z_final:.4f} (+{1000*(z_final-z0):.0f}mm from before), tilt={tilt():.1f}")
hold_targets = cur
# The final settle below re-solves fresh IK toward all four anchors -- if
# any still point at the OLD (pre-standup) position, that settle would just
# snap the leg straight back and undo the stand-up push. The rear legs
# weren't anchor-tracked during the push (direct joint control, so they
# could actually extend), so their foot position moved too -- update all
# four to wherever the feet actually ended up.
fl_anchor = p.getLinkState(rid, PAW_LF)[0]
fr_anchor = p.getLinkState(rid, PAW_RF)[0]
rb_anchor = p.getLinkState(rid, PAW_RB)[0]
lb_anchor = p.getLinkState(rid, PAW_LB)[0]
print(f"  standing: body_x={p.getBasePositionAndOrientation(rid)[0][0]:.4f}, tilt={tilt():.1f}")

# CRITICAL BUG FOUND (by extracting and looking at our own replay frames,
# not just trusting tilt): a soft-starting force ramp (0.8 -> ANCHOR_FORCE
# over 15 steps) here was letting the body SAG STRAIGHT DOWN under gravity
# during that low-force window, before the ramp caught up -- with the front
# knee already near its ~90deg limit (an awkward, barely-supportable
# configuration), 0.8 isn't enough to hold the body's weight up at all.
# This is a STRAIGHT-DOWN collapse (body stays level/un-rotated the whole
# time), which is exactly why `tilt` (roll/pitch only) never caught it --
# tilt measures ORIENTATION, not HEIGHT, and a robot can be perfectly level
# while completely collapsed. Confirmed directly: extracted frames from our
# own GIF around this point in the sequence show the body flush against the
# platform surface, legs splayed, matching the user's "falls on its face"
# report exactly -- something the printed tilt diagnostic never revealed.
# Fix: track body HEIGHT explicitly (not just tilt) as a real diagnostic
# going forward, and start this settle at firm force throughout -- the
# jerkiness a soft start was meant to prevent is a far smaller problem than
# an invisible collapse.
body_z_before_settle = p.getBasePositionAndOrientation(rid)[0][2]
print(f"  body height before final settle: {body_z_before_settle:.4f}m")
FINAL_SETTLE_STEPS = 40
for _fs in range(FINAL_SETTLE_STEPS):
    tgt = _with_all_four_ik(hold_targets.copy())
    settle_force = ANCHOR_FORCE
    p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=np.ones(8) * settle_force)
    sim_step()
paws = [p.getLinkState(rid, j)[0] for j in CLIMB_PAW_LINKS]
final_tilt = tilt()
# A flipped-onto-its-back robot can still satisfy the paw-height/x check --
# the check alone doesn't verify orientation. Gate the whole result on tilt
# so a flip never reports as a false "4/4" success again.
if final_tilt > 68.8:
    on_top_each = {lbl: False for lbl in labels}
else:
    on_top_each = {lbl: (pz > platform_top_z - 0.02 and px > EDGE_X - 0.02) for lbl, (px, py, pz) in zip(labels, paws)}
on_top = sum(on_top_each.values())
bx, by, bz = p.getBasePositionAndOrientation(rid)[0]
# Paw-height alone doesn't catch a collapsed body between well-planted feet
# (confirmed directly: tilt stayed ~9deg while the body sat flush against
# the platform, legs splayed -- "sitting on its belly" exactly as reported).
# Report body height relative to the platform explicitly so this is visible
# in the numbers from now on, not just discoverable by extracting frames.
body_clearance = bz - platform_top_z
print(f"FINAL: {on_top}/4 paws on-top {on_top_each}, body_x={bx:.4f}, "
      f"tilt={final_tilt:.1f}, body_clearance_above_platform={body_clearance:.4f}m")

if args.out and frames:
    # Extra hold frames at the SAME constant duration as the rest, not a
    # longer per-frame duration -- Pillow (12.3.0, confirmed via direct
    # test) silently collapses a per-frame duration LIST to just the last
    # value applied to every frame when saving a GIF, regardless of frame
    # count or optimize=. A single constant `duration=` int is the only
    # form that's actually respected. This bug likely wrecked the intended
    # playback speed on every GIF saved this way earlier in the session too.
    for _ in range(45):
        _snap()
env.close()

if args.out and frames:
    from PIL import Image
    imgs = [Image.fromarray(f) for f in frames]
    # optimize=True was the actual root cause, not the duration format --
    # confirmed directly: it silently MERGES near-identical consecutive
    # frames (common here, many settle/hold phases) and corrupts the
    # duration of the merged frames to a large bogus value in this Pillow
    # version (12.3.0), independent of whether duration is a list or a
    # constant. optimize=False keeps every frame and its real duration.
    imgs[0].save(args.out, save_all=True, append_images=imgs[1:], duration=FRAME_MS, loop=0, optimize=False)
    print(f"{args.out}: {len(imgs)} frames, ~{len(imgs)*FRAME_MS/1000:.1f}s")
raise SystemExit  # everything below is the old hand-built pipeline, kept for reference only


print("Fully extending the rear legs (a firm, braced base to pull against -- "
      "not just un-crouching, a real plant-and-push stance)...")
extend_targets = hold_targets.copy()
extend_targets[RB_HIP] += np.deg2rad(35)    # undo the -15deg weight-shift + stand up tall
extend_targets[LB_HIP] += np.deg2rad(35)
extend_targets[RB_KNEE] += np.deg2rad(20)   # straighten -- confirmed direction: +20deg held body
extend_targets[LB_KNEE] += np.deg2rad(20)   # height better than -20deg in isolation testing
for st in range(30):
    frac = (st + 1) / 30
    lt = hold_targets * (1 - frac) + extend_targets * frac
    ik_fl = p.calculateInverseKinematics(rid, PAW_LF, fl_anchor)
    ik_fr = p.calculateInverseKinematics(rid, PAW_RF, fr_anchor)
    lt[FL_SHOULDER], lt[FL_KNEE] = ik_fl[FL_SHOULDER], ik_fl[FL_KNEE]
    lt[FR_SHOULDER], lt[FR_KNEE] = ik_fr[FR_SHOULDER], ik_fr[FR_KNEE]
    f = np.ones(8) * 1.0
    f[FL_SHOULDER] = f[FL_KNEE] = f[FR_SHOULDER] = f[FR_KNEE] = ANCHOR_FORCE
    for _wait in range(6):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, lt, forces=f.tolist())
        sim_step()
hold_targets = extend_targets.copy()
ik_fl = p.calculateInverseKinematics(rid, PAW_LF, fl_anchor)
ik_fr = p.calculateInverseKinematics(rid, PAW_RF, fr_anchor)
hold_targets[FL_SHOULDER], hold_targets[FL_KNEE] = ik_fl[FL_SHOULDER], ik_fl[FL_KNEE]
hold_targets[FR_SHOULDER], hold_targets[FR_KNEE] = ik_fr[FR_SHOULDER], ik_fr[FR_KNEE]
print(f"  extended: body_x={p.getBasePositionAndOrientation(rid)[0][0]:.4f}, tilt={tilt():.1f}")

print("Both front feet secured. Pulling the body forward (front legs retract, "
      "feet held by real friction -- not pushed from the rear)...")
# The rear-leg-push version (kept above in git history / the log) failed:
# holding both front feet RIGIDLY fixed via continuous IK is an active,
# always-corrected constraint, not a passive resting contact -- the body
# physically cannot translate past what that double-anchor's own reach
# envelope allows. Real climbing mechanics pull the body TOWARD an already
# -planted limb by retracting it (like a pull-up), relying on real static
# friction to hold the foot, not a puppet-string IK lock. Verified directly
# earlier this session: increasing knee flexion (more negative FL_KNEE/
# FR_KNEE) while the foot has real contact is what produced clean lift.


def _foot_slipped(paw_link, anchor_pos, tol=0.01):
    cur = p.getLinkState(rid, paw_link)[0]
    return np.hypot(cur[0] - anchor_pos[0], cur[1] - anchor_pos[1]) > tol


def _step_force(base=1.0):
    f = np.ones(8) * base
    f[FL_SHOULDER] = f[FL_KNEE] = f[FR_SHOULDER] = f[FR_KNEE] = ANCHOR_FORCE
    return f.tolist()


def _with_front_ik(tgt, fl_pos, fr_pos):
    ik_fl = p.calculateInverseKinematics(rid, PAW_LF, fl_pos)
    ik_fr = p.calculateInverseKinematics(rid, PAW_RF, fr_pos)
    tgt[FL_SHOULDER], tgt[FL_KNEE] = ik_fl[FL_SHOULDER], ik_fl[FL_KNEE]
    tgt[FR_SHOULDER], tgt[FR_KNEE] = ik_fr[FR_SHOULDER], ik_fr[FR_KNEE]
    return tgt


PULL_DEG_PER_CYCLE = 12
N_PULL_CYCLES = 6
STEP_FORCE = _step_force(1.0)

if not args.skip_pull_step:
    print("Stage A: front legs pull the body forward, rear legs held firmly "
          "extended as a fixed brace (not stepping yet)...")
    for cyc in range(N_PULL_CYCLES):
        lt = hold_targets.copy()
        for st in range(15):
            frac = (st + 1) / 15
            lt = hold_targets.copy()
            lt[FL_KNEE] = hold_targets[FL_KNEE] - np.deg2rad(PULL_DEG_PER_CYCLE) * frac
            lt[FR_KNEE] = hold_targets[FR_KNEE] - np.deg2rad(PULL_DEG_PER_CYCLE) * frac
            for _wait in range(8):
                p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, lt, forces=STEP_FORCE)
                sim_step()
        hold_targets = lt
        # re-anchor to wherever the foot actually ended up (not the original
        # probe point) -- forcing it back after a successful pull would
        # itself be a jerky snap-back, undoing the progress just made.
        fl_anchor = p.getLinkState(rid, PAW_LF)[0]
        fr_anchor = p.getLinkState(rid, PAW_RF)[0]
        fl_slip = _foot_slipped(PAW_LF, fl_anchor)
        fr_slip = _foot_slipped(PAW_RF, fr_anchor)
        bx = p.getBasePositionAndOrientation(rid)[0][0]
        print(f"  pull {cyc}: body_x={bx:.4f}, tilt={tilt():.1f}, FL_slip={fl_slip}, FR_slip={fr_slip}")
        bo = p.getBasePositionAndOrientation(rid)[1]
        if max(abs(x) for x in p.getEulerFromQuaternion(bo)[0:2]) > 68.8 * np.pi / 180:
            print("FLIPPED during pull phase -- aborting")
            if args.out and frames:
                for _ in range(15):
                    _snap()
            env.close()
            raise SystemExit

    print("Stage B: now that the pull has drawn the body closer, step the "
          "rear legs forward toward the ledge lip...")
    for hip_idx, knee_idx, label in [(RB_HIP, RB_KNEE, "RB"), (LB_HIP, LB_KNEE, "LB")]:
        lt = hold_targets.copy()
        for st in range(12):
            frac = (st + 1) / 12
            lt = hold_targets.copy()
            lt[knee_idx] = hold_targets[knee_idx] - np.deg2rad(30) * frac
            tgt = _with_front_ik(lt.copy(), fl_anchor, fr_anchor)
            for _wait in range(8):
                p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=STEP_FORCE)
                sim_step()
        for st in range(12):
            frac = (st + 1) / 12
            lt2 = lt.copy()
            lt2[hip_idx] = lt[hip_idx] - np.deg2rad(20) * frac
            tgt = _with_front_ik(lt2.copy(), fl_anchor, fr_anchor)
            for _wait in range(8):
                p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=STEP_FORCE)
                sim_step()
        lt3 = lt2.copy()
        lt3[knee_idx] = hold_targets[knee_idx]
        for _wait in range(12):
            tgt = _with_front_ik(lt3.copy(), fl_anchor, fr_anchor)
            p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=STEP_FORCE)
            sim_step()
        hold_targets = _with_front_ik(lt3.copy(), fl_anchor, fr_anchor)
        bx = p.getBasePositionAndOrientation(rid)[0][0]
        print(f"  step {label}: body_x={bx:.4f}, tilt={tilt():.1f}")
        bo = p.getBasePositionAndOrientation(rid)[1]
        if max(abs(x) for x in p.getEulerFromQuaternion(bo)[0:2]) > 68.8 * np.pi / 180:
            print("FLIPPED after rear step -- aborting")
            if args.out and frames:
                for _ in range(15):
                    _snap()
            env.close()
            raise SystemExit

bx_final = p.getBasePositionAndOrientation(rid)[0][0]
print(f"Pull-and-step done: body_x={bx_final:.4f}, tilt={tilt():.1f}")

# --- Real cmh push-off commit, from the now-properly-secured front feet ---
# FK-traced the tail (ticks 160-171) directly: the rear legs extend
# explosively BACKWARD (relative to body) during 166-168, not a step-up --
# a genuine push-off/launch, not quasi-static walking. climb_env.py defines
# PUSH_FORCE=6.5 for exactly this ("rear legs get this during the PUSH
# phases -- more lift onto the ledge") but never actually wires it into
# step() (grepped: defined, never referenced) -- so no test all day,
# including the original Phase F runs, ever actually used it. Testing now.
print("Blending into the real cmh commit sequence (front feet already secured)...")
commit_ready_tick = 165
PUSH_FORCE = 6.5
FRONT_FORCE = ANCHOR_FORCE   # keep using the SAME front-leg holding force throughout, no jump
REAR_JOINTS_IDX = [RB_HIP, RB_KNEE, LB_HIP, LB_KNEE]
FRONT_JOINTS_IDX = [FL_SHOULDER, FL_KNEE, FR_SHOULDER, FR_KNEE]


def _commit_force(rear_scale):
    # ramp the rear legs' force from the walking-phase level up to PUSH_FORCE
    # gradually (rear_scale 0->1) instead of jumping straight to 6.5, and
    # hold the front legs at one constant value throughout.
    f = np.ones(8) * 3.2
    for idx in REAR_JOINTS_IDX:
        f[idx] = 1.0 + rear_scale * (PUSH_FORCE - 1.0)
    for idx in FRONT_JOINTS_IDX:
        f[idx] = FRONT_FORCE
    return f.tolist()


# No forced blend into cmh's literal tick-165 pose: that pose's REAR-leg
# angles assume the un-extended stance cmh's own reset produces, which no
# longer matches our fully-extended rear brace -- forcing it caused the
# same kind of drag the front-leg fix just solved, just for the rear legs
# this time. Just settle wherever Stage A/B actually left the robot, then
# let the push loop's own targets (starting at tick 166) pull the rear legs
# into the real push-off motion directly -- position control already
# smooths that transition over FRAME_SKIP steps, no explicit blend needed.
for s in range(40):
    p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, hold_targets, forces=_commit_force(0.0))
    sim_step()
    bo = p.getBaseVelocity(rid)
    if s > 15 and np.linalg.norm(bo[0]) < 0.02 and np.linalg.norm(bo[1]) < 0.15:
        break
print(f"  ready for commit: body_x={p.getBasePositionAndOrientation(rid)[0][0]:.4f}, tilt={tilt():.1f}")

# Push phase: only the REAR legs follow cmh's own raw trajectory (that's the
# real, novel push-off motion) -- the FRONT legs stay IK-anchored to their
# verified position throughout instead of also snapping to cmh's hardcoded
# absolute angles (30deg/65deg etc), which have nothing to do with where
# THIS body actually found real contact. That mismatch was quietly yanking
# the front feet off their secure spot during every previous test today.
n_push_ticks = len(CLIMB_POSE_SEQ) - (commit_ready_tick + 1)
flipped = False
for ti, t in enumerate(range(commit_ready_tick + 1, len(CLIMB_POSE_SEQ))):
    tgt = _with_front_ik(CLIMB_POSE_SEQ[t].copy(), fl_anchor, fr_anchor)
    f = _commit_force(min(1.0, (ti + 1) / 3))   # ramp to full push force over the first 3 ticks
    for _ in range(4):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, tgt, forces=f)
        sim_step()
    tl = tilt()
    bx = p.getBasePositionAndOrientation(rid)[0][0]
    print(f"  push tick {t}: body_x={bx:.4f}, tilt={tl:.1f}")
    if tl > 68.8:
        print(f"FLIPPED during push commit at tick {t}")
        flipped = True
        break
if not flipped:
    final_tgt = _with_front_ik(CLIMB_POSE_SEQ[-1].copy(), fl_anchor, fr_anchor)
    for _ in range(60):
        p.setJointMotorControlArray(rid, env.joint_id, p.POSITION_CONTROL, final_tgt, forces=_commit_force(1.0))
        sim_step()
    paws = [p.getLinkState(rid, j)[0] for j in CLIMB_PAW_LINKS]
    on_top = sum(1 for (px, py, pz) in paws if pz > platform_top_z - 0.02 and px > EDGE_X - 0.02)
    bx = p.getBasePositionAndOrientation(rid)[0][0]
    print(f"PUSH-COMMIT DONE: {on_top}/4 paws on-top, body_x={bx:.4f}, tilt={tilt():.1f}")

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
