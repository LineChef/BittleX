"""Launch a training run and kill it early if it's clearly not converging, so a
bad recipe costs ~1 h instead of ~4.

    python run_with_bailout.py --tag phase2 --steps 10000000
    python run_with_bailout.py --tag phase2b --steps 10000000 --from trained/cov_r1_slope_ppo

Checks the latest checkpoint at two milestones:
  ~1M steps  (gross sanity) : is it moving at all / not collapsing?
  ~3M steps  (on track)     : is it a real forward gait?
On a fail it kills training and writes trained/<tag>.BAILOUT with the reason.
On the 3M pass it stops checking and lets the run finish.
"""
import argparse
import glob
import os
import subprocess
import sys
import time

import numpy as np


def latest_ckpt(tag, min_steps):
    best, best_n = None, -1
    for p in glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"):
        try:
            n = int(p.split("_")[-2])
        except ValueError:
            continue
        if n >= min_steps and n > best_n:
            best, best_n = p, n
    return best, best_n


def flat_eval(ckpt, episodes):
    """Headless flat-ground rollout. Returns (mean_fwd_speed, fall_rate, mean_len)."""
    import opencat_gym_env as E
    E.GUI_MODE = False
    for k in ("SLOPE_MAX_DEG", "START_POSE_JITTER", "STUCK_FOOT_PROB", "SUSTAINED_FORCE",
              "DEFORM_GROUND", "SLIP_PATCH", "RANDOM_TERRAIN", "RANDOM_PUSH", "IMPULSE_PUSH",
              "RANDOM_FRICTION", "RANDOM_MASS", "RANDOM_GYRO", "PHASE_RAND", "LEDGE_HEIGHT", "LEDGE_PROB",
              "ROUGH_TERRAIN", "TORQUE_CUTBACK"):
        if hasattr(E, k):
            setattr(E, k, 0.0)
    if hasattr(E, "SLOPE_FIXED_RP"):
        E.SLOPE_FIXED_RP = (0.0, 0.0)
    # G4: the payload is bolted on -- the policy only ever trains with it, so the
    # bailout sanity gate evaluates with it too (nominal mass, no jitter).
    if hasattr(E, "PAYLOAD_PROB"):
        E.PAYLOAD_PROB = 1.0
    if hasattr(E, "PAYLOAD_MASS_RAND"):
        E.PAYLOAD_MASS_RAND = 0.0
    E.DR_EVAL_FULL = True
    from opencat_gym_env import OpenCatGymEnv, CONTROL_HZ
    import pybullet as p
    from stable_baselines3 import PPO
    m = PPO.load(ckpt)
    env = OpenCatGymEnv()
    if hasattr(env, "set_command"):
        env.set_command(fwd=getattr(env, "_cmd_target_speed", 0.10), yaw=0.0)  # ask for a forward walk
    sp, fell, lens = [], 0, []
    for e in range(episodes):
        np.random.seed(9000 + e)
        obs, _ = env.reset()
        if hasattr(env, "set_command"):
            env.set_command(fwd=0.10, yaw=0.0)
        x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        steps, term, trunc = 0, False, False
        while not (term or trunc):
            a, _ = m.predict(obs, deterministic=True)
            obs, _, term, trunc, _ = env.step(a)
            steps += 1
        x1 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        sp.append((x1 - x0) / (steps / CONTROL_HZ))
        fell += int(term)
        lens.append(steps)
    env.close()
    return float(np.mean(sp)), fell / episodes, float(np.mean(lens))


def bail(tag, proc, reason):
    print(f"\n*** BAILOUT: {reason} ***", flush=True)
    try:
        proc.terminate(); proc.wait(timeout=15)
    except Exception:
        proc.kill()
    with open(f"trained/{tag}.BAILOUT", "w") as f:
        f.write(reason + "\n")
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--steps", type=float, default=1e7)
    ap.add_argument("--from", dest="from_ckpt", default=None)
    ap.add_argument("--finetune-lr", type=float, default=None)
    ap.add_argument("--finetune-target-kl", type=float, default=None)
    args = ap.parse_args()

    try:
        os.remove(f"trained/{args.tag}.BAILOUT")
    except OSError:
        pass

    cmd = [sys.executable, "train.py", "--tag", args.tag, "--steps", str(args.steps)]
    if args.from_ckpt:
        cmd += ["--from", args.from_ckpt]
    if args.finetune_lr is not None:
        cmd += ["--finetune-lr", str(args.finetune_lr)]
    if args.finetune_target_kl is not None:
        cmd += ["--finetune-target-kl", str(args.finetune_target_kl)]
    print("launch:", " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd)

    # (milestone_steps, need_speed, max_fall, episodes, label)
    gates = [
        (1_000_000, 0.010, 0.90, 6,  "1M gross sanity"),
        (3_000_000, 0.035, 0.45, 12, "3M on-track"),
    ]
    gi = 0
    while proc.poll() is None and gi < len(gates):
        ms, need_sp, max_fall, eps, label = gates[gi]
        ckpt, n = latest_ckpt(args.tag, ms)
        if ckpt is None:
            time.sleep(20)
            continue
        print(f"\n[{label}] evaluating {ckpt} ({n} steps)...", flush=True)
        try:
            spd, fr, ln = flat_eval(ckpt, eps)
        except Exception as e:
            print(f"[{label}] eval error ({e}) -- skipping this gate", flush=True)
            gi += 1
            continue
        print(f"[{label}] fwd {spd:.3f} m/s | fall {fr:.0%} | ep_len {ln:.0f}", flush=True)
        if spd < need_sp:
            bail(args.tag, proc, f"{label}: forward speed {spd:.3f} < {need_sp} (not walking)")
        if fr > max_fall:
            bail(args.tag, proc, f"{label}: fall rate {fr:.0%} > {max_fall:.0%}")
        if ln < 40:
            bail(args.tag, proc, f"{label}: mean episode length {ln:.0f} < 40 (falling instantly)")
        print(f"[{label}] PASS", flush=True)
        gi += 1

    rc = proc.wait()
    print(f"\ntraining exited ({rc}). {len(gates)} gate(s) checked, no bailout." if rc == 0
          else f"\ntraining exited with code {rc}.", flush=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
