"""Local addition (not part of upstream ger01d/opencat-gym): a short training
run to sanity-check the full pipeline (training loop, logging, checkpoint
saving/loading) before committing to train.py's full 2M-step run. Not enough
steps to produce a good gait -- just confirms everything works end-to-end.
"""
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv
from opencat_gym_env import OpenCatGymEnv

if __name__ == "__main__":
    parallel_env = 4
    env = make_vec_env(OpenCatGymEnv, n_envs=parallel_env, vec_env_cls=SubprocVecEnv)

    custom_arch = dict(net_arch=[256, 256])
    model = PPO('MlpPolicy', env, seed=42,
                policy_kwargs=custom_arch,
                n_steps=512,
                verbose=1).learn(20_000)

    model.save("trained/smoke_test_ppo")
    print("Saved smoke test checkpoint to trained/smoke_test_ppo.zip")
