"""Sim-to-real gap: replay a real robot log's joint commands OPEN-LOOP in a
minimal pybullet sim and diff the body-tilt / angular-rate trajectories against
the real IMU. No policy, no joint feedback needed -- just the commands (logged)
and the IMU (logged).

    # from a calibration run
    python sysid_replay.py --log sysid_20260918.csv
    # from an H1 walk
    python sysid_replay.py --log run_rl_C1_1.csv
    # find the sim actuator params that best match reality
    python sysid_replay.py --log sysid_20260918.csv --fit

Log format (from run_gait.py --log or pi_pipeline/gait/sysid_collect.py):
    t,roll,pitch,yaw,gx,gy,gz,j0,j1,j2,j3,j4,j5,j6,j7[,phase]
    angles/rates in RADIANS, joints in DEGREES, URDF order.

The sim here mirrors opencat_gym_env's physics: models/bittle_esp32.urdf,
g=-9.81, 240 Hz, POSITION_CONTROL, a welded 75 g rear payload. What --fit
sweeps: motor maxForce, position gain, velocity gain, and a command-latency in
control steps. Output: the corrected values + how to put them in the env.
"""
import argparse
import itertools
import os
import sys

import numpy as np
import pybullet as p
import pybullet_data

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
PAYLOAD_MASS = 0.075
PAYLOAD_POS = (-0.020, 0.0, 0.025)
SUBSTEP_HZ = 240.0


def load_log(path):
    hdr = None
    rows = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if hdr is None:
                hdr = ln.split(",")
                continue
            rows.append(ln.split(","))
    cols = {name: i for i, name in enumerate(hdr)}
    t = np.array([float(r[cols["t"]]) for r in rows])
    rp = np.array([[float(r[cols["roll"]]), float(r[cols["pitch"]])] for r in rows])
    gyro = np.array([[float(r[cols["gx"]]), float(r[cols["gy"]])] for r in rows])
    jd = np.array([[float(r[cols[f"j{k}"]]) for k in range(8)] for r in rows])
    phase = ([r[cols["phase"]] for r in rows] if "phase" in cols else [""] * len(rows))
    return t, rp, gyro, jd, phase


