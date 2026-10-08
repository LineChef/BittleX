#!/bin/bash
# Watch the V3 run in the PyBullet GUI: the newest checkpoint of a run, in the same hardware world it trains in (the G2 profile: measured IMU, case2 payload, servo rate, command timing).
#   ./watch_v3.sh                 # newest trained/checkpoints/v3_20m_*_steps.zip
#   ./watch_v3.sh v3_k3           # another run's newest checkpoint, or its final policy
#   ./watch_v3.sh v3_20m --deterministic   # the policy as DEPLOYED (no exploration noise); the default samples actions the way training does
# What you see is what trains: the environment is the run's own training environment (g2_profile.env_for_job, the function the training launch uses), the difficulty levels and the
# ramp position are the run's current ones (read from its console log), and episodes are drawn by the same sampler (easy, combo and focus episodes). There is no calm or reduced mode.
# To watch the actual episodes training met, record them (G2E_RECORD_EVERY, on by default for new runs) and use watch_training.py.
# Run it from your own terminal (the GUI window does not open from a background process). It takes CPU from the training while the window is open, so the run's clock stretches a little.
set -u
cd "$(dirname "$0")"
PY=../../.venv/bin/python
TAG="${1:-v3_20m}"
eval "$($PY watch_env.py "$TAG")" || exit 1
export G2_WATCH_TAG="$TAG"
exec "$PY" watch_trained.py "$TAG" "${@:2}"
