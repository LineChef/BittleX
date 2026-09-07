#!/bin/bash
# Replay the Phase D A/B run in the PyBullet GUI -- the latest checkpoint while
# training, or the final policy once done. Sets the same course/env config the
# run trains on so the terrain shows up and the (282-d vision / 278-d blind)
# observation matches.
#
#   ./watch_ab.sh              # abD_vision, latest checkpoint
#   ./watch_ab.sh blind        # abD_blind, latest checkpoint
#   ./watch_ab.sh vision final # the finished abD_vision_ppo
#
# Must be run from your own terminal -- the GUI window won't open from a
# detached/background process. Uses CPU it would otherwise give to training,
# so the run's clock stretches a little while the window is open (harmless).
set -u
cd "$(dirname "$0")"
WHICH="${1:-vision}"
MODE="${2:-latest}"
PY=../../.venv/bin/python

if [ "$MODE" = "final" ]; then
  CKPT="trained/abD_${WHICH}_ppo"
else
  CKPT=$(ls -t trained/checkpoints/abD_${WHICH}_*_steps.zip 2>/dev/null | head -1)
  CKPT="${CKPT%.zip}"
fi
[ -n "$CKPT" ] && [ -e "${CKPT}.zip" ] || { echo "no checkpoint for abD_${WHICH} yet"; exit 1; }
echo "replaying $CKPT"

VIS=1; [ "$WHICH" = "blind" ] && VIS=0

env G2E_TERRAIN_FEATURE=$VIS \
    G2E_FAC_NOSTALL=22 G2E_FAC_NOSTALL_BONUS=8 G2E_FAC_IMITATION=5 \
    G2E_RANDOM_TERRAIN_PROB=0.85 G2E_RANDOM_TERRAIN_MAX_H=0.09 \
    G2E_OBSTACLE_COUNT=5 G2E_OBSTACLE_TALL_FRAC=0.30 G2E_OBSTACLE_SPAN_FRAC=0.10 \
    G2E_OBSTACLE_X_HI=1.0 G2E_OBSTACLE_Y_SPREAD=0.10 \
    G2E_LEDGE_HEIGHT=0.018 G2E_LEDGE_PROB=0.35 G2E_LEDGE_RANDOMIZE=1 \
    G2E_RUBBLE_PROB=0.35 G2E_SLOPE_MAX_DEG=10 \
  "$PY" watch_trained.py "$CKPT" --dr-terrain 0.06

