#!/bin/bash
# Supervisor for the sim training (2026-11-02): keeps train.py running until it writes DONE (a crash, a kill or a reboot-resume just restarts it; state is checkpointed every generation).
#   nohup caffeinate -i bash tools/sim_train/run.sh ~/g2_sim_train/run_X [--search --base RUN_A] >/dev/null 2>&1 &
RUN="${1:?run dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"; mkdir -p "$RUN"
tries=0
until [ -f "$RUN/DONE" ] || [ "$tries" -ge 50 ]; do
  tries=$((tries+1)); echo "$(date '+%H:%M:%S') start $tries" >> "$RUN/supervisor.log"
  # guard (2026-11-02: a run once wrote 42 GB to the real turn log): stop the trainer if G2's real chase logs grow while it runs
  sz() { stat -f %z "$HOME/.local/share/g2/turn_log.jsonl" "$HOME/.local/share/g2/decision_log.jsonl" 2>/dev/null | paste -sd+ - | bc; }
  before=$(sz); before=${before:-0}
  "$ROOT/.venv/bin/python" "$HERE/train.py" "$RUN" "${@:2}" >> "$RUN/stdout.log" 2>&1 &
  tp=$!
  while kill -0 "$tp" 2>/dev/null; do
    now=$(sz); now=${now:-0}
    if [ $((now - before)) -gt 10000000 ]; then echo "$(date '+%H:%M:%S') STOP: the real chase logs grew by $((now - before)) bytes during the run" >> "$RUN/supervisor.log"; kill "$tp"; touch "$RUN/LOG_GUARD"; fi
    sleep 20
  done
  wait "$tp"
  [ -f "$RUN/LOG_GUARD" ] && break
  echo "$(date '+%H:%M:%S') exited $?" >> "$RUN/supervisor.log"; sleep 5
done
