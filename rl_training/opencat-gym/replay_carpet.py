"""Carpet sim dial-in (user 2026-10-20): replay the joint commands of REAL carpet walks through the sim under a grid of carpet and body settings and score how well the sim
reproduces what the real body did (roll trace on the IMU's fresh 5 Hz frames, and the time it tipped past 45 deg). Open loop: the logged joint commands are the commands the
hardware controller produced, so any difference in the body's motion is physics, not policy.

usage (cwd = rl_training/opencat-gym):
  python replay_carpet.py LOGDIR [--grid K=80/120,DEPTH=0.0088/0.012,MU=1.0/2.2,MOTOR_FORCE=0.10/0.15,DY=-0.008/0] [--c 2] [--jobs 4] [--json-out X]
Grid names: K, C, DEPTH, MU (the pad), MOTOR_FORCE (servo strength), DY / DZ (pod centre sideways / up, m), any other name is an env module constant.
Logs with no joint commands (firmware-skill logs) are skipped."""
import argparse
import glob
import itertools
import json
import multiprocessing as mp
import os
import sys

import numpy as np

sys.path.insert(0, os.getcwd())
PAD = {"K": "CARPET_PAD_K", "C": "CARPET_PAD_C", "DEPTH": "CARPET_PAD_DEPTH", "MU": "CARPET_PAD_MU"}
TILT_DEG = 45.0


def real_series(log):
    """The IMU's fresh frames: index, roll (+ = right side down, as the sim), pitch, in degrees."""
    held = np.r_[True, (np.diff(log["roll"]) != 0) | (np.diff(log["pitch"]) != 0)]
    idx = np.nonzero(held)[0]
    return idx, -np.degrees(log["roll"][idx] - log["roll"][0]), np.degrees(log["pitch"][idx] - log["pitch"][0])


def first_over(t, roll, pitch):
    tilt = np.maximum(np.abs(roll), np.abs(pitch))
    over = np.nonzero(tilt > TILT_DEG)[0]
    return float(t[over[0]]) if len(over) else None


