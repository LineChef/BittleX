"""Validate the deployment mirror: drive pi_pipeline/gait/residual_policy.py from
the sim in lockstep with the training-side model.predict, and assert the
observation, the policy action, and the rounded joint targets match.

If this passes, the on-Pi control loop reproduces run20m_ppo's exact gait -- the
only remaining unknown at deploy time is the sim-vs-real IMU gap.

Alignment: after env.reset(), env._deploy_dbg carries (quat_0, gyro_0, obs_0).
Each iteration t:
    a_t   = model.predict(obs_t)
    env.step(a_t) -> obs_{t+1}, env._deploy_dbg = {quat_{t+1}, gyro_{t+1},
                                                   obs_{t+1}, joint_deg_t}
    j_t   = pol.step(quat_{t+1}, gyro_{t+1})   # consumes pol's pending obs_t,
                                               # emits joints_t, builds obs_{t+1}
compare:  pol.last_action vs a_t ;  j_t vs joint_deg_t ;  pol.obs vs obs_{t+1}

    python validate_deploy.py
    python validate_deploy.py --steps 800 --cmd 0.10 --verbose
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pi_pipeline", "gait"))
sys.path.insert(0, HERE)


def run_one(cmd_fwd, steps, onnx_path, wkf_path, verbose=False):
    import opencat_gym_env as E
    E.GUI_MODE = False
    E.DEPLOY_DEBUG = True
    E.DR_EVAL_FULL = True
    for k, v in dict(RANDOM_GYRO=0.0, RANDOM_JOINT_ANGS=0.0, RANDOM_FRICTION=0.0,
                     RANDOM_MASS=0.0, RANDOM_PUSH=0.0, IMPULSE_PUSH=0.0,
                     RANDOM_TERRAIN=0.0, ROUGH_TERRAIN=0.0, TORQUE_CUTBACK=0.0,
                     PAYLOAD_PROB=0.0, SLOPE_MAX_DEG=0.0, START_POSE_JITTER=0.0,
                     CMD_RESAMPLE_PROB=0.0, STUCK_FOOT_PROB=0.0, SUSTAINED_FORCE=0.0,
                     CMD_LATENCY_STEPS=0, JOINT_OFFSET_DEG=0.0).items():
        setattr(E, k, v)
    E.SLOPE_FIXED_RP = None

    from opencat_gym_env import OpenCatGymEnv
    from residual_policy import ResidualGaitPolicy, quat_to_euler
    from stable_baselines3 import PPO
    import pybullet as p

    env = OpenCatGymEnv()
    env.set_command(fwd=cmd_fwd, yaw=0.0)
    model = PPO.load(onnx_path.replace(".onnx", ""), device="cpu")
    pol = ResidualGaitPolicy(onnx_path=onnx_path, wkf_path=wkf_path)
    pol.set_command(fwd=cmd_fwd, yaw=0.0)

    np.random.seed(0)
    obs, _ = env.reset()
    d0 = env._deploy_dbg
    j0 = np.asarray(p.getJointStates(env.robot_id, env.joint_id), dtype=object)[:, 0].astype(float)
    pol.reset(j0, d0["quat"], d0["angvel_raw"])

    obs0_err = np.abs(pol.obs.astype(np.float64) - d0["obs"]).max()

    obs_err, act_err, euler_err = [], [], []
    jdeg_cells_off, jdeg_max = 0, 0
    dbg_prev = d0

    for t in range(steps):
        a_sb3, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, _ = env.step(a_sb3)
        dbg = env._deploy_dbg                       # quat_{t+1}, obs_{t+1}, joint_deg_t

        j_pol = pol.step(dbg["quat"], dbg["angvel_raw"])
        act_err.append(float(np.abs(pol.last_action - a_sb3).max()))
        dm = np.abs(j_pol - dbg["joint_deg"])
        jdeg_cells_off += int((dm > 0).sum())
        jdeg_max = max(jdeg_max, int(dm.max()))
        obs_err.append(float(np.abs(pol.obs.astype(np.float64) - dbg["obs"]).max()))
        my_rp = np.array(quat_to_euler(dbg["quat"])[:2])
        euler_err.append(float(np.abs(my_rp - dbg["euler_rp"]).max()))

        if verbose and t < 8:
            print(f"  t={t:3d}  act_err={act_err[-1]:.2e}  obs_err={obs_err[-1]:.2e}  "
                  f"jdeg_diff={dm.tolist()}")
        dbg_prev = dbg
        if term or trunc:
            break

    return dict(cmd=cmd_fwd, n=len(obs_err), obs0_err=obs0_err,
                obs_max=max(obs_err) if obs_err else None,
                obs_mean=float(np.mean(obs_err)) if obs_err else None,
                act_max=max(act_err) if act_err else None,
                euler_max=max(euler_err) if euler_err else None,
                jdeg_cells_off=jdeg_cells_off, jdeg_max=jdeg_max)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", default=os.path.join(HERE, "trained", "run20m_ppo.onnx"))
    ap.add_argument("--wkf", default=os.path.join(HERE, "reference_gait", "wkf_ref.npy"))
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--cmd", type=float, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cmds = [args.cmd] if args.cmd is not None else [0.0, 0.04, 0.10, 0.14, -0.06]
    print(f"{'cmd':>6} {'n':>4} {'obs0_err':>10} {'obs_max':>10} {'obs_mean':>10} "
          f"{'act_max':>10} {'euler_err':>10} {'jdeg_off':>9} {'jdeg_max°':>10}  verdict")
    allok = True
    for c in cmds:
        r = run_one(c, args.steps, args.onnx, args.wkf, verbose=args.verbose)
        ok = (r["obs_max"] or 0) < 2e-4 and r["jdeg_cells_off"] == 0 and (r["act_max"] or 0) < 1e-4
        allok &= ok
        print(f"{r['cmd']:>6.2f} {r['n']:>4} {r['obs0_err']:>10.2e} {r['obs_max']:>10.2e} "
              f"{r['obs_mean']:>10.2e} {r['act_max']:>10.2e} {r['euler_max']:>10.2e} "
              f"{r['jdeg_cells_off']:>9} {r['jdeg_max']:>10}  {'OK' if ok else 'MISMATCH'}")
    print("\n" + ("ALL OK -- the deployment mirror reproduces the sim policy exactly"
                  if allok else "MISMATCH -- residual_policy.py diverges from the env"))
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
