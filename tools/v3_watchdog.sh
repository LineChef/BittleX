#!/usr/bin/env bash
# Keep the V3 queue runner alive unattended. Every 2 minutes: if no `phase_v3.py run` process exists and the queue has not finished, relaunch it (the runner resumes a job that is already
# training, so a relaunch is safe) and keep the Mac awake while it lives. Log: ~/g2_logs/v3_watchdog.log. Stop with: kill <pid of this script>.  Never uses pkill.
RL="$(cd "$(dirname "$0")/.." && pwd)/rl_training/opencat-gym"; LOG="$HOME/g2_logs/v3_watchdog.log"; mkdir -p "$HOME/g2_logs"
cd "$RL" || exit 1
while true; do
  if ! pgrep -f "[p]hase_v3.py run" > /dev/null; then
    if tail -n 20 trained/phase_v3.log | grep -q "QUEUE COMPLETE"; then
      echo "$(date '+%I:%M:%S %p') queue complete: watchdog exits" >> "$LOG"; exit 0
    fi
    echo "$(date '+%I:%M:%S %p') runner not running: relaunching" >> "$LOG"
    (nohup ../../.venv/bin/python phase_v3.py run >> trained/phase_v3.stdout 2>&1 &)
    sleep 5
    RPID=$(pgrep -f "[p]hase_v3.py run" | head -1)
    [ -n "$RPID" ] && (nohup caffeinate -i -w "$RPID" > /dev/null 2>&1 &)
  fi
  sleep 120
done
