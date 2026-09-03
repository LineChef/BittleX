"""Parity check: the exported ONNX policy must produce the same deterministic
actions as the PyTorch SB3 policy, on both random and real-rollout observations.

A silent export mismatch (wrong weight order, opset quirk, dtype) is a worse
failure mode on the robot than any latency issue -- this is the gate before the
.onnx ships to the Pi.

    python verify_onnx.py --model trained/run20m_ppo --onnx trained/run20m_ppo.onnx
"""
import argparse

import numpy as np
import onnxruntime as ort
from stable_baselines3 import PPO


def real_obs_batch(n):
    """Observations from an actual env rollout under the loaded policy -- the
    distribution that matters, not just gaussian noise."""
    import opencat_gym_env as E
    E.GUI_MODE = False
    E.DR_EVAL_FULL = True
    from opencat_gym_env import OpenCatGymEnv
    env = OpenCatGymEnv()
    obs, _ = env.reset()
    if hasattr(env, "set_command"):
        env.set_command(fwd=0.10, yaw=0.0)
    out = []
    m = _MODEL
    for _ in range(n):
        out.append(np.asarray(obs, dtype=np.float32))
        a, _ = m.predict(obs, deterministic=True)
        obs, _, term, trunc, _ = env.step(a)
        if term or trunc:
            obs, _ = env.reset()
            if hasattr(env, "set_command"):
                env.set_command(fwd=0.10, yaw=0.0)
    env.close()
    return np.stack(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="trained/run20m_ppo")
    ap.add_argument("--onnx", default=None)
    ap.add_argument("--tol", type=float, default=1e-5)
    ap.add_argument("--n-random", type=int, default=4000)
    ap.add_argument("--n-rollout", type=int, default=1500)
    args = ap.parse_args()
    onnx_path = args.onnx or (args.model + ".onnx")

    global _MODEL
    _MODEL = PPO.load(args.model, device="cpu")
    obs_dim = int(np.prod(_MODEL.observation_space.shape))

    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name

    def onnx_act(batch):
        return sess.run(None, {in_name: batch.astype(np.float32)})[0]

    def sb3_act(batch):
        return np.stack([_MODEL.predict(o, deterministic=True)[0] for o in batch])

    worst = 0.0
    for label, batch in [
        ("gaussian(0,1)", np.random.default_rng(1).standard_normal((args.n_random, obs_dim)).astype(np.float32)),
        ("gaussian(0,3)", (np.random.default_rng(2).standard_normal((args.n_random, obs_dim)) * 3).astype(np.float32)),
        ("real rollout",  real_obs_batch(args.n_rollout)),
    ]:
        a_onnx = onnx_act(batch)
        a_sb3 = sb3_act(batch)
        d = np.abs(a_onnx - a_sb3)
        worst = max(worst, d.max())
        print(f"  {label:14s}  n={len(batch):5d}  max|diff|={d.max():.2e}  mean|diff|={d.mean():.2e}  "
              + ("OK" if d.max() < args.tol else "!! FAIL"))

    print(f"\nworst max|diff| = {worst:.2e}   tol = {args.tol:.0e}")
    if worst < args.tol:
        print("PARITY OK -- safe to ship this .onnx to the Pi")
        return 0
    print("PARITY FAIL -- do not deploy")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
