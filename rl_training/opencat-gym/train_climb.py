"""Train / watch the Phase F CLIMB policy (climb_env.ClimbEnv).

    python train_climb.py --steps 400000                 # smoke run
    python train_climb.py --steps 400000 --ledge-lo 0.03 --ledge-hi 0.06
    python train_climb.py --watch trained/climb_smoke    # replay in the GUI
    python train_climb.py --sanity                       # 1 random-action episode, prints reward

Checkpoints + TB logs under trained/ , same as train.py.
"""
import argparse
import os

import numpy as np


def _make(ledge_lo, ledge_hi):
    from climb_env import ClimbEnv
    return lambda: ClimbEnv(ledge_lo=ledge_lo, ledge_hi=ledge_hi)


def sanity(ledge_lo, ledge_hi):
    from climb_env import ClimbEnv
    env = ClimbEnv(ledge_lo=ledge_lo, ledge_hi=ledge_hi)
    obs, _ = env.reset()
    print(f"obs dim {obs.shape}, action dim {env.action_space.shape}")
    tot, steps = 0.0, 0
    while True:
        obs, r, term, trunc, info = env.step(env.action_space.sample())
        tot += r
        steps += 1
        if term or trunc:
            break
    print(f"random episode: {steps} steps, return {tot:.1f}, "
          f"end bz {info['bz']:.3f} pitch {np.degrees(info['pitch']):+.0f} "
          f"on_top {info['on_top']}/4 success {info['success']}")
    env.close()


def watch(path, ledge_lo, ledge_hi, episodes):
    from stable_baselines3 import PPO
    from climb_env import ClimbEnv
    model = PPO.load(path, device="cpu")
    env = ClimbEnv(render_mode="human", ledge_lo=ledge_lo, ledge_hi=ledge_hi)
    for e in range(episodes):
        obs, _ = env.reset()
        tot = 0.0
        while True:
            a, _ = model.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(a)
            tot += r
            if term or trunc:
                print(f"ep {e}: return {tot:.1f}  end bz {info['bz']:.3f}  "
                      f"pitch {np.degrees(info['pitch']):+.0f}  on_top {info['on_top']}/4  "
                      f"{'SUCCESS' if info['success'] else ''}")
                break
    env.close()


def train(steps, ledge_lo, ledge_hi, n_envs, tag):
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.vec_env import SubprocVecEnv
    from stable_baselines3.common.callbacks import CheckpointCallback
    from climb_env import ClimbEnv

    env = make_vec_env(lambda: ClimbEnv(ledge_lo=ledge_lo, ledge_hi=ledge_hi),
                       n_envs=n_envs, vec_env_cls=SubprocVecEnv)
    ckpt = CheckpointCallback(save_freq=max(100_000 // n_envs, 1),
                              save_path="trained/", name_prefix=tag)
    model = PPO("MlpPolicy", env, seed=42,
                policy_kwargs=dict(net_arch=[256, 256]),
                n_steps=int(2048 * 4 / n_envs), batch_size=256,
                gamma=0.99, ent_coef=0.004, learning_rate=3e-4,
                verbose=1, tensorboard_log="trained/tensorboard_logs/")
    model.learn(int(steps), callback=ckpt, tb_log_name=tag)
    out = f"trained/{tag}"
    model.save(out)
    print(f"saved {out}.zip")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=400_000)
    ap.add_argument("--ledge-lo", type=float, default=0.04)
    ap.add_argument("--ledge-hi", type=float, default=0.04)
    ap.add_argument("--n-envs", type=int, default=6)
    ap.add_argument("--tag", default="climb_smoke")
    ap.add_argument("--watch", default=None, help="checkpoint path to replay")
    ap.add_argument("--episodes", type=int, default=4)
    ap.add_argument("--sanity", action="store_true")
    a = ap.parse_args()
    os.makedirs("trained/tensorboard_logs", exist_ok=True)
    if a.sanity:
        sanity(a.ledge_lo, a.ledge_hi)
    elif a.watch:
        watch(a.watch, a.ledge_lo, a.ledge_hi, a.episodes)
    else:
        train(a.steps, a.ledge_lo, a.ledge_hi, a.n_envs, a.tag)
