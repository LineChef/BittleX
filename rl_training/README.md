# RL Training

Simulation-based reinforcement learning for the walking gait: PyBullet + Stable-Baselines3 (PPO) + Gymnasium.

## `opencat-gym/`

A curated copy of [ger01d/opencat-gym](https://github.com/ger01d/opencat-gym) (MIT license, commit `12b39ff`), which already targets our exact hardware — `models/bittle_esp32.urdf` is a Bittle/BiBoard (ESP32) model. Only the source files are vendored here; the upstream repo's demo GIFs and pretrained checkpoint files were left out to keep this repo lean (checkpoints you train yourself go in `trained/`, which is gitignored).

- `opencat_gym_env.py` — the Gymnasium environment (reward function constants live here)
- `train.py` — trains a PPO agent (`python train.py`)
- `enjoy.py` — runs a saved policy
- `opencat-gym.ipynb` — same workflow as a notebook
- `models/bittle_esp32.urdf` — the simulated robot model

## Setup

Requires Python >= 3.10 (this project uses a `.venv` built with Homebrew's `python@3.11`, since macOS ships an EOL 3.8).

```
python3.11 -m venv .venv
source .venv/bin/activate
CPPFLAGS="-Dfdopen=fdopen" pip install -r requirements.txt
```

The `CPPFLAGS` workaround is required on macOS: `pybullet` has no prebuilt wheel for macOS (only Linux) and must compile from C++ source, which otherwise fails against current macOS SDKs due to a decades-old zlib/`fdopen` macro bug bundled in pybullet's vendored zlib copy.

Verify the environment works:

```
python -c "
from stable_baselines3.common.env_checker import check_env
from opencat_gym_env import OpenCatGymEnv
env = OpenCatGymEnv()
check_env(env)
env.reset()
print('OK')
"
```

(Run from inside `rl_training/opencat-gym/`, since `train.py`/`enjoy.py` import `opencat_gym_env` as a local module.)
