"""Ledge-bump study: what does a blind G2 feel when it walks into a step-up?

Step 1 of the proprioceptive climb (2026-09-22). The walk policy is blind, so
the first sign of a ledge is a front foot meeting the riser. This walks the
policy at a range of ledge heights through G2's real control path (firmware
`i` command model + stock 5 Hz IMU) and records, per height:

  - GRADED WITH SIM GROUND TRUTH (evaluation only, never a decision input):
    did the walk get both front paws onto the platform by itself.
  - WHAT G2 CAN SENSE: front-joint tracking error as servo feedback would
    report it (joint angles read at FEEDBACK_HZ, judged against the range the
    joint's commands swept over the last LAG_S -- the JamGuard comparison, so
    the firmware's ~55 ms lag isn't counted as error), and IMU pitch at 5 Hz.

A height of 0 is the flat-ground baseline the bump has to stand out from.

    python ledge_bump_study.py
    python ledge_bump_study.py --heights 0,0.02,0.035 --seeds 3 --seconds 8
"""
import argparse
import json
import os

import numpy as np
import pybullet as p

import opencat_gym_env as E
E.GUI_MODE = False
E.DR_EVAL_FULL = True
E.DEPLOY_DEBUG = True
import benchmark_decathlon as B
B._EXTRA_DR = "clean"

FRONT = (0, 1, 2, 3)                 # URDF: FL shoulder, FL knee, FR shoulder, FR knee
PAW_LF, PAW_RF = 3, 6
EDGE_X = 0.11                        # env's step-up edge -- used for GRADING only
FEEDBACK_HZ = 5.0
LAG_S = 0.12


def track_err(cmd_hist, fbk):
    """Per front joint: distance from feedback to the span of recent commands."""
    c = np.array(cmd_hist)                               # (n, 4)
    lo, hi = c.min(0), c.max(0)
    return np.where(fbk < lo, lo - fbk, np.where(fbk > hi, fbk - hi, 0.0))


def run(model, height, seed, seconds):
    B._apply({"LEDGE_HEIGHT": height, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1} if height > 0 else {})
    E.ADAPTIVE_PUSH = False
    E.EPISODE_LENGTH = int(seconds * 80) + 5
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"
    env = E.OpenCatGymEnv()
    np.random.seed(seed)
    obs, _ = env.reset()
    env.set_command(fwd=0.10, yaw=0.0)
    rid = env.robot_id
    every = int(round(80 / FEEDBACK_HZ))
    cmd_hist, rows = [], []
    fell = False
    for k in range(int(seconds * 80)):
        a, _ = model.predict(obs, deterministic=True)
        obs, _, term, trunc, _ = env.step(a)
        t = (k + 1) / 80
        cmd_hist.append(np.asarray(env._deploy_dbg["joint_deg"], float)[list(FRONT)])
        cmd_hist = cmd_hist[-int(LAG_S * 80) - 1:]
        if k % every == 0:
            js = np.rad2deg(np.array([s[0] for s in p.getJointStates(rid, env.joint_id)]))
            err = track_err(cmd_hist, js[list(FRONT)])
            pos, orn = p.getBasePositionAndOrientation(rid)
            pitch = np.rad2deg(p.getEulerFromQuaternion(orn)[1])
            lf, rf = p.getLinkState(rid, PAW_LF)[0], p.getLinkState(rid, PAW_RF)[0]
            rows.append(dict(t=round(t, 3), x=round(pos[0], 4), pitch=round(pitch, 2),
                             err=[round(float(e), 2) for e in err],
                             lf=[round(lf[0], 4), round(lf[2], 4)], rf=[round(rf[0], 4), round(rf[2], 4)]))
        if term:
            fell = True
            break
    env.close()
    for k in ("IMU_HOLD_STEPS", "IMU_RATE_ZERO", "CMD_PATH"):
        setattr(E, k, {"IMU_HOLD_STEPS": 0, "IMU_RATE_ZERO": False, "CMD_PATH": ""}[k])
    on_top = bool(height > 0 and rows and all(r[1] > height * 0.8 + 0.004 and r[0] > EDGE_X
                                               for r in (rows[-1]["lf"], rows[-1]["rf"])))
    return dict(height=height, seed=seed, fell=fell, on_top=on_top, final_x=rows[-1]["x"], rows=rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", default="trained/run20m_resid30_ppo")
    ap.add_argument("--heights", default="0,0.015,0.02,0.025,0.03,0.035,0.04,0.05")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--json-out", default="trained/ledge_bump_study.json")
    args = ap.parse_args()
    from stable_baselines3 import PPO
    model = PPO.load(args.checkpoint, device="cpu")
    out = []
    print(f"{'ledge mm':>8} {'seed':>5} {'on top':>7} {'fell':>5} {'final x':>8} {'max front err':>14} {'p95 err':>8} {'pitch range':>12}")
    for h in [float(x) for x in args.heights.split(",")]:
        for s in range(args.seeds):
            r = run(model, h, 7000 + s, args.seconds)
            e = np.array([row["err"] for row in r["rows"]])
            pr = [row["pitch"] for row in r["rows"]]
            print(f"{h*1000:8.0f} {7000+s:5d} {str(r['on_top']):>7} {str(r['fell']):>5} {r['final_x']:8.3f} "
                  f"{e.max():14.1f} {np.percentile(e.max(1), 95):8.1f} {min(pr):5.1f}..{max(pr):5.1f}", flush=True)
            out.append(r)
    with open(args.json_out, "w") as f:
        json.dump(out, f)


if __name__ == "__main__":
    main()
