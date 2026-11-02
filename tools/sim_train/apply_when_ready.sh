#!/bin/bash
# Waits for the sim training to finish (DONE), then applies the recommended values to G2 as soon as the Pi is on and idle (retries every 2 minutes for up to 24 hours). tools/sim_train/apply.py has the rules.
RUN="${1:?run dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
until [ -f "$RUN/DONE" ]; do sleep 30; done
for i in $(seq 1 720); do
  [ -f "$RUN/APPLIED" ] && exit 0
  "$ROOT/.venv/bin/python" "$HERE/apply.py" "$RUN" >> "$RUN/apply.log" 2>&1; rc=$?
  echo "$(date '+%H:%M:%S') apply exit $rc" >> "$RUN/apply.log"
  [ "$rc" = 0 ] || [ "$rc" = 1 ] && exit "$rc"
  sleep 120
done
