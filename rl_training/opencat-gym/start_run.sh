#!/usr/bin/env bash
# Kick off an RL training run with one command, running the full pre-run checklist.
#
#   ./start_run.sh v7                  # 2M-step run -> trained/v7_ppo.zip, new PPO_N
#   ./start_run.sh v7 --steps 20000    # short run (extra args pass through to train.py)
#   ./start_run.sh v7 --force          # allow reusing a tag (overwrites v7's files)
#
# Checklist, in order:
#   1. Require a tag, and reject one that's already been used (would overwrite).
#   2. Refuse to start if a training run is already in progress.
#   3. Warn about lingering PyBullet viewer windows (they slow training).
#   4. Warn if opencat_gym_env.py / train.py have uncommitted changes and no
#      smoke test was run since.
#   5. Start TensorBoard (if needed) and open it in the browser.
#   6. Launch training in the background; print PID / log path / how to stop.
set -euo pipefail

cd "$(dirname "$0")"
VENV_PY="../../.venv/bin/python"
VENV_TB="../../.venv/bin/tensorboard"

# ---- parse args: first arg is the tag; pull out --force; rest go to train.py ----
TAG="${1:-}"
[ $# -gt 0 ] && shift || true
FORCE=0
PASS_ARGS=()
for a in "$@"; do
  if [ "$a" = "--force" ]; then FORCE=1; else PASS_ARGS+=("$a"); fi
done

if [ -z "$TAG" ]; then
  echo "Usage: ./start_run.sh <tag> [--steps N] [--force]"
  echo "  <tag> labels every file this run produces (trained/<tag>_ppo.zip,"
  echo "  trained/checkpoints/<tag>_*.zip, trained/<tag>_console.log)."
  echo "  Use the reward-iteration label: v7, v8, ..."
  exit 1
fi

# ---- 1. tag collision ----
if compgen -G "trained/${TAG}_ppo.zip" >/dev/null \
   || compgen -G "trained/checkpoints/${TAG}_*_steps.zip" >/dev/null \
   || [ -e "trained/${TAG}_console.log" ]; then
  if [ "$FORCE" -eq 1 ]; then
    echo "NOTE: tag '$TAG' already has files -- --force given, they will be overwritten."
  else
    echo "Tag '$TAG' has already been used:"
    ls -1 trained/${TAG}_ppo.zip trained/checkpoints/${TAG}_*_steps.zip \
          trained/${TAG}_console.log 2>/dev/null | sed 's/^/  /'
    echo "Pick a new tag, or pass --force to overwrite. Aborting."
    exit 1
  fi
fi

# ---- 2. don't stack runs (interpreter shows as ".../Python train.py", capital P) ----
if pgrep -f "[a-z_]*train\.py" >/dev/null; then
  echo "A training run is already in progress:"
  pgrep -fl "[a-z_]*train\.py" | sed 's/^/  /'
  echo "Stop it first (kill <PID>), or let it finish. Aborting."
  exit 1
fi

# ---- 3. lingering GUI viewers ----
if pgrep -f "watch_trained.py|view_sim.py" >/dev/null; then
  echo "WARNING: a PyBullet viewer window is still open and will slow training:"
  pgrep -fl "watch_trained.py|view_sim.py" | sed 's/^/  /'
  read -r -p "Kill it and continue? [y/N] " ans
  [ "$ans" = "y" ] && pkill -f "watch_trained.py|view_sim.py" || { echo "Aborting."; exit 1; }
fi

# ---- 4. smoke-test reminder if the training code has uncommitted edits ----
if command -v git >/dev/null && \
   ! git diff --quiet -- opencat_gym_env.py train.py 2>/dev/null; then
  echo "NOTE: opencat_gym_env.py / train.py have uncommitted changes."
  echo "      If you haven't already, run a smoke test first:  $VENV_PY smoke_train.py"
  read -r -p "Continue with the full run anyway? [y/N] " ans
  [ "$ans" = "y" ] || { echo "Aborting."; exit 1; }
fi

# ---- 5. TensorBoard ----
if ! pgrep -f "tensorboard.*tensorboard_logs" >/dev/null; then
  nohup "$VENV_TB" --logdir trained/tensorboard_logs/ --port 6006 \
        > trained/tensorboard.log 2>&1 &
  echo "TensorBoard started -> http://localhost:6006/"
  sleep 5
else
  echo "TensorBoard already up -> http://localhost:6006/"
fi
open "http://localhost:6006/" 2>/dev/null || true

# ---- 6. launch ----
LOG="trained/${TAG}_console.log"
nohup "$VENV_PY" train.py --tag "$TAG" "${PASS_ARGS[@]}" > "$LOG" 2>&1 &
PID=$!
sleep 3
if ! kill -0 "$PID" 2>/dev/null; then
  echo "Training process exited immediately -- check the log:"
  tail -20 "$LOG" | sed 's/^/  /'
  exit 1
fi
echo "Training started (PID $PID)"
echo "  tag:    $TAG"
echo "  log:    $(pwd)/$LOG"
echo "  follow: tail -f $LOG"
echo "  stop:   kill $PID"
echo
echo "Next: when it finishes (~40 min), replay it with  g2watch  and log the"
echo "result + curve in docs/project-plan.md before starting the next run."
