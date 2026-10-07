import argparse
import os
from datetime import datetime

import numpy as np

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, CallbackList, CheckpointCallback
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv
from opencat_gym_env import OpenCatGymEnv

# Create OpenCatGym environment from class and check if structure is correct
#env = OpenCatGymEnv()
#check_env(env)


def linear_schedule(initial_value):
    """Linearly decay from initial_value at the start of training to 0 at the
    end. SB3 calls this with progress_remaining going from 1.0 -> 0.0.
    Added to prevent large, destabilizing updates late in training once the
    policy has converged and its action noise (std) has shrunk -- a fixed
    learning rate the whole run was a likely contributor to the recurring
    late-training collapses seen in v1 and v4.
    """
    def schedule(progress_remaining):
        return progress_remaining * initial_value
    return schedule


class RampSync(BaseCallback):
    """Tells every env the run's total step count before each rollout, so the penalty / DR ramps
    (opencat_gym_env RAMP_MODE "total") follow the whole run, not one env's share of it.
    `offset` is added to the count: a continuation passes RAMP_TOTAL_STEPS so it starts at full strength."""
    def __init__(self, offset=0.0):
        super().__init__()
        self.offset = float(offset)

    def _on_training_start(self):
        self._on_rollout_start()

    def _on_rollout_start(self):
        self.training_env.env_method("set_ramp_steps", self.offset + self.num_timesteps)

    def _on_rollout_end(self):
        try:
            lv = np.array(self.training_env.get_attr("_level"), dtype=float)
            cats = self.training_env.get_attr("_levels")               # one dict per env: {category: level}
            if lv.size:
                self.logger.record("curriculum/level_mean", float(lv.mean()))
                per = {c: float(np.mean([d[c] for d in cats])) for c in cats[0]}
                scs = self.training_env.get_attr("_cat_score")
                sc = {c: float(np.nanmean([d[c] for d in scs])) if not all(np.isnan(d[c]) for d in scs) else float("nan") for c in scs[0]}
                for c, v in per.items():
                    self.logger.record(f"curriculum/{c}", v)
                print(f"[level] steps {self.offset + self.num_timesteps:.0f}  mean level {lv.mean():.2f} (min {lv.min():.2f}, max {lv.max():.2f})  by category (level, last window score): "
                      + "  ".join(f"{c} {v:.2f} ({sc[c]:.2f})" for c, v in per.items()), flush=True)
        except Exception:
            pass

    def _on_step(self):
        return True


