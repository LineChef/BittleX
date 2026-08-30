"""Local addition (not part of upstream ger01d/opencat-gym): continues training
an existing checkpoint rather than starting fresh. Used to test the hypothesis
that full_run_v1's late-training collapse was caused by PENALTY_STEPS (2e6)
finishing its ramp right as training ended -- more steps now train under a
stable, fully-ramped penalty instead of a shifting one.
"""
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv
from opencat_gym_env import OpenCatGymEnv

if __name__ == "__main__":
    parallel_env = 8
    env = make_vec_env(OpenCatGymEnv, n_envs=parallel_env, vec_env_cls=SubprocVecEnv)

    model = PPO.load("trained/full_run_v1_ppo", env=env,
                      n_steps=int(2048 * 8 / parallel_env),
                      tensorboard_log="trained/tensorboard_logs/")

    # Save a checkpoint every ~200K total env steps, so an interruption only
    # costs progress back to the last checkpoint, not the entire run.
    checkpoint_callback = CheckpointCallback(
        save_freq=max(200_000 // parallel_env, 1),
        save_path="trained/checkpoints/",
        name_prefix="full_run_v1_continued",
    )

    # reset_num_timesteps=False keeps step counting continuous from ~2.02M,
    # so this run's curve picks up right where full_run_v1's left off in
    # TensorBoard (shows up as a new run, e.g. PPO_2).
    model.learn(2_000_000, reset_num_timesteps=False, callback=checkpoint_callback)

    model.save("trained/full_run_v1_continued_ppo")
