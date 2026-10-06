import argparse
from datetime import datetime

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

    def _on_step(self):
        return True


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
    parser.add_argument("--re-ramp", action="store_true",
                        help="with --from: ramp penalties / domain randomization up from zero again "
                             "(default: a continuation starts at full strength)")
    args = parser.parse_args()

    # PPO update threads (2026-10-06): on the M1 Pro the default 8 threads made the update 14.4 s per
    # rollout vs 9.6 s at 4 (686 -> 862 steps/s overall, same math). G2E_TORCH_THREADS overrides.
    import os
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
    ramp_offset = _E.RAMP_TOTAL_STEPS if (args.from_ckpt and not args.re_ramp) else 0.0
    checkpoint_callback = CallbackList([RampSync(ramp_offset), checkpoint_callback])

    if args.from_ckpt:
        # Finetune: load the policy and nudge it with a low CONSTANT LR plus a
        # target_kl early-stop. The previous linear_schedule(3e-4) restart on a
        # converged policy diverged every time (approx_kl 70-400, clip_fraction
        # ~0.99); see --finetune-lr help.
        print(f"finetuning from {args.from_ckpt}  "
              f"(lr={args.finetune_lr}, target_kl={args.finetune_target_kl})")
        model = PPO.load(args.from_ckpt, env=env,
                         n_steps=int(2048*8/parallel_env),
                         learning_rate=args.finetune_lr,
                         target_kl=args.finetune_target_kl,
                         tensorboard_log=None)
        model.learn(args.steps, callback=checkpoint_callback,
                    reset_num_timesteps=True)
    else:
        model = PPO('MlpPolicy', env, seed=42,
                    policy_kwargs=custom_arch,
                    n_steps=int(2048*8/parallel_env),
                    learning_rate=linear_schedule(3e-4),
                    verbose=1,
                    tensorboard_log=None).learn(args.steps, callback=checkpoint_callback)

    model.save(f"trained/{args.tag}_ppo")

    # Load model to continue previous training
    #model = PPO.load("trained/opencat_gym_esp32_trained_controller", 
    #                   env, policy_kwargs=custom_policy_kwargs, 
    #                   n_steps=int(2048*8/parallel_env), verbose=1, 
    #                   tensorboard_log="trained/tensorboard_logs/").learn(2e6)
    #model.save("trained/opencat_gym_esp32_trained_controller_2")


