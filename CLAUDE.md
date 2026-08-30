# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A Petoi Bittle X quadruped robot (referred to as **G2**) that learns to walk via
reinforcement learning, perceives its environment through an onboard AI camera, holds
voice conversations powered by the Claude API, and builds persistent memory across
conversations. Full context, hardware list, and the phased roadmap live in
`docs/project-plan.md` — that file is a **living log**: read it before starting work
in an area, and keep it updated as decisions and steps land.

The builder has a web dev (HTML/JS/CSS) background and no prior Python experience —
favor explaining Python idioms in terms of JS/CSS analogues when relevant, and keep
in mind this is their first hardware/robotics project.

## Current State

- **Phase 3 (RL training in simulation) is the active work.** Real hardware has not
  arrived yet; everything so far is software-only.
- `rl_training/opencat-gym/` has a working PyBullet + Stable-Baselines3 training
  pipeline. Reward-function iteration is ongoing (runs v1–v6 documented in
  `docs/project-plan.md`); trained checkpoints and TensorBoard logs are gitignored.
- `pi_pipeline/` is still just READMEs — no code yet.

## RL Training — Commands

`docs/commands.md` is the full runnable-command reference (training, watching,
tests, TensorBoard, process management, setup). The essentials:

All commands run **from inside `rl_training/opencat-gym/`** (the scripts import
`opencat_gym_env` as a local module and load `models/` by relative path), with the
project venv active:

```
source .venv/bin/activate          # venv lives at repo root; Homebrew python@3.11
cd rl_training/opencat-gym
```

