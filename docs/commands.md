# Command Reference

Every runnable command in this project, with the full step sequence for each so
nothing gets missed when running them by hand. When you want me (Claude) to run
one, point at it by name — e.g. "run the smoke test from `docs/commands.md`" or
"start a run, tag v8".

Status: only the RL training system (Phase 3) has code so far. `pi_pipeline/`
(voice / memory / vision) has no commands yet — this file grows as those land.

---

## TL;DR — the ones you'll actually use

| I want to… | Command |
|---|---|
| Start a training run | `g2train v8` |
| Watch the newest trained policy walk | `g2watch` |
| Quick check the pipeline isn't broken (~90s) | `cd rl_training/opencat-gym && ../../.venv/bin/python smoke_train.py` |
| See training curves | opens automatically with `g2train`; else `open http://localhost:6006/` |
| Stop a run | `kill <PID>` (printed at launch) or `pkill -f train.py` |

`g2train` / `g2watch` are shell functions in `~/.bash_profile`. After editing that
file, run `source ~/.bash_profile` or open a new terminal before they work.

Common rules for everything in `rl_training/opencat-gym/`:

- **Run from that directory.** The scripts import `opencat_gym_env` locally and
  load `models/` by relative path. Running from anywhere else fails.
- **Use the project venv** — either `source .venv/bin/activate` (from the repo
  root) once per shell, or call the interpreter as `../../.venv/bin/python`
  (what the examples below do).
- **Every run needs its own unique `<tag>`.** The tag names `trained/<tag>_ppo.zip`,
  `trained/checkpoints/<tag>_<steps>_steps.zip`, and `trained/<tag>_console.log`.
  Reusing a tag overwrites the earlier run. Convention: the reward-iteration
  label — `v6`, `v7`, `v8`, … The TensorBoard run (`PPO_N`) numbers itself.

---

## RL training

### Start a training run — the full procedure

**The easy path:** `g2train <tag>` (e.g. `g2train v8`). It runs every step below
for you — steps 1–5 as automated checks, step 6 as the launch — and stops with a
clear message if any check fails. `/train <tag>` in Claude Code does the same.

**If you run it by hand** (not using `start_run.sh` / `g2train`), do these in order:

