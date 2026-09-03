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

## Watching a policy (PyBullet GUI — run from your own terminal)

> GUI windows do **not** appear when launched from a background/detached process.
> Run these in an interactive terminal. Every run is a fresh randomised episode
> (not a loop of one recording); close the window to stop.

**`watch.py` — pick a policy + a challenge.** From `rl_training/opencat-gym/`:

| Command | Does |
|---|---|
| `python watch.py --list` | Print every challenge name |
| `python watch.py` | `run20m_ppo`, flat ground, cruise (0.10 m/s) |
| `python watch.py --challenge slope-up` | **Just one challenge** — a 12° climb. Also: `slope-up-gentle` (5°), `slope-up-steep` (15°), `slope-down` (−12°), `slope-down-steep` (−24°), `cross-slope` (5° roll) |
| `python watch.py --challenge obstacles` | 35 mm obstacle field. Also `obstacles-small` (20 mm), `obstacles-big` (50 mm), `obstacles-huge` (85 mm) |
| `python watch.py --challenge shoves` | Repeated 0.55 shoves. Also `one-shove` (single hard hit), `shoves-hard` (1.0 magnitude) |
| `python watch.py --challenge step-down` | 30 mm drop. Also `threshold-up` (15 mm), `step-up` (30 mm), `big-ledge` (45 mm random) |
| `python watch.py --challenge weak-servos` | 60% torque cutback + a −12° descent |
| `python watch.py --challenge slope+obstacles` | 9° slope + 30 mm obstacles |
| `python watch.py --challenge gauntlet` | **The hard combined test (T5.1):** 4°/9° slope + 40 mm obstacles + repeated shoves |
| `python watch.py --challenge brutal-gauntlet` | **The T6.4 hardened tier:** 20° slope + 70 mm + 1.0 shoves |
| `... --cmd 0.13` | Change the forward-speed command (creep ≈ 0.04, cruise 0.10, fast ≈ 0.14, backward < 0) |
| `... --speed 0.5` | Slow-mo (0.5×); `--speed 2` = 2× |
| `... --dr clean` | Drop the non-challenge DR (no payload). Default `payload` = the deployment config; `full` = training DR |
| `... --model trained/checkpoints/<tag>_<N>_steps` | Watch a mid-training snapshot instead of `run20m_ppo` |
| `pkill -f watch.py` | Close it (or Ctrl-C / close the window) |

**`g2watch` / `watch_trained.py` — quick "just show me the gait" (loops):**

| Command | Does |
|---|---|
| `g2watch` | GUI replay of the newest `trained/*_ppo.zip`, episode after episode. Shell fn in `~/.bash_profile`. |
| `g2watch trained/<tag>_ppo` | A specific policy — e.g. `g2watch trained/run20m_ppo` |
| `g2watch trained/checkpoints/<tag>_<N>_steps` | A mid-training snapshot |
| `python watch_trained.py trained/<ckpt> --dr-terrain 0.012` / `--dr-push 0.35` | Replay on one held-out disturbance |
| `pkill -f watch_trained.py` | Close it |

## TensorBoard

| Command | Does |
|---|---|
| `open http://localhost:6006/` | Open the dashboard (started automatically by `g2train`) |
| `python -m tensorboard.main --logdir trained/tensorboard_logs/ --port 6006` | Start it manually |
| `pkill -f "tensorboard.*tensorboard_logs"` | Stop it |

Run → `PPO_N` mapping is in the per-run logs (`docs/auto-iteration-log*.md`).

## Evaluating a policy — scored, headless

All from `rl_training/opencat-gym/`, venv active. `<ckpt>` = e.g. `trained/run20m_ppo`.

| Command | Does |
|---|---|
| `python evaluate_policy.py <ckpt> --episodes 8` | Quick metrics: speed, yaw drift, trot corr, stride, startup ratio, foot clearance |
| `... --dr-terrain 0.012` / `--dr-push 0.35` / `--dr-friction 0.3` / `--dr-mass 0.15` / `--dr-gyro 0.02` | Grade on one held-out disturbance (any `--dr-*` zeroes all knobs first) |
| `... --frames-dir eval_frames/<name>` | Also dump ~30 frames for a look |

### The decathlon — the graded easy→brutal ladder, learned vs scripted

