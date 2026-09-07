"""Graft a smaller-observation policy into a wider network (new zero-init cols).

To finetune ON TOP OF the existing gait rather than from scratch, copy every
weight of the source policy into a fresh network sized for the current env, and
ZERO the new input columns of each obs-facing layer -- so at step 0 the new
inputs contribute nothing and the grafted policy reproduces the source gait
exactly. Training can then only ADD a learned response; it starts as the
existing gait, so it can't "fight" it.

The target width comes from whatever G2E_* flags are set when this runs:
    G2E_TERRAIN_FEATURE=1 python graft_terrain_policy.py \
        --src trained/run20m_ppo --dst trained/run20m_graft282     # 278 -> 282
    G2E_TERRAIN_FEATURE=1 G2E_GOAL_MODE=1 python graft_terrain_policy.py \
        --src trained/run20m_ppo --dst trained/run20m_graft285     # 278 -> 285

Then:  <same G2E_* flags> python train.py --from <dst> --tag <tag> --steps <N>
"""
import argparse
import os

import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import DummyVecEnv

from opencat_gym_env import OpenCatGymEnv, SIZE_OBSERVATION

ap = argparse.ArgumentParser()
ap.add_argument("--src", default="trained/run20m_ppo")
ap.add_argument("--dst", default="trained/run20m_graft282")
ap.add_argument("--check-episodes", type=int, default=3)
args = ap.parse_args()

src = PPO.load(args.src, device="cpu")
src_dim = src.observation_space.shape[0]

env = make_vec_env(OpenCatGymEnv, n_envs=1, vec_env_cls=DummyVecEnv)
dst_dim = env.observation_space.shape[0]
n_new = dst_dim - src_dim
print(f"src obs dim {src_dim}   dst obs dim {dst_dim}   (+{n_new} new cols)   (SIZE_OBSERVATION={SIZE_OBSERVATION})")
assert 0 < n_new <= 16, f"expected dst = src + a few, got {src_dim} -> {dst_dim}"

dst = PPO("MlpPolicy", env, seed=42, policy_kwargs=dict(net_arch=[256, 256]), device="cpu")

ssd = src.policy.state_dict()
new_sd = {}
for k, dst_t in dst.policy.state_dict().items():
    src_t = ssd.get(k)
    if src_t is None:
        new_sd[k] = dst_t.clone()
        print(f"  {k:44s} not in src -> left fresh")
    elif src_t.shape == dst_t.shape:
        new_sd[k] = src_t.clone()
        print(f"  {k:44s} copied {tuple(src_t.shape)}")
    elif (src_t.dim() == 2 and dst_t.shape[0] == src_t.shape[0]
          and dst_t.shape[1] == src_t.shape[1] + n_new):
        g = torch.zeros_like(dst_t)
        g[:, :src_t.shape[1]] = src_t            # old obs columns; new cols stay 0
        new_sd[k] = g
        print(f"  {k:44s} GRAFTED {tuple(src_t.shape)} -> {tuple(dst_t.shape)}  (+{n_new} cols = 0)")
    else:
        new_sd[k] = dst_t.clone()
        print(f"  {k:44s} SHAPE MISMATCH src{tuple(src_t.shape)} dst{tuple(dst_t.shape)} -> left fresh")

dst.policy.load_state_dict(new_sd)

# --- behaviour-parity check: grafted 282-d policy must match the source on the
#     same states (the 4 terrain columns are zeroed, so their value can't matter)
env2 = OpenCatGymEnv()
max_abs = 0.0
for e in range(args.check_episodes):
    np.random.seed(5000 + e)
    obs, _ = env2.reset()
    for _ in range(250):
        a_dst, _ = dst.predict(obs, deterministic=True)
        a_src, _ = src.predict(obs[:src_dim], deterministic=True)
        max_abs = max(max_abs, float(np.max(np.abs(a_dst - a_src))))
        obs, _, term, trunc, _ = env2.step(a_dst)
        if term or trunc:
            break
env2.close()
print(f"\nmax |action(dst_282) - action(src_278)| over {args.check_episodes} episodes: {max_abs:.2e}")
if max_abs > 1e-4:
    print("  WARNING: graft did not preserve behaviour (expected < 1e-4)")
else:
    print("  OK -- grafted policy reproduces the source gait")

dst.save(args.dst)
print(f"\nwrote {args.dst}.zip")
