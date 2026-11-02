#!/bin/bash
# Supervisor for the sim training (2026-11-02): keeps train.py running until it writes DONE (a crash, a kill or a reboot-resume just restarts it; state is checkpointed every generation).
#   nohup caffeinate -i bash tools/sim_train/run.sh ~/g2_sim_train/run_X [--search --base RUN_A] >/dev/null 2>&1 &
RUN="${1:?run dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"; mkdir -p "$RUN"
tries=0
until [ -f "$RUN/DONE" ] || [ "$tries" -ge 50 ]; do
  tries=$((tries+1)); echo "$(date '+%H:%M:%S') start $tries" >> "$RUN/supervisor.log"
  "$ROOT/.venv/bin/python" "$HERE/train.py" "$RUN" "${@:2}" >> "$RUN/stdout.log" 2>&1
  echo "$(date '+%H:%M:%S') exited $?" >> "$RUN/supervisor.log"; sleep 5
done