def build_sim(gui=False):
    cid = p.connect(p.GUI if gui else p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setGravity(0, 0, -9.81)
    p.setTimeStep(1.0 / SUBSTEP_HZ)
    p.loadURDF("plane.urdf")
    rid = p.loadURDF("models/bittle_esp32.urdf", [0, 0, 0.08], [0, 0, 0, 1],
                     flags=p.URDF_USE_SELF_COLLISION)
    jids = [j for j in range(p.getNumJoints(rid))
            if p.getJointInfo(rid, j)[2] in (p.JOINT_REVOLUTE, p.JOINT_PRISMATIC)]
    pl = p.createMultiBody(baseMass=PAYLOAD_MASS, baseCollisionShapeIndex=-1,
                           basePosition=[PAYLOAD_POS[0], PAYLOAD_POS[1], 0.08 + PAYLOAD_POS[2]])
    c = p.createConstraint(rid, -1, pl, -1, p.JOINT_FIXED, [0, 0, 0], list(PAYLOAD_POS), [0, 0, 0])
    p.changeConstraint(c, maxForce=5e3)
    return cid, rid, jids


def replay(t, jd_deg, jids, rid, max_force, kp, kd, latency):
    """Feed the recorded joint targets open-loop; return sim (roll,pitch) and
    (gx,gy) sampled at each log row."""
    jr = np.deg2rad(jd_deg)
    # reset the body + joints to a clean start (fit calls this many times)
    p.resetBasePositionAndOrientation(rid, [0, 0, 0.08], [0, 0, 0, 1])
    p.resetBaseVelocity(rid, [0, 0, 0], [0, 0, 0])
    for k, j in enumerate(jids):
        p.resetJointState(rid, j, float(jr[0][k]))
    # settle at the first commanded pose
    for _ in range(120):
        p.setJointMotorControlArray(rid, jids, p.POSITION_CONTROL, jr[0],
                                    forces=[max_force] * 8,
                                    positionGains=[kp] * 8, velocityGains=[kd] * 8)
        p.stepSimulation()
    buf = [jr[0]] * max(1, latency + 1)
    sim_rp = np.empty((len(t), 2))
    sim_g = np.empty((len(t), 2))
    prev = t[0]
    for i in range(len(t)):
        buf.append(jr[i])
        tgt = buf.pop(0)
        nsub = 1 if i == 0 else max(1, int(round((t[i] - prev) * SUBSTEP_HZ)))
        prev = t[i]
        for _ in range(min(nsub, 24)):
            p.setJointMotorControlArray(rid, jids, p.POSITION_CONTROL, tgt,
                                        forces=[max_force] * 8,
                                        positionGains=[kp] * 8, velocityGains=[kd] * 8)
            p.stepSimulation()
        _, quat = p.getBasePositionAndOrientation(rid)
        e = p.getEulerFromQuaternion(quat)
        w = p.getBaseVelocity(rid)[1]
        sim_rp[i] = (e[0], e[1])
        sim_g[i] = (w[0], w[1])
    return sim_rp, sim_g


def gap(real_rp, real_g, sim_rp, sim_g, align=True):
    """RMS tilt + rate gap. If align, subtract per-axis means first (removes a
    static IMU-vs-sim frame offset) and report what was removed."""
    off = np.zeros(2)
    if align:
        off = np.mean(real_rp - sim_rp, axis=0)
        real_rp = real_rp - off
    tilt_rms = float(np.sqrt(np.mean((real_rp - sim_rp) ** 2)))
    rate_rms = float(np.sqrt(np.mean((real_g - sim_g) ** 2)))
    return tilt_rms, rate_rms, off


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--max-force", type=float, default=0.20)   # env default
    ap.add_argument("--kp", type=float, default=0.1)
    ap.add_argument("--kd", type=float, default=1.0)
    ap.add_argument("--latency", type=int, default=0)
    ap.add_argument("--no-align", action="store_true")
    args = ap.parse_args()

    t, real_rp, real_g, jd, phase = load_log(args.log)
    print(f"log: {len(t)} rows, {t[-1]-t[0]:.1f} s"
          + (f", phases: {sorted(set(phase))}" if any(phase) else ""))

    _cid, rid, jids = build_sim()

    def eval_params(mf, kp, kd, lat):
        srp, sg = replay(t, jd, jids, rid, mf, kp, kd, lat)
        return gap(real_rp, real_g, srp, sg, align=not args.no_align), (srp, sg)

    base = eval_params(args.max_force, args.kp, args.kd, args.latency)
    (t0, r0, off0), _ = base
    print(f"\nbaseline (env params: max_force={args.max_force}, kp={args.kp}, kd={args.kd}, "
          f"latency={args.latency}):")
    print(f"  tilt gap  {np.degrees(t0):.2f} deg RMS")
    print(f"  rate gap  {r0:.3f} rad/s RMS")
    print(f"  frame offset removed (roll,pitch): {np.degrees(off0).round(2).tolist()} deg  "
          f"{'<- large: IMU axis/sign mismatch, check parse_imu_line' if np.abs(off0).max() > 0.15 else ''}")

    if not args.fit:
        return

    print("\nfitting (coordinate descent)...")
    grids = {
        "mf":  [0.10, 0.15, 0.20, 0.28, 0.40, 0.60],
        "kp":  [0.03, 0.06, 0.1, 0.2, 0.4],
        "kd":  [0.2, 0.5, 1.0, 2.0],
        "lat": [0, 1, 2, 3, 4],
    }
    best = dict(mf=args.max_force, kp=args.kp, kd=args.kd, lat=args.latency)
    best_cost = np.degrees(t0) + 30 * r0
    for _round in range(2):
        for key, vals in grids.items():
            for v in vals:
                trial = dict(best); trial[key] = v
                (tr, rr, _), _ = eval_params(trial["mf"], trial["kp"], trial["kd"], trial["lat"])
                cost = np.degrees(tr) + 30 * rr
                if cost < best_cost - 1e-6:
                    best_cost, best = cost, trial
    (tf, rf, offf), _ = eval_params(best["mf"], best["kp"], best["kd"], best["lat"])
    improved = (np.degrees(t0) - np.degrees(tf) > 0.15) or (r0 - rf > 0.005)
    if not improved:
        print(f"\nno meaningful improvement -- the env's current params already fit this log "
              f"(tilt gap stays {np.degrees(t0):.2f} deg RMS). "
              f"{'The gap is small; sim matches reality here.' if np.degrees(t0) < 1.0 else 'The residual gap is not explained by these 4 params -- look at friction, CoM, IMU frame.'}")
        return
    print(f"\nbest: max_force={best['mf']}, kp={best['kp']}, kd={best['kd']}, latency={best['lat']}")
    print(f"  tilt gap  {np.degrees(t0):.2f} -> {np.degrees(tf):.2f} deg RMS")
    print(f"  rate gap  {r0:.3f} -> {rf:.3f} rad/s RMS")
    print("\napply to opencat_gym_env.py:")
    print(f"  - motor forces:  forces=np.ones(8)*{best['mf']:.3f}*self._torque_scale   (was 0.2)")
    if abs(best["kp"] - 0.1) > 1e-6 or abs(best["kd"] - 1.0) > 1e-6:
        print(f"  - add gains to setJointMotorControlArray: positionGains=[{best['kp']}]*8, "
              f"velocityGains=[{best['kd']}]*8")
    if best["lat"] > 0:
        print(f"  - CMD_LATENCY_STEPS = {best['lat']}   (already a knob; default 0)")
    print("\nThen re-run the H1 walk and validate_deploy; retrain if H1 was a 'middle' result.")


if __name__ == "__main__":
    main()