| Task | Command |
|---|---|
| Install deps (macOS) | `CPPFLAGS="-Dfdopen=fdopen" pip install -r requirements.txt` |
| Sanity-check the env | `python -c "from stable_baselines3.common.env_checker import check_env; from opencat_gym_env import OpenCatGymEnv; check_env(OpenCatGymEnv()); print('OK')"` |
| Smoke test the pipeline (~20K steps, ~25s) | `python smoke_train.py` |
| **Start a full run (preferred)** | `./start_run.sh <tag>` — e.g. `./start_run.sh v7`; runs the pre-run checklist, starts TensorBoard, launches training in the background |
| Full training run (direct) | `python train.py --tag <label> [--steps N]` (2M steps, ~40 min here) |
| Continue an existing checkpoint | `python continue_train.py` |
| Replay a checkpoint in the GUI (deterministic) | `python watch_trained.py trained/<tag>_ppo` |
| View the sim with random actions | `python view_sim.py` |
| TensorBoard | `tensorboard --logdir trained/tensorboard_logs/` (http://localhost:6006/) |

There is **no test suite / linter** — the `check_env` one-liner above is the closest
thing to a test.

Every run needs a unique `--tag` (or `start_run.sh` arg): it names
`trained/<tag>_ppo.zip` and the `trained/checkpoints/<tag>_*_steps.zip` files, so
re-using a tag overwrites a previous run. The TensorBoard run (`PPO_N`)
auto-increments on its own. Shell helpers `g2train` / `g2watch` (in `~/.bash_profile`)
and the `/train <tag>` Claude Code slash command wrap `start_run.sh`.

The `CPPFLAGS="-Dfdopen=fdopen"` workaround is mandatory on macOS: `pybullet` has no
macOS wheel and must compile from source, where a bundled zlib `fdopen` macro
otherwise breaks the build.

## RL Training — Architecture

**Vendored upstream.** `rl_training/opencat-gym/` is a curated copy of
[`ger01d/opencat-gym`](https://github.com/ger01d/opencat-gym) (commit `12b39ff`,
source only). Files added locally for this project state so in their module
docstring: `smoke_train.py`, `continue_train.py`, `watch_trained.py`, `view_sim.py`.
`enjoy.py` is upstream and **stale** (loads a `trained/trained_agent_PPO` path that
doesn't exist here) — use `watch_trained.py` instead.

**`opencat_gym_env.py`** is the whole environment and the primary lever:

- **Action space**: 8 continuous values in `[-1, 1]` = per-step deltas (scaled by
  `STEP_ANGLE`) to the 8 walking joints (shoulder/elbow ×2 front, hip/knee ×2 rear).
- **Observation space** (`SIZE_OBSERVATION` = `30*8 + 6 + 1` = 247): 30-step joint-angle
  history + base quaternion + clipped angular velocity (roll/pitch) + a cyclical
  time/phase signal. Yaw rate is *penalized* but deliberately not in the observation.
- **Reward** is a weighted sum of terms, all tuned via the `FAC_*` module constants at
  the top of the file. Most penalty terms are scaled by
  `penalty_scale = step_counter_session / PENALTY_STEPS`, so they ramp in over
  training; `FAC_MOVEMENT` and `FAC_GAIT_SYMMETRY` are applied unramped. `step()`
  returns a per-term breakdown in its `info` dict (`r_movement`, `r_gait_symmetry`,
  …) so behavior changes can be traced to a specific term.
- **Dead constants**: of the randomization knobs, only `RANDOM_JOINT_ANGS` is wired
  in. `RANDOM_GYRO`, `RANDOM_MASS`, `RANDOM_FRICTION` are declared but unused —
  setting them does nothing.
- `GUI_MODE` is a **module-level global**, not a constructor arg. The GUI scripts set
  `opencat_gym_env.GUI_MODE = True` *before* importing `OpenCatGymEnv`, and connect
  PyBullet before importing `stable_baselines3`/`torch` (doing it after makes
  PyBullet's macOS Metal GUI thread fail silently).

**`train.py`**: 8 parallel `SubprocVecEnv`s, PPO `MlpPolicy` with `net_arch=[256,256]`,
linear LR decay (`linear_schedule(3e-4)`), `CheckpointCallback` every ~200K steps to
`trained/checkpoints/`. Each full run should save to `trained/full_run_v<N>_ppo` and
log to a fresh `PPO_<N>` TensorBoard run (bump the `name_prefix` and
`model.save(...)` path per run).

**Known recurring failure mode** (see `docs/project-plan.md` for the full history):
several early runs collapsed late in training — `approx_kl` spiking, reward crashing.
Root cause was structural (penalty-ramp timing = full training length + non-decaying
learning rate), fixed in v5 by lowering `PENALTY_STEPS` to `5e5` and adding LR decay.
Watch for this signature (`approx_kl` >> ~0.1, reward crash) in any new run.

**Training-run workflow** (also captured in memory): before starting a run, kill any
lingering `python`/PyBullet processes (a forgotten `watch_trained.py` window will eat
CPU and slow training); open TensorBoard when a run starts; on completion, replay the
result visually with `watch_trained.py`, then analyze the reward curve and propose the
next iteration — and wait for a go-ahead before launching it.

**Automated (unattended) iteration** is a separate workflow — when the user asks for
"automated testing" / "iterate on your own", follow `docs/automated-testing-loop.md`:
work on the `auto-gait-iteration` branch (merge `development` in first), stay
interruptible with hard caps, self-evaluate headlessly, and on wrap-up produce a
report + queue TensorBoard and a visual replay, then ask before merging to
`development`.

## Repo Structure

```
rl_training/opencat-gym/   # Phase 3 RL training (PyBullet + SB3 + Gymnasium)
pi_pipeline/
  voice/    # STT -> Claude API -> TTS          (not yet built)
  memory/   # persistent conversation storage    (not yet built)
  vision/   # camera, on-device avoidance, scene description via Claude (not yet built)
docs/       # project-plan.md — the living roadmap and decision log
```

`rl_training` and `pi_pipeline` are intentionally **independent systems** (movement,
vision, voice, memory) rather than one unified "brain" — a deliberate design choice
from the project plan. Avoid coupling them as they're built out.

## Secrets

Never commit API keys/credentials. Per `.gitignore`, secrets live in `.env`,
`config.local.*`, or files matching `**/secrets.py` / `**/api_keys.py`. Copy
`.env.example` to `.env` for real values. The Claude/Anthropic API key used in
`pi_pipeline` is billed usage-based, separate from any Claude subscription.

## Large / Local Files (gitignored — don't try to commit)

Trained checkpoints (`*.zip`, `*.pkl`, `rl_training/models/`, `rl_training/logs/`,
`**/tensorboard_logs/`) and the local conversation memory DB
(`pi_pipeline/memory/*.db`, `pi_pipeline/memory/data/`).
