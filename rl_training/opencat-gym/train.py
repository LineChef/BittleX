from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
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


if __name__ == "__main__":
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
        name_prefix="full_run_v5",
    )

    # Define PPO agent and train
    model = PPO('MlpPolicy', env, seed=42,
                policy_kwargs=custom_arch,
                n_steps=int(2048*8/parallel_env),
                learning_rate=linear_schedule(3e-4),
                verbose=1,
                tensorboard_log="trained/tensorboard_logs/").learn(2e6, callback=checkpoint_callback)

    model.save("trained/full_run_v5_ppo")

    # Load model to continue previous training
    #model = PPO.load("trained/opencat_gym_esp32_trained_controller", 
    #                   env, policy_kwargs=custom_policy_kwargs, 
    #                   n_steps=int(2048*8/parallel_env), verbose=1, 
    #                   tensorboard_log="trained/tensorboard_logs/").learn(2e6)
    #model.save("trained/opencat_gym_esp32_trained_controller_2")


