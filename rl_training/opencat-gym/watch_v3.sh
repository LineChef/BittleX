#!/bin/bash
# Watch the V3 run in the PyBullet GUI: the newest checkpoint of a run, in the same hardware world it trains in (the G2 profile: measured IMU, case2 payload, servo rate, command timing).
#   ./watch_v3.sh                 # newest trained/checkpoints/v3_20m_*_steps.zip
#   ./watch_v3.sh v3_20m --dr-push 0.35     # extra args go to watch_trained.py (random shoves, rough terrain, ...)
#   ./watch_v3.sh v3_k3           # another run's newest checkpoint, or its final policy
#   ./watch_v3.sh v3_20m --calm   # the calm scoring world instead: a flat floor with no steps, snags or ledges (what the benchmark cells start from)
# By default the replay shows the course the run trains on (surface steps, snag obstacles and ledges at difficulty level 1.0, hard levels x1.10), so you see what the policy is actually handling.
# Run it from your own terminal (the GUI window does not open from a background process). It takes CPU from the training while the window is open, so the run's clock stretches a little.
set -u
cd "$(dirname "$0")"
PY=../../.venv/bin/python
TAG="${1:-v3_20m}"
MODE=course
ARGS=()
for a in "${@:2}"; do
  if [ "$a" = "--calm" ]; then MODE=calm; elif [ "$a" = "--course" ]; then MODE=course; else ARGS+=("$a"); fi
done
eval "$($PY watch_env.py "$MODE")"
exec "$PY" watch_trained.py "$TAG" ${ARGS[@]+"${ARGS[@]}"}