| Command | Does |
|---|---|
| `python benchmark_decathlon.py --learned <ckpt> --episodes 24 --json-out /tmp/dec.json` | Run **all** cells T1–T7 (flat, slopes, obstacles, stumble-catch, gauntlet, T6 hardened, T7 ledge). Prints fell% / speed / cond-survival per cell |
| `... --extra-dr payload` | **Deployment config:** 75 g payload forced on, rough + torque-cutback off (the number that matters for hardware) |
| `... --extra-dr clean` | No payload / rough / cutback — cell tests exactly its label |
| `... --extra-dr full` | Training DR (payload 90%, rough 35%, cutback 40%) |
| `... --scripted-balance 0.5` | Give the scripted `wkF` baseline a gyro-balance assist (fairer comparison) |
| `... --gif-dir /tmp/dec_gifs` | Also render the gauntlet cell, learned + scripted |
| `python build_decathlon_report.py /tmp/dec.json` | Turn the JSON into an HTML report |

> No single-cell flag on the decathlon — for one challenge use `watch.py --challenge <name>`
> (visual) or `evaluate_policy.py --dr-<knob>` (scored, single knob).

### Other scored benchmarks

| Command | Does |
|---|---|
| `python benchmark_commanded.py --learned <ckpt> --episodes 16 --json-out /tmp/cmd.json` | Speed-command tracking: creep / cruise / fast / backward / stand / turn — commanded vs achieved, heading drift |
| `python benchmark_gaits.py --learned <ckpt> --episodes 28 --scripted-balance 0.5` | Head-to-head vs scripted `wkF` on flat + obstacle courses (distance, trot corr, falls) |
| `python benchmark_recovery.py <ckpt-a> <ckpt-b>` | Bare-robot stance-recovery probe (payload OFF, rough + escalating shoves) — the decathlon can't see recovery with the payload on. Compares two checkpoints |
| `python robustness_sweep.py --learned <ckpt> --seeds 16 --json-out /tmp/rob.json` | Sweep each sim-to-real axis (payload mass, cmd latency, joint offset, IMU noise, torque cutback) one at a time — where does the gait break? |
| `python render_showcase.py --learned <ckpt> --out showcase.gif` | One annotated GIF of every skill back-to-back (cruise / creep / fast / stand / shoves / slopes / gauntlet / thresholds / steps). `--scripted-balance 0.5` for the scripted version |
| `python render_gif.py <ckpt> out.gif --steps 250 --stride 2` | One episode → animated GIF |

## Deployment / sim-to-real  (see `docs/gait-deployment.md`, `docs/rl-runs/h1-head-to-head-rubric.md`)

**Mac side** (`rl_training/opencat-gym/`):

| Command | Does |
|---|---|
| `python export_onnx.py --model trained/run20m_ppo --out trained/run20m_ppo.onnx` | Export the deterministic policy to ONNX (drops value net + noise) |
| `python verify_onnx.py --model trained/run20m_ppo --onnx trained/run20m_ppo.onnx` | Parity check: ONNX vs PyTorch actions across gaussian + a real rollout |
| `python validate_deploy.py` | Drive `pi_pipeline/gait/residual_policy.py` from the sim in lockstep with `model.predict` — asserts obs + joint targets match bit-for-bit |
| `python sysid_replay.py --log <real_log.csv>` | Replay a real robot log's joint commands open-loop in a sim mirror; report the sim-to-real tilt/rate gap |
| `python sysid_replay.py --log <real_log.csv> --fit` | + sweep motor force / PD gains / `CMD_LATENCY_STEPS` to close the gap; prints the env edits |

**Pi side** (`pi_pipeline/gait/`, in a venv with onnxruntime):

| Command | Does |
|---|---|
| `python bench_real.py` | Time the real `run20m_ppo.onnx` end-to-end (ONNX + obs build) — the per-tick cost |
| `python run_gait.py --dry-run --seconds 5` | Full 80 Hz loop, synthetic IMU, no serial — rate check |
| `python run_gait.py --probe-imu` | Print raw BiBoard `V` IMU stream — check `parse_imu_line` matches the format |
| `python run_gait.py --openloop` | Play `wkf_ref.npy` open-loop (on a cradle) — verify servo signs, set `deploy_map.SERVO_SIGN` |
| `python run_gait.py --cmd 0.10` | The learned gait on the real robot (firmware balance off) |
| `python run_gait.py --cmd 0.10 --keep-firmware-balance --log run.csv` | + firmware gyro-assist underneath, logging per-tick for `sysid_replay` |
| `python sysid_collect.py --log sysid.csv` | Policy-free calibration sequence (loaded poses + slow wkF) → log for `sysid_replay` |
| `python h1_score.py --template > runs.json` then `python h1_score.py --from runs.json` | Score the H1 head-to-head from measured numbers → verdict |

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
