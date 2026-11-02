#!/bin/bash
# Waits for a sim training run (DONE), then, as soon as the Pi is on and idle: deploys the current code to it (the recommended settings may include settings only the new code has) and applies the
# recommended values (tools/sim_train/apply.py: backup first, revert command). Retries every 2 minutes for up to 24 hours.
RUN="${1:?run dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
until [ -f "$RUN/DONE" ]; do sleep 30; done
for i in $(seq 1 720); do
  [ -f "$RUN/APPLIED" ] && exit 0
  if bash "$ROOT/tools/g2_deploy_when_online.sh" --once >> "$RUN/apply.log" 2>&1; then
    "$ROOT/.venv/bin/python" "$HERE/apply.py" "$RUN" >> "$RUN/apply.log" 2>&1; rc=$?
    echo "$(date '+%H:%M:%S') deployed, apply exit $rc" >> "$RUN/apply.log"
    { [ "$rc" = 0 ] || [ "$rc" = 1 ]; } && exit "$rc"
  else
    echo "$(date '+%H:%M:%S') Pi not reachable or busy: retrying" >> "$RUN/apply.log"
  fi
  sleep 120
done
