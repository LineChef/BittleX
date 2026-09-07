"""Local addition (not part of upstream ger01d/opencat-gym): loads a saved
checkpoint and replays it deterministically in the PyBullet GUI, so training
results can be watched visually rather than just read from reward logs.

Usage:
  python watch_trained.py <tag>                 # newest trained/checkpoints/<tag>_*_steps.zip,
                                                # or trained/<tag>_ppo.zip if no checkpoints
  python watch_trained.py trained/<tag>_ppo     # an explicit path also works
  python watch_trained.py <tag> --dr-terrain 0.03   # force the obstacle course + full DR
  python watch_trained.py <tag> --dr-push 0.35      # with random shoves

Auto-detects the observation width the checkpoint expects and sets
TERRAIN_FEATURE / GOAL_MODE / CLIFF so the env matches -- works for any run
without knowing its G2E_* config. Any --dr-* flag forces full-strength
randomization (dr = 1) every episode.
"""
import argparse
import glob
import os
import re
import time
import zipfile

ap = argparse.ArgumentParser()
ap.add_argument("checkpoint", nargs="?", default="trained/smoke_test_ppo")
ap.add_argument("--dr-friction", type=float, default=None)
ap.add_argument("--dr-mass", type=float, default=None)
ap.add_argument("--dr-gyro", type=float, default=None)
ap.add_argument("--dr-push", type=float, default=None)
ap.add_argument("--dr-terrain", type=float, default=None)
args = ap.parse_args()


def _resolve(arg):
    """Accept an explicit path or a bare run tag -> newest checkpoint / final."""
    if os.path.exists(arg) or os.path.exists(arg + ".zip"):
        return arg
    cks = sorted(glob.glob(f"trained/checkpoints/{arg}_*_steps.zip"), key=os.path.getmtime)
    if cks:
        return cks[-1][:-4]
    for cand in (f"trained/{arg}", f"trained/{arg}_ppo"):
        if os.path.exists(cand + ".zip"):
            return cand
    return arg  # let PPO.load raise a clear error


def _ckpt_obs_dim(path):
    p = path if path.endswith(".zip") else path + ".zip"
    try:
        with zipfile.ZipFile(p) as z:
            raw = z.read("data").decode("utf-8", "replace")
        m = re.search(r'observation_space.*?_shape.*?\[\s*(\d+)', raw, re.S)
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


args.checkpoint = _resolve(args.checkpoint)
print(f"replaying {args.checkpoint}")

import opencat_gym_env
opencat_gym_env.GUI_MODE = True

# feature-flag the env to match the checkpoint's observation width
_od = _ckpt_obs_dim(args.checkpoint)
if _od:
    _extra = _od - opencat_gym_env.SIZE_OBSERVATION
    _map = {0: (0, 0, 0), 4: (1, 0, 0), 7: (1, 0, 1), 8: (1, 1, 0), 11: (1, 1, 1)}
    _t, _g, _c = _map.get(_extra, (1 if _extra >= 4 else 0, 0, 0))
    opencat_gym_env.TERRAIN_FEATURE = bool(_t)
    opencat_gym_env.GOAL_MODE = bool(_g)
    opencat_gym_env.CLIFF = bool(_c)
    print(f"obs {_od} (+{_extra}) -> TERRAIN_FEATURE={bool(_t)} GOAL_MODE={bool(_g)} CLIFF={bool(_c)}")
_dr = {"RANDOM_FRICTION": args.dr_friction, "RANDOM_MASS": args.dr_mass,
       "RANDOM_GYRO": args.dr_gyro, "RANDOM_PUSH": args.dr_push,
       "RANDOM_TERRAIN": args.dr_terrain}
if any(v is not None for v in _dr.values()):
    for k, v in _dr.items():
        if v is not None:
            setattr(opencat_gym_env, k, v)
    opencat_gym_env.DR_EVAL_FULL = True
    print("replay with DR forced on:", {k: getattr(opencat_gym_env, k) for k in _dr})
from opencat_gym_env import OpenCatGymEnv

# Connect to the GUI (env's __init__ calls p.connect) before importing
# stable_baselines3/torch -- doing it after causes PyBullet's macOS Metal GUI
# thread to fail silently ("Not connected to physics server" on first step).
env = OpenCatGymEnv()
obs, info = env.reset()

from stable_baselines3 import PPO
model = PPO.load(args.checkpoint)

import pybullet

try:
    while True:
        action, _state = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        time.sleep(1 / 60)
        if terminated or truncated:
            obs, info = env.reset()
except (KeyboardInterrupt, pybullet.error):
    pass  # Ctrl+C, or the GUI window was closed
finally:
    try:
        env.close()
    except pybullet.error:
        pass