def replay(job):
    path, ov = job
    import real2sim as R
    import g2_profile
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    g2_profile.set_environ(g2_profile.scoring_env())
    import pybullet as p
    import opencat_gym_env as E
    E.GUI_MODE = False
    for k in ("RANDOM_MASS", "RANDOM_FRICTION", "RANDOM_PUSH", "IMPULSE_PUSH", "JOINT_OFFSET_DEG", "RANDOM_GYRO", "IMU_BIAS_DEG", "TORQUE_CUTBACK",
              "PAYLOAD_MASS_RAND", "HEAD_MASS_RAND", "REAR_MASS_RAND", "PAYLOAD_JITTER_XY", "CMD_PATH_EXTRA_MS_MAX", "RANDOM_JOINT_ANGS"):
        setattr(E, k, 0.0)
    E.CATEGORY_OVERRIDE = {"terrain": 0.0}
    E.CARPET_PAD_K, E.CARPET_PAD_C, E.CARPET_PAD_DEPTH, E.CARPET_PAD_MU = 0.0, 0.0, 0.0064, 1.0
    dy = dz = 0.0
    for k, v in ov.items():
        if k in PAD:
            setattr(E, PAD[k], v)
        elif k == "DY":
            dy = v
        elif k == "DZ":
            dz = v
        else:
            setattr(E, k, v)
    if dy or dz:
        E.PAYLOAD_POS = (E.PAYLOAD_POS[0], E.PAYLOAD_POS[1] + dy, E.PAYLOAD_POS[2] + dz)
    log = R.load_log(path)
    env = E.OpenCatGymEnv()
    env.set_ramp_steps(1e12)
    env.set_command(fwd=0.10, yaw=0.0)
    np.random.seed(0)
    env.reset()
    e0 = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])
    sim_r, sim_p = [], []
    ended = None                                                  # the sim ended the replay early (it judged G2 fallen): that is a tip at this step
    for i_step, j in enumerate(log["j"]):
        env._abs_joint_override = j
        _o, _r, te, _tr, _i = env.step(np.zeros(8))
        e = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])
        sim_r.append(np.degrees(e[0] - e0[0]))
        sim_p.append(np.degrees(e[1] - e0[1]))
        if te:
            ended = float(log["t"][i_step])
            break
    env.close()
    n = len(sim_r)
    idx, real_r, real_p = real_series(log)
    t_real = first_over(log["t"][idx], real_r, real_p)            # from the FULL real log, whatever the sim did
    keep = idx < n
    idx, real_r, real_p = idx[keep], real_r[keep], real_p[keep]
    t = log["t"][idx]
    sr, sp = np.array(sim_r)[idx], np.array(sim_p)[idx]
    t_sim = first_over(t, sr, -sp)                               # the sim pitch is nose-down +; the log's is the opposite sign
    if ended is not None and (t_sim is None or ended < t_sim):
        t_sim = ended
    if len(t) < 2:
        return dict(path=os.path.basename(path), ov=ov, rms=90.0, t_real=t_real, t_sim=t_sim, real_peak=0.0, sim_peak=0.0, real_side=0.0, sim_side=0.0)
    window = t <= (t_real + 0.2 if t_real else t[-1])
    if window.sum() < 2:
        window = np.ones_like(t, dtype=bool)
    rms = float(np.sqrt(np.mean((sr[window] - real_r[window]) ** 2)))
    return dict(path=os.path.basename(path), ov=ov, rms=rms, t_real=t_real, t_sim=t_sim, real_peak=float(np.abs(real_r[window]).max()),
                sim_peak=float(np.abs(sr[window]).max()), real_side=float(np.sign(real_r[np.argmax(np.abs(real_r))])), sim_side=float(np.sign(sr[np.argmax(np.abs(sr))])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logdir")
    ap.add_argument("--grid", default="K=80/120/250,DEPTH=0.0088/0.012,MU=1.0/1.5/2.2,MOTOR_FORCE=0.10/0.15,DY=-0.008/0")
    ap.add_argument("--c", type=float, default=2.0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--json-out", default="")
    a = ap.parse_args()
    logs = []
    for f in sorted(glob.glob(os.path.join(a.logdir, "*.csv"))):
        head = next((l for l in open(f) if l.strip() and not l.startswith("#")), "")
        if "j0" in head.split(","):
            logs.append(f)
    names, vals = [], []
    for kv in a.grid.split(","):
        n, v = kv.split("=")
        names.append(n)
        vals.append([float(x) for x in v.split("/")])
    points = [dict(zip(names, combo), C=a.c) for combo in itertools.product(*vals)]
    jobs = [(l, ov) for ov in points for l in logs]
    print(f"{len(logs)} logs x {len(points)} settings = {len(jobs)} replays", flush=True)
    with mp.get_context("spawn").Pool(a.jobs, maxtasksperchild=1) as pool:
        res = pool.map(replay, jobs)
    rows = []
    for ov in points:
        rr = [r for r in res if r["ov"] == ov]
        td = [abs(r["t_sim"] - r["t_real"]) if r["t_real"] and r["t_sim"] else (1.5 if r["t_real"] else 0.0) for r in rr]      # a missed or invented tip counts 1.5 s
        side = np.mean([r["real_side"] == r["sim_side"] for r in rr if r["t_real"]]) if any(r["t_real"] for r in rr) else 1.0
        rows.append(dict(ov=ov, rms=float(np.mean([r["rms"] for r in rr])), tip_err=float(np.mean(td)), side_ok=float(side),
                         tipped=int(sum(1 for r in rr if r["t_sim"])), n=len(rr)))
    rows.sort(key=lambda r: r["rms"] + 5.0 * r["tip_err"] - 5.0 * r["side_ok"])
    for r in rows[:15]:
        print(f"  {r['ov']}: roll rms {r['rms']:5.1f} deg  tip-time err {r['tip_err']:.2f} s  side ok {r['side_ok']:.2f}  sim tipped {r['tipped']}/{r['n']}")
    real_tipped = sum(1 for r in res if r["ov"] == points[0] and r["t_real"])
    print(f"real tipped {real_tipped}/{len(logs)} logs")
    if a.json_out:
        json.dump(dict(rows=rows, per_log=res), open(a.json_out, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
