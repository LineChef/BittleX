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
    """episodes <= 0 -> loop forever (Ctrl-C to stop)."""
    import time
    from stable_baselines3 import PPO
    from climb_env import ClimbEnv
    model = PPO.load(path, device="cpu")
    env = ClimbEnv(render_mode="human", ledge_lo=ledge_lo, ledge_hi=ledge_hi)
    print(f"watching {path}   ledge {ledge_lo*100:.1f}-{ledge_hi*100:.1f} cm   "
          f"({'looping, Ctrl-C to stop' if episodes <= 0 else str(episodes)+' episodes'})")
    e = 0
    try:
        while episodes <= 0 or e < episodes:
            obs, _ = env.reset()
            tot = 0.0
            while True:
                a, _ = model.predict(obs, deterministic=True)
                obs, r, term, trunc, info = env.step(a)
                tot += r
                if term or trunc:
                    print(f"  ep {e + 1:3d}: ledge {env._ledge_h*100:.1f}cm  return {tot:7.1f}  "
                          f"end bz {info['bz']:.3f}  pitch {np.degrees(info['pitch']):+.0f}  "
                          f"feet-on-top {info['on_top']}/4  "
                          f"{'SUCCESS' if info['success'] else ''}")
                    break
            e += 1
            time.sleep(1.1)                       # beat between episodes so it doesn't look glitchy
    except KeyboardInterrupt:
        print("\nstopped.")
    env.close()


def train(steps, ledge_lo, ledge_hi, n_envs, tag, curr_end=0.0):
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
    from stable_baselines3.common.vec_env import SubprocVecEnv
    from stable_baselines3.common.callbacks import CheckpointCallback, BaseCallback
    from climb_env import ClimbEnv

    env = make_vec_env(lambda: ClimbEnv(ledge_lo=ledge_lo, ledge_hi=ledge_hi),
                       n_envs=n_envs, vec_env_cls=SubprocVecEnv)
    ckpt = CheckpointCallback(save_freq=max(100_000 // n_envs, 1),
                              save_path="trained/", name_prefix=tag)
    cbs = [ckpt]

    if curr_end > 0:
        # linear height curriculum: (0.010, 0.020) -> (ledge_lo, ledge_hi) over
        # `curr_end` fraction of training, then hold at full range.
        class Curriculum(BaseCallback):
            def _on_step(self):
                f = min(1.0, self.num_timesteps / (curr_end * steps))
                lo = 0.010 + f * (ledge_lo - 0.010)
                hi = 0.020 + f * (ledge_hi - 0.020)
                self.training_env.env_method("set_ledge", lo, hi)
                return True
        cbs.append(Curriculum())
        print(f"curriculum: ledge (0.010,0.020) -> ({ledge_lo},{ledge_hi}) over "
              f"{curr_end:.0%} of {steps} steps")

    model = PPO("MlpPolicy", env, seed=42,
                policy_kwargs=dict(net_arch=[256, 256]),
                n_steps=int(2048 * 4 / n_envs), batch_size=256,
                gamma=0.99, ent_coef=0.012, learning_rate=3e-4,
                verbose=1, tensorboard_log="trained/tensorboard_logs/")
    model.learn(int(steps), callback=cbs, tb_log_name=tag)
    out = f"trained/{tag}"
    model.save(out)
    print(f"saved {out}.zip")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=400_000)
    ap.add_argument("--ledge-lo", type=float, default=0.04)
    ap.add_argument("--ledge-hi", type=float, default=0.04)
    ap.add_argument("--n-envs", type=int, default=6)
    ap.add_argument("--curr-end", type=float, default=0.0,
                    help="fraction of training over which to ramp ledge height from "
                         "(1,2 cm) to (--ledge-lo,--ledge-hi); 0 = no curriculum")
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
        train(a.steps, a.ledge_lo, a.ledge_hi, a.n_envs, a.tag, a.curr_end)
