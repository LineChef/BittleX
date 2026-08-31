# Command Cheat Sheet

Curated quick-reference. Add to it by telling me "add this to the cheat sheet".
For the exhaustive reference (every script, all flags, setup), see
[`docs/reference/commands.md`](commands.md).

Shell helpers (`g2train`, `g2watch`) live in `~/.bash_profile` — `source ~/.bash_profile`
or open a new terminal to pick them up. RL commands run from `rl_training/opencat-gym/`.

---

## Training / the automated loop

| Command | Does |
|---|---|
| `g2train <tag>` | Start a training run (checklist, TensorBoard, background). e.g. `g2train v9` |
| `python train.py --tag <tag> --steps 2000000` | Run directly (from `rl_training/opencat-gym/`, venv active) |
| `python train.py --tag <tag> --from trained/<ckpt>_ppo --steps 1000000` | Finetune from a checkpoint (note: diverged in Run 5 — use fresh) |
| `touch rl_training/opencat-gym/STOP` | Ask the automated loop to stop cleanly after the current iteration |
| `pgrep -fl "train.py"` | Is a training run active? (shows PID) |
| `pkill -f "train.py"` | Stop all training runs |
| `tail -f rl_training/opencat-gym/trained/<tag>_console.log` | Watch a run's live SB3 output |

## Watching a policy

| Command | Does |
|---|---|
| `g2watch` | Opens a PyBullet GUI window and **deterministically replays a trained policy's gait**, episode after episode on a loop, so you can watch how it actually walks. With no argument it uses the newest `trained/*_ppo.zip`. Shell function in `~/.bash_profile`; `cd`s into `rl_training/opencat-gym` and runs `watch_trained.py`. Ctrl+C or close the window to stop. |
| `g2watch trained/<tag>_ppo` | Same, for a specific saved policy (omit the `.zip`) — e.g. `g2watch trained/phase3-gait_ppo` |
| `g2watch trained/checkpoints/<tag>_<N>_steps` | Replay a mid-training snapshot (checkpoints save every ~200K steps) — watch the gait as it was partway through a run |
| `python watch_trained.py trained/<ckpt> --dr-terrain 0.012` | Replay on the 12 mm obstacle course (full DR) |
| `python watch_trained.py trained/<ckpt> --dr-push 0.35` | Replay with random shoves |
| `pkill -f watch_trained.py` | Close the replay window |

## TensorBoard

| Command | Does |
|---|---|
| `open http://localhost:6006/` | Open the dashboard (started automatically by `g2train`) |
| `python -m tensorboard.main --logdir trained/tensorboard_logs/ --port 6006` | Start it manually |
| `pkill -f "tensorboard.*tensorboard_logs"` | Stop it |

Run → `PPO_N` mapping is in the per-run logs (`docs/auto-iteration-log*.md`).

## Evaluating a policy (headless)

| Command | Does |
|---|---|
| `python evaluate_policy.py trained/<ckpt> --episodes 8` | Metrics: speed, yaw drift, trot corr, stride, startup ratio, foot clearance |
| `... --frames-dir eval_frames/<name>` | Also render ~30 frames for visual inspection |
| `... --dr-friction 0` | Force a flat (no-DR) run — any `--dr-*` zeroes all knobs, then applies what you pass |
| `... --dr-terrain 0.012` | Grade on the obstacle course |
| `... --dr-push 0.35` / `--dr-friction 0.3` / `--dr-mass 0.15` / `--dr-gyro 0.02` | Grade on a single held-out disturbance |
| `python render_gif.py trained/<ckpt> out.gif --steps 250 --stride 2` | Render one episode to an animated GIF |

## wkF reference gait (imitation reward)

| Command | Does |
|---|---|
| `python reference_gait/build_wkf_reference.py` | Rebuild `wkf_ref.npy` from `InstinctBittleESP.h` |
| `python reference_gait/verify_wkf_reference.py` | Score sign/mirroring variants by open-loop forward walk |
| `python reference_gait/verify_wkf_reference.py identity --render` | Render the open-loop reference playback to a GIF |

## Git landmarks

| Command | Does |
|---|---|
| `git checkout gait-v6-known-good -- rl_training/opencat-gym/opencat_gym_env.py` | Restore the pre-loop v6 reward function |
| `git checkout phase3-gait -- rl_training/opencat-gym/opencat_gym_env.py` | Restore the locked Phase 3 gait config |
| `g2watch trained/phase3-gait_ppo` | Replay the locked Phase 3 gait |
| `git for-each-ref refs/backup/` | Pre-history-rewrite backup refs |

## Quick checks

| Command | Does |
|---|---|
| `ps aux \| grep -iE "python\|pybullet\|tensorboard" \| grep -v grep` | Everything RL-related that's running |
| `../../.venv/bin/python smoke_train.py` | ~90 s pipeline sanity check (reward ~40–60, no NaN) |
