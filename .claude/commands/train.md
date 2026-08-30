---
description: Start an RL training run (opencat-gym), tag passed as the argument
---

Start a new G2 RL training run.

Run tag: `$ARGUMENTS` (e.g. `v7`). If empty, ask me for the tag before starting — every run needs a unique label so checkpoints don't overwrite.

Steps:
1. `cd rl_training/opencat-gym`
2. Check for a run already in progress (`pgrep -fl "train.py"`). If one is live, report it and stop — do not stack runs.
3. Warn about any lingering `watch_trained.py` / `view_sim.py` viewer windows (they slow training).
4. Run `./start_run.sh $ARGUMENTS` — it starts TensorBoard (http://localhost:6006/) and launches training in the background.
5. Wait ~25s, then show the first `trained/$ARGUMENTS_console.log` output to confirm it's logging to a fresh `PPO_N` and reward isn't NaN.
6. Remind me: the run is ~2M steps / ~40 min, and I asked you to replay the result visually with `g2watch` / `watch_trained.py` when it finishes, then analyze before the next run.
