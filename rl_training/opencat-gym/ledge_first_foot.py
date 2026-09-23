"""Get ONE front foot on top of a step-up ledge, using only what G2 can sense.

Step 1 of the proprioceptive climb (2026-09-22). Sequence:

  1. walk blind into the ledge (learned gait, G2's real `i` command path)
     until pinned against the riser -- no ledge position is given to G2
  2. stop, then back up a set distance (timed backward walk)
  3. settle into Petoi's `cmh` reach pose, shift weight back onto the rear legs
  4. lift the front-left paw, reach forward-and-up to a body-frame target
  5. lower it slowly; contact = the joint stops following its command
     (commanded vs actual knee angle, read at FEEDBACK_HZ like servo feedback)

Rules: every decision uses only joint angles (servo feedback) and body
orientation (IMU) plus G2's own leg geometry. Body-frame targets are turned
into motor targets with the robot's own kinematics -- on hardware that is
forward kinematics from the joint angles plus IMU pitch, no external
position. Sim ground truth (contact points, ledge position) GRADES the
result only. All motor forces are capped at the P1S servo's ~0.29 N*m.

    python ledge_first_foot.py --seed 7000 --out trained/first_foot.gif
    python ledge_first_foot.py --seeds 7000,7002,7003,7005,7006
"""
import argparse

import numpy as np
import pybullet as p

import opencat_gym_env as E
E.GUI_MODE = False
E.DR_EVAL_FULL = True
E.DEPLOY_DEBUG = True
import benchmark_decathlon as B
B._EXTRA_DR = "clean"
from climb_env import _BASE as CMH

FL_SH, FL_KN = 0, 1
RB_HIP, LB_HIP = 4, 6
PAW_LF = 3
EDGE_X = 0.11          # GRADING ONLY
TORQUE_CAP = 0.29      # P1S peak, N*m
CMH_REACH_FRAME = 20

ap = argparse.ArgumentParser()
ap.add_argument("--checkpoint", default="trained/run20m_resid30_ppo")
ap.add_argument("--ledge-h", type=float, default=0.025)
ap.add_argument("--seeds", default="7000")
ap.add_argument("--seed", type=int, default=None)
ap.add_argument("--walk-s", type=float, default=4.0, help="blind walk time (long enough to pin against the riser)")
ap.add_argument("--backup-mm", type=float, default=30.0)
ap.add_argument("--backup-cmd", type=float, default=-0.06)
ap.add_argument("--shift-deg", type=float, default=15.0, help="rear-hip weight shift before lifting")
ap.add_argument("--reach-fwd-mm", type=float, default=55.0, help="paw target ahead of its resting spot (body frame)")
ap.add_argument("--reach-up-mm", type=float, default=45.0, help="paw target above its resting height, for the reach")
ap.add_argument("--search-mm-per-read", type=float, default=1.5)
ap.add_argument("--feedback-hz", type=float, default=10.0)
ap.add_argument("--contact-deg", type=float, default=3.0, help="knee lag behind command that means 'touching'")
ap.add_argument("--probe-force", type=float, default=0.12)
ap.add_argument("--out", default=None)
args = ap.parse_args()
SEEDS = [args.seed] if args.seed is not None else [int(s) for s in args.seeds.split(",")]

frames = []


