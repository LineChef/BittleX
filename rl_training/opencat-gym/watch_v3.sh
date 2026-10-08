#!/bin/bash
# Watch the V3 run in the PyBullet GUI: the newest checkpoint of a run, in the same hardware world it trains in (the G2 profile: measured IMU, case2 payload, servo rate, command timing).
#   ./watch_v3.sh                 # newest trained/checkpoints/v3_20m_*_steps.zip
#   ./watch_v3.sh v3_20m --dr-push 0.35     # extra args go to watch_trained.py (random shoves, rough terrain, ...)
#   ./watch_v3.sh v3_k3           # another run's newest checkpoint, or its final policy
#   ./watch_v3.sh v3_20m --course # also switch on the course the 20M trains on: surface steps, snag obstacles and ledges (the plain replay is the calm scoring world: a flat floor)
# Run it from your own terminal (the GUI window does not open from a background process). It takes CPU from the training while the window is open, so the run's clock stretches a little.
set -u
cd "$(dirname "$0")"
PY=../../.venv/bin/python
TAG="${1:-v3_20m}"
eval "$($PY -c "import g2_profile as G; print('; '.join(f'export {k}={v}' for k, v in G.scoring_env('mirror').items()))")"
ARGS=()
for a in "${@:2}"; do
  if [ "$a" = "--course" ]; then
    eval "$($PY -c "import g2_profile as G; print('; '.join(f'export {k}={v}' for k, v in G.stage_extra('s6_full_strength', ('mirror',)).items() if k.startswith(('G2E_SURFACE_', 'G2E_SNAG_', 'G2E_LEDGE_'))))")"
  else
    ARGS+=("$a")
  fi
done
exec "$PY" watch_trained.py "$TAG" ${ARGS[@]+"${ARGS[@]}"}
