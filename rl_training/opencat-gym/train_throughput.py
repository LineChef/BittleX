"""Measure training throughput and where the time goes (experience collection vs PPO update), for a given PPO batch size and torch
thread count. Uses train.py's setup (8 SubprocVecEnv envs, [256, 256] MLP, n_steps 2048 per env) and the G2 real-path env vars.

    ../../.venv/bin/python train_throughput.py [BATCH_SIZE] [TORCH_THREADS]      # defaults: 64, torch's default

2026-10-06, M1 Pro (6P + 2E cores), batch 64: 8 threads 686 steps/s (update 14.4 s / rollout), 1: 692, 2: 803, 4: 862 (update 9.6 s);
collection ~9.4 s / 16k-step rollout regardless. train.py now sets 4 threads (G2E_TORCH_THREADS overrides).
Writes nothing (the model is discarded). Must run from a file, not stdin: SubprocVecEnv workers re-import __main__.
"""
import os
import sys
import time

for k, v in dict(G2E_IMU_HOLD_STEPS="16", G2E_IMU_RATE_ZERO="1", G2E_CMD_PATH="i", G2E_CMD_PATH_EXTRA_MS_MAX="4",
                 G2E_BODY_MASS_SCALE="1.12", G2E_IMU_BIAS_DEG="2", G2E_JOINT_OFFSET_DEG="2", G2E_SLOPE_TARGET_PROB="0.3",
                 G2E_SERVO_RATE_LIMIT_DEG_S="137", G2E_CMD_SEND_EVERY_N="3", G2E_FAC_YAW_TRACK="9.0", G2E_PAYLOAD_PROFILE="case").items():
    os.environ.setdefault(k, v)

import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv

from opencat_gym_env import OpenCatGymEnv
from mirror import MirrorPPO


class _Timer(BaseCallback):
    def __init__(self):
        super().__init__()
        self.t = []

    def _on_rollout_start(self):
        self.t.append(time.time())

    def _on_rollout_end(self):
        self.t.append(time.time())

    def _on_step(self):
        return True


if __name__ == "__main__":
    bs = int(sys.argv[1]) if len(sys.argv) > 1 else 64
    if len(sys.argv) > 2:
        torch.set_num_threads(int(sys.argv[2]))
    print("torch threads", torch.get_num_threads(), "batch", bs)
    env = make_vec_env(OpenCatGymEnv, n_envs=8, vec_env_cls=SubprocVecEnv)
    cb = _Timer()
    algo = MirrorPPO if os.environ.get("MIRROR") else PPO              # MIRROR=1 times the mirror-symmetry loss's extra cost
    m = algo("MlpPolicy", env, seed=42, policy_kwargs=dict(net_arch=[256, 256]), n_steps=2048, batch_size=bs, verbose=0)
    if algo is MirrorPPO:
        m.mirror_w, m.mirror_wv = 1.0, 0.1
    t0 = time.time()
    m.learn(16384 * 3, callback=cb)
    tot = time.time() - t0
    ev = cb.t
    coll = [ev[i + 1] - ev[i] for i in range(0, len(ev) - 1, 2)]
    upd = [ev[i + 2] - ev[i + 1] for i in range(0, len(ev) - 2, 2)]
    print(f"total {tot:.1f}s for {16384 * 3} steps = {16384 * 3 / tot:.0f} steps/s; "
          f"collect per rollout {[round(c, 1) for c in coll]} s; update {[round(u, 1) for u in upd]} s")
    env.close()