1. **Pick a new, unique tag.** Check it hasn't been used:
   ```bash
   cd rl_training/opencat-gym
   ls trained/ | grep <tag>          # expect: no output
   ```
   If anything prints, pick a different tag (or you'll overwrite that run).
2. **Confirm no run is already going** — only one at a time (they'd fight for CPU):
   ```bash
   pgrep -fl train.py                # expect: no output
   ```
3. **Close any sim viewer windows** — an open `watch_trained.py` / `view_sim.py`
   steals CPU and slows training:
   ```bash
   pgrep -fl "watch_trained.py|view_sim.py"      # expect: no output
   pkill -f "watch_trained.py|view_sim.py"       # if it found any
   ```
4. **Smoke-test first if you changed `opencat_gym_env.py` or `train.py`:**
   ```bash
   ../../.venv/bin/python smoke_train.py         # ~90s; reward ~40–55, no NaN
   ```
5. **Start TensorBoard** (skip if already running) and open it:
   ```bash
   pgrep -f "tensorboard.*tensorboard_logs" || \
     nohup ../../.venv/bin/tensorboard --logdir trained/tensorboard_logs/ --port 6006 \
       > trained/tensorboard.log 2>&1 &
   open http://localhost:6006/
   ```
6. **Launch the run** (background, logging to a file named by the tag):
   ```bash
   nohup ../../.venv/bin/python train.py --tag <tag> > trained/<tag>_console.log 2>&1 &
   echo "PID $!"                     # write this down — it's how you stop the run
   ```
   Add `--steps 20000` for a short test run.
7. **Verify it actually started** (wait ~20s, then):
   ```bash
   tail -n 20 trained/<tag>_console.log
   ```
   You want to see `Logging to trained/tensorboard_logs/PPO_N`, `ep_rew_mean` a
   real number (not `nan`), and `fps` in the hundreds. If the process died, the
   error is at the bottom of that log.
8. **While it runs** (~2M steps, ~40 min here): `tail -f trained/<tag>_console.log`
   or watch the `PPO_N` curve at http://localhost:6006/.
9. **When it finishes:** replay it (`g2watch`), then record the result — final
   reward, episode length, curve shape, and what the replay looked like — as a new
   bullet under Phase 3 in `docs/project-plan.md`. Decide the next tweak before
   starting the next run.

### `start_run.sh` flags

| Command | Effect |
|---|---|
| `./start_run.sh v8` | Normal run (from `rl_training/opencat-gym/`) |
| `./start_run.sh v8 --steps 20000` | Short run — extra args pass straight to `train.py` |
| `./start_run.sh v8 --force` | Allow a tag whose files already exist (overwrites them) |
| `./start_run.sh` | No tag → prints usage and exits (this is intentional) |

### Continue an existing run (no reward-function change)

```bash
cd rl_training/opencat-gym
# 1. Edit continue_train.py first — the source checkpoint and output name are
#    hardcoded near the top (currently trained/full_run_v1_ppo -> full_run_v1_continued).
#    It has NO command-line args.
# 2. Same pre-flight as a fresh run: no run active, no viewers open.
pgrep -fl train.py
# 3. Launch.
nohup ../../.venv/bin/python continue_train.py > trained/<name>_console.log 2>&1 &
```

Trains 2M more steps with `reset_num_timesteps=False` so the TensorBoard curve
continues from where the source run stopped. Use this only when the reward
function is unchanged; a reward change gets a fresh `g2train` run instead.

### Watch / evaluate a trained policy

| Command | What it does |
|---|---|
| `g2watch` | Replays the **newest** `trained/*_ppo.zip` in the PyBullet GUI (deterministic) |
| `g2watch trained/v6_ppo` | Replay a specific checkpoint (omit the `.zip`) |
| `cd rl_training/opencat-gym && ../../.venv/bin/python watch_trained.py trained/<tag>_ppo` | The script directly |
| `cd rl_training/opencat-gym && ../../.venv/bin/python view_sim.py` | Opens the sim with **random** actions — sanity-checks the model/physics, not a gait |

Close the GUI window or Ctrl+C to stop. **Don't leave a viewer open during a
training run.** `enjoy.py` is stale upstream code (loads a path that doesn't exist
here) — use `watch_trained.py` / `g2watch`.

### "Tests"

There is **no test suite or linter.** The closest things, run from
`rl_training/opencat-gym/`:

| Command | What it verifies | Pass looks like |
|---|---|---|
| `../../.venv/bin/python smoke_train.py` | Whole training pipeline end-to-end at 20K steps (~90s): env, PPO loop, logging, checkpoint save | Reward ~40–55, no `nan`, prints "Saved smoke test checkpoint" |
| `../../.venv/bin/python -c "from stable_baselines3.common.env_checker import check_env; from opencat_gym_env import OpenCatGymEnv; check_env(OpenCatGymEnv()); print('OK')"` | The Gym env's spaces / shapes / return types are valid | Prints `OK` with no warnings |

Run the smoke test after any edit to `opencat_gym_env.py` or `train.py`, before a
full run. (`start_run.sh` reminds you if those files have uncommitted changes.)

### TensorBoard

| Command | What it does |
|---|---|
| `open http://localhost:6006/` | Open the dashboard |
| `cd rl_training/opencat-gym && ../../.venv/bin/tensorboard --logdir trained/tensorboard_logs/ --port 6006` | Start the server manually |
| `pkill -f "tensorboard.*tensorboard_logs"` | Stop it |

Runs appear as `PPO_1`, `PPO_2`, … in load order — `docs/project-plan.md` records
which `PPO_N` is which reward-function version.

### Managing running processes

| Command | What it does |
|---|---|
| `pgrep -fl train.py` | Is a training run active? (PID + command) |
| `kill <PID>` | Stop a specific run (PID printed at launch) |
| `pkill -f train.py` | Stop any/all training runs |
| `pkill -f "watch_trained.py\|view_sim.py"` | Close stray GUI viewer windows |
| `ps aux \| grep -iE "python\|pybullet\|tensorboard" \| grep -v grep` | Everything related that's running |

---

## Environment setup (one-time)

From the repo root:

```bash
python3.11 -m venv .venv                                  # Homebrew python@3.11; macOS system Python is too old
source .venv/bin/activate
CPPFLAGS="-Dfdopen=fdopen" pip install -r requirements.txt # CPPFLAGS is mandatory on macOS (pybullet zlib build bug)
```

Then verify with the `check_env` one-liner under [Tests](#tests).

---

## Not yet — placeholders

- `pi_pipeline/voice/` — speech-to-text → Claude API → text-to-speech (no code yet)
- `pi_pipeline/memory/` — persistent conversation store (no code yet)
- `pi_pipeline/vision/` — camera / obstacle avoidance (no code yet)
- Sim-to-real deployment (`ger01d/opencat-gym-sim2real`) — Phase 6, not set up yet