class Curriculum(BaseCallback):
    """Difficulty curriculum driven by a DETERMINISTIC probe (opencat_gym_env LEVEL_EXTERNAL). Every `every` training steps the current policy is run, without
    exploration noise, for `episodes` episodes on each hazard category at its current level (the others at 0; random training commands); the category's mean episode
    score (survived x fraction of commanded distance covered) is compared with LEVEL_UP_SCORE / LEVEL_DOWN_SCORE: LEVEL_PROMOTE_WINDOWS consecutive good probes raise the
    category by LEVEL_STEP_C, one bad probe lowers it. The new levels are pushed to every training env. `start` is the level every category starts at."""
    def __init__(self, every=98304, episodes=6, start=0.0, ramp_offset=0.0, verbose=1):
        super().__init__(verbose)
        self.every, self.episodes = int(every), int(episodes)
        self.ramp_offset = float(ramp_offset)
        import opencat_gym_env as E
        self.E = E
        self.levels = {c: float(start) for c in E.CATS}
        self.streak = {c: 0 for c in E.CATS}
        self.last = {c: float("nan") for c in E.CATS}
        self.raw = {c: float("nan") for c in E.CATS}
        self.base = float("nan")
        self.env = None
        self._next = self.every

    def _on_training_start(self):
        self.E.GUI_MODE = False
        self.E.CATEGORY_OVERRIDE = {}
        self.env = self.E.OpenCatGymEnv()
        self.training_env.env_method("set_category_levels", self.levels)

    def _probe(self, cat):
        """Mean episode score (survived x fraction of commanded distance) of the deterministic policy with `cat` at its level and every other category at 0.
        cat=None: the clean-floor baseline (all categories 0). The probe env gets the SAME generic-randomization ramp as the training envs."""
        import pybullet as p
        self.E.CATEGORY_OVERRIDE = {cat if cat else "terrain": self.levels[cat] if cat else 0.0}
        self.env.set_ramp_steps(self.ramp_offset + self.num_timesteps)
        scores, signs = [], []
        for k in range(self.episodes):
            obs, _ = self.env.reset(seed=int(self.num_timesteps) % 100000 + k)
            signs.append(getattr(self.env, "_len_sign", 0.0))
            peak = 0.0
            while True:
                act, _ = self.model.predict(obs, deterministic=True)
                obs, _r, te, tr, _i = self.env.step(act)
                rr, pp, _y = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(self.env.robot_id)[1])
                peak = max(peak, abs(rr), abs(pp))
                if te or tr:
                    break
            scores.append(self.env._episode_score() if peak <= 1.3 else 0.0)
        self.E.CATEGORY_OVERRIDE = {}
        if cat == "length":                              # the length level is only earned if BOTH push directions pass: the lower of the left and right means (the probe alternates the sign)
            sides = [np.mean([s for s, g in zip(scores, signs) if g == sign]) for sign in (-1.0, 1.0) if any(g == sign for g in signs)]
            return float(min(sides)) if sides else float(np.mean(scores))
        return float(np.mean(scores))

    def _on_step(self):
        return True

    def _on_rollout_end(self):
        if self.num_timesteps < self._next:
            return
        self._next += self.every
        E = self.E
        base = self._probe(None)                         # what this policy scores on a clean floor under the same randomization: hazards are judged relative to it
        self.base = base
        cap = min(1.0, (self.ramp_offset + self.num_timesteps) / E.RAMP_TOTAL_STEPS) if E.LEVEL_CAP_BY_TIME else 1.0
        rel = {}
        for c in E.CATS:
            raw = self._probe(c)
            rel[c] = min(1.0, raw / max(base, 0.30))      # RELATIVE score: a slow walker, or one limited by the randomization, is not penalized for it
            self.last[c], self.raw[c] = rel[c], raw
        from curriculum import update_levels
        update_levels(self.levels, self.streak, rel, base, cap, E.LEVEL_UP_SCORE, E.LEVEL_DOWN_SCORE, E.LEVEL_STEP_C, E.LEVEL_PROMOTE_WINDOWS,
                      E.LEVEL_MIN_BASELINE, E.LEVEL_COLLAPSE_BASELINE)
        self.training_env.env_method("set_category_levels", self.levels)
        print(f"[probe] steps {self.num_timesteps:.0f}  clean-floor score {self.base:.2f} (cap {cap:.2f}); relative score by category (raw) -> new level: "
              + "  ".join(f"{c} {self.last[c]:.2f} ({self.raw[c]:.2f}) -> {self.levels[c]:.2f}" for c in E.CATS), flush=True)


