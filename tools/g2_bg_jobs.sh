#!/usr/bin/env bash
# The Mac-side background jobs, run from a plain background loop (not launchd: macOS refuses to let a launchd agent run scripts that live under ~/Desktop,
# "Operation not permitted", unless /bin/bash is given Full Disk Access).  Every INTERVAL minutes (default 30) it runs
#   tools/g2_curate_auto.sh run   (pull the exploration pictures from the Pi, re-curate the library)
#   tools/g2_cal_auto.sh run      (pull the run logs, ingest, build / harm-check / approve a calibration snapshot by the rules)
#   g2_bg_jobs.sh start [MINUTES] | stop | status | once
# The loop ends when the Mac restarts or logs out: run `start` again (or `g2_bg_jobs.sh status` to see). Log: ~/g2_logs/bg_jobs.log.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="$HOME/g2_logs/bg_jobs.pid"
LOG="$HOME/g2_logs/bg_jobs.log"
mkdir -p "$HOME/g2_logs"
alive() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
case "${1:-status}" in
  start)
    alive && { echo "already running (pid $(cat "$PIDFILE"))"; exit 0; }
    MIN="${2:-30}"
    nohup bash -c "while true; do bash '$ROOT/tools/g2_curate_auto.sh' run >> '$LOG' 2>&1; bash '$ROOT/tools/g2_cal_auto.sh' run >> '$LOG' 2>&1; sleep $((MIN * 60)); done" >/dev/null 2>&1 &
    echo $! > "$PIDFILE"; disown 2>/dev/null || true
    echo "started (pid $(cat "$PIDFILE")): curation and calibration every $MIN min. log: $LOG" ;;
  stop)
    alive && { kill "$(cat "$PIDFILE")"; rm -f "$PIDFILE"; echo stopped; } || echo "not running" ;;
  once)
    bash "$ROOT/tools/g2_curate_auto.sh" run; bash "$ROOT/tools/g2_cal_auto.sh" run ;;
  status)
    alive && echo "running (pid $(cat "$PIDFILE"))" || echo "not running (g2_bg_jobs.sh start)"
    tail -n 6 "$LOG" 2>/dev/null ;;
  *) echo "usage: $0 start [MINUTES] | stop | status | once"; exit 2 ;;
esac