def snap(env, label):
    if not args.out:
        return
    from PIL import Image, ImageDraw
    pos = p.getBasePositionAndOrientation(env.robot_id)[0]
    w, h = 480, 360
    _, _, rgb, _, _ = p.getCameraImage(
        w, h, viewMatrix=p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[pos[0] + 0.04, pos[1], 0.04], distance=0.38,
            yaw=60, pitch=-15, roll=0, upAxisIndex=2),
        projectionMatrix=p.computeProjectionMatrixFOV(55, w / h, 0.05, 5),
        renderer=p.ER_TINY_RENDERER)
    im = Image.fromarray(np.reshape(rgb, (h, w, 4))[:, :, :3].astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.rectangle([0, h - 22, w, h], fill=(20, 24, 23))
    d.text((6, h - 17), label, fill=(235, 240, 238))
    frames.append(im)


def joints(env):
    return np.array([s[0] for s in p.getJointStates(env.robot_id, env.joint_id)])


def drive(env, tgt, forces, steps, label=None, every=8):
    for k in range(steps):
        p.setJointMotorControlArray(env.robot_id, env.joint_id, p.POSITION_CONTROL, list(tgt),
                                    forces=list(np.minimum(forces, TORQUE_CAP)))
        p.stepSimulation()
        if label and k % every == 0:
            snap(env, label)


def body_to_world(env, v_body):
    _, orn = p.getBasePositionAndOrientation(env.robot_id)
    return np.array(p.getMatrixFromQuaternion(orn)).reshape(3, 3) @ np.asarray(v_body)


def ik_fl(env, paw_world, cur):
    ik = p.calculateInverseKinematics(env.robot_id, PAW_LF, list(paw_world))
    t = cur.copy()
    t[FL_SH], t[FL_KN] = ik[FL_SH], ik[FL_KN]
    return t


def run(seed, model):
    B._apply({"LEDGE_HEIGHT": args.ledge_h, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1})
    E.ADAPTIVE_PUSH = False
    E.EPISODE_LENGTH = 100000
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"
    env = E.OpenCatGymEnv()
    np.random.seed(seed)
    obs, _ = env.reset()
    rid = env.robot_id

    # 1. blind walk into the ledge
    env.set_command(fwd=0.10, yaw=0.0)
    for k in range(int(args.walk_s * 80)):
        a, _ = model.predict(obs, deterministic=True)
        obs, _, term, _, _ = env.step(a)
        if k % 4 == 0:
            snap(env, "1. walking blind into the ledge")
        if term:
            return dict(seed=seed, ok=False, why="fell while walking into the ledge"), env
    # 2. stop, back up a set distance (timed; speed calibrated in sim below)
    env.set_command(fwd=0.0, yaw=0.0)
    for k in range(60):
        a, _ = model.predict(obs, deterministic=True)
        obs, _, term, _, _ = env.step(a)
        if k % 4 == 0:
            snap(env, "2. stop")
    x0 = p.getBasePositionAndOrientation(rid)[0][0]
    env.set_command(fwd=args.backup_cmd, yaw=0.0)
    backup_s = (args.backup_mm / 1000) / (BACKUP_SPEED or abs(args.backup_cmd))
    for k in range(int(backup_s * 80)):
        a, _ = model.predict(obs, deterministic=True)
        obs, _, term, _, _ = env.step(a)
        if k % 4 == 0:
            snap(env, f"2. backing up {args.backup_mm:.0f} mm")
        if term:
            return dict(seed=seed, ok=False, why="fell backing up"), env
    env.set_command(fwd=0.0, yaw=0.0)
    for k in range(40):
        a, _ = model.predict(obs, deterministic=True)
        obs, _, term, _, _ = env.step(a)
    backed = (x0 - p.getBasePositionAndOrientation(rid)[0][0]) * 1000
    E.CMD_PATH = ""   # from here on the probe drives joints directly (slow motion)

    # 3. cmh reach pose, then weight shift back
    cur = joints(env)
    pose = np.array(CMH[CMH_REACH_FRAME])
    for st in range(40):
        f = (st + 1) / 40
        drive(env, cur * (1 - f) + pose * f, [TORQUE_CAP] * 8, 5, "3. climb reach pose")
    drive(env, pose, [TORQUE_CAP] * 8, 60, "3. climb reach pose")
    hold = pose.copy()
    for st in range(30):
        f = (st + 1) / 30
        t = hold.copy()
        t[RB_HIP] -= np.deg2rad(args.shift_deg) * f
        t[LB_HIP] -= np.deg2rad(args.shift_deg) * f
        drive(env, t, [TORQUE_CAP] * 8, 4, "3. shifting weight back")
    hold = t.copy()

    # 4. lift + reach to a body-frame target relative to the paw's resting spot
    rest = np.array(p.getLinkState(rid, PAW_LF)[0])
    target = rest + body_to_world(env, [args.reach_fwd_mm / 1000, 0.0, 0.0]) + np.array([0, 0, args.reach_up_mm / 1000])
    lift = rest + np.array([0, 0, args.reach_up_mm / 1000])
    forces = np.full(8, TORQUE_CAP)
    for leg_target, n, label in ((lift, 30, "4. lifting the front-left paw"), (target, 50, "4. reaching forward")):
        start = np.array(p.getLinkState(rid, PAW_LF)[0])
        for st in range(n):
            f = (st + 1) / n
            t = ik_fl(env, start * (1 - f) + leg_target * f, hold)
            drive(env, t, forces, 6, label)
    hold = ik_fl(env, target, hold)
    tilt_after_reach = np.degrees(max(abs(v) for v in p.getEulerFromQuaternion(p.getBasePositionAndOrientation(rid)[1])[:2]))

    # 5. search down; contact = the knee stops following its command
    read_every = int(round(240 / args.feedback_hz))
    forces[FL_SH] = forces[FL_KN] = args.probe_force
    paw = target.copy()
    touched = None
    lag_hist = []
    for r in range(int(120 / args.search_mm_per_read)):
        paw = paw - np.array([0, 0, args.search_mm_per_read / 1000])
        t = ik_fl(env, paw, hold)
        drive(env, t, forces, read_every, "5. lowering the paw, feeling for the top")
        lag = abs(np.degrees(joints(env)[FL_KN] - t[FL_KN])) + abs(np.degrees(joints(env)[FL_SH] - t[FL_SH]))
        lag_hist.append(lag)
        if len(lag_hist) >= 2 and lag_hist[-1] > args.contact_deg and lag_hist[-2] > args.contact_deg:
            touched = r
            break
    drive(env, t, forces, 60, "5. contact -- holding" if touched is not None else "5. no contact")
    for _ in range(12):
        snap(env, "5. contact -- holding" if touched is not None else "5. no contact")

    # grade with ground truth
    pw = np.array(p.getLinkState(rid, PAW_LF)[0])
    cps = [c for c in p.getContactPoints(bodyA=rid, linkIndexA=PAW_LF) if c[2] != rid]
    on_top = bool(cps) and max(c[7][2] for c in cps) > 0.9 and pw[0] > EDGE_X + 0.005 and pw[2] > args.ledge_h
    tilt = np.degrees(max(abs(v) for v in p.getEulerFromQuaternion(p.getBasePositionAndOrientation(rid)[1])[:2]))
    return dict(seed=seed, ok=on_top, backed_mm=round(backed, 1), sensed_contact=touched is not None,
                paw_x_past_edge_mm=round((pw[0] - EDGE_X) * 1000, 1), paw_z_mm=round(pw[2] * 1000, 1),
                tilt=round(tilt, 1), tilt_after_reach=round(tilt_after_reach, 1),
                max_lag=round(max(lag_hist), 1) if lag_hist else None), env


BACKUP_SPEED = None


def main():
    global BACKUP_SPEED
    from stable_baselines3 import PPO
    model = PPO.load(args.checkpoint, device="cpu")
    results = []
    for s in SEEDS:
        r, env = run(s, model)
        env.close()
        for k, v in (("IMU_HOLD_STEPS", 0), ("IMU_RATE_ZERO", False), ("CMD_PATH", "")):
            setattr(E, k, v)
        results.append(r)
        print(r, flush=True)
    print(f"\nfoot on top: {sum(r['ok'] for r in results)}/{len(results)}")
    if args.out and frames:
        frames[0].save(args.out, save_all=True, append_images=frames[1:], duration=67, loop=0)
        print(args.out, len(frames), "frames")


if __name__ == "__main__":
    main()