if __name__ == "__main__":
    # --tag names this run everywhere: checkpoints land in
    # trained/checkpoints/<tag>_<steps>_steps.zip and the final model in
    # trained/<tag>_ppo.zip. TensorBoard logging is disabled (tensorboard_log=None
    # below) -- not needed; use evaluate_policy.py / g2watch on checkpoints instead.
    # Pass the reward-iteration label, e.g.  python train.py --tag v7
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag",
                        default="run_" + datetime.now().strftime("%Y%m%d_%H%M%S"),
                        help="label for this run's checkpoint/model filenames")
    parser.add_argument("--steps", type=float, default=2e6,
                        help="total env steps to train (default 2e6)")
    parser.add_argument("--from", dest="from_ckpt", default=None,
                        help="finetune from this checkpoint (e.g. trained/auto_gait_final_ppo) "
                             "instead of training a fresh policy")
    parser.add_argument("--finetune-lr", type=float, default=3e-5,
                        help="CONSTANT LR for --from finetuning (default 3e-5). The old "
                             "linear_schedule(3e-4) restart diverged a converged policy every "
                             "time: approx_kl 70-400, clip_fraction ~0.99 (run20m from-scratch "
                             "ran at kl ~0.01). Finetuning needs a gentle nudge, not a kick.")
    parser.add_argument("--finetune-target-kl", type=float, default=0.05,
                        help="SB3 aborts an update once approx_kl exceeds this (finetune only) -- "
                             "a hard backstop against the divergence above")
    parser.add_argument("--mirror-loss", type=float, default=float(os.environ.get("G2E_MIRROR_LOSS", "0") or 0),
                        help="V3 lever R1: weight of the left/right mirror-symmetry loss (mirror.py MirrorPPO); 0 = plain PPO. "
                             "Env default G2E_MIRROR_LOSS. Value-loss weight: G2E_MIRROR_VALUE_LOSS (default 0.1)")
    parser.add_argument("--re-ramp", action="store_true",
                        help="with --from: ramp penalties / domain randomization up from zero again "
                             "(default: a continuation starts at full strength)")
    args = parser.parse_args()

    # PPO update threads (2026-10-06): on the M1 Pro the default 8 threads made the update 14.4 s per
    # rollout vs 9.6 s at 4 (686 -> 862 steps/s overall, same math). G2E_TORCH_THREADS overrides.
    import torch
    torch.set_num_threads(int(os.environ.get("G2E_TORCH_THREADS", "4")))

    # Set up number of parallel environments
    parallel_env = 8
    env = make_vec_env(OpenCatGymEnv,
                       n_envs=parallel_env,
                       vec_env_cls=SubprocVecEnv)

    # Change architecture of neural network to two hidden layers of size 256
    custom_arch = dict(net_arch=[256, 256])

    # Save a checkpoint every ~200K total env steps, so an interruption only
    # costs progress back to the last checkpoint, not the entire run (train.py
    # previously only saved once, at the very end of .learn()).
    checkpoint_callback = CheckpointCallback(
        save_freq=max(200_000 // parallel_env, 1),
        save_path="trained/checkpoints/",
        name_prefix=args.tag,
    )
    import opencat_gym_env as _E
    if args.mirror_loss > 0:
        from mirror import MirrorPPO
        PPOCls = MirrorPPO
        print(f"mirror-symmetry loss ON: policy weight {args.mirror_loss}, value weight "
              f"{float(os.environ.get('G2E_MIRROR_VALUE_LOSS', '0.1'))}", flush=True)
    else:
        PPOCls = PPO
    ramp_offset = max(_E.RAMP_TOTAL_STEPS, _E.RAMP_PENALTY_STEPS) if (args.from_ckpt and not args.re_ramp) else 0.0
    cbs = [RampSync(ramp_offset), checkpoint_callback]
    if _E.LEVEL_EXTERNAL and _E.ADAPTIVE_LEVEL and _E.CATEGORY_LEVELS:
        cbs.append(Curriculum(every=int(os.environ.get("G2E_PROBE_EVERY", "98304")), episodes=int(os.environ.get("G2E_PROBE_EPISODES", "6")),
                              start=_E.LEVEL_FIXED if _E.LEVEL_FIXED >= 0 else _E.LEVEL_START, ramp_offset=ramp_offset))
    checkpoint_callback = CallbackList(cbs)

    if args.from_ckpt:
        # Finetune: load the policy and nudge it with a low CONSTANT LR plus a
        # target_kl early-stop. The previous linear_schedule(3e-4) restart on a
        # converged policy diverged every time (approx_kl 70-400, clip_fraction
        # ~0.99); see --finetune-lr help.
        print(f"finetuning from {args.from_ckpt}  "
              f"(lr={args.finetune_lr}, target_kl={args.finetune_target_kl})")
        model = PPOCls.load(args.from_ckpt, env=env,
                         n_steps=int(2048*8/parallel_env),
                         learning_rate=args.finetune_lr,
                         target_kl=args.finetune_target_kl,
                         tensorboard_log=None)
        if args.mirror_loss > 0:
            model.mirror_w, model.mirror_wv = args.mirror_loss, float(os.environ.get("G2E_MIRROR_VALUE_LOSS", "0.1"))
        model.learn(args.steps, callback=checkpoint_callback,
                    reset_num_timesteps=True)
    else:
        model = PPOCls('MlpPolicy', env, seed=int(os.environ.get("G2E_SEED", "42")),
                    policy_kwargs=custom_arch,
                    n_steps=int(2048*8/parallel_env),
                    learning_rate=linear_schedule(3e-4),
                    verbose=1,
                    tensorboard_log=None)
        if args.mirror_loss > 0:
            model.mirror_w, model.mirror_wv = args.mirror_loss, float(os.environ.get("G2E_MIRROR_VALUE_LOSS", "0.1"))
        model.learn(args.steps, callback=checkpoint_callback)

    model.save(f"trained/{args.tag}_ppo")

    # Load model to continue previous training
    #model = PPO.load("trained/opencat_gym_esp32_trained_controller", 
    #                   env, policy_kwargs=custom_policy_kwargs, 
    #                   n_steps=int(2048*8/parallel_env), verbose=1, 
    #                   tensorboard_log="trained/tensorboard_logs/").learn(2e6)
    #model.save("trained/opencat_gym_esp32_trained_controller_2")


