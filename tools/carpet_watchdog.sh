#!/usr/bin/env bash
# Keep the carpet-gait plan (rl_training/opencat-gym/phase_carpet.py run: rounds 1-5, the 20M included) alive unattended. Every 2 minutes: if no runner process
# exists and the plan is not complete, relaunch it (the runner resumes from trained/carpet_state.json and waits for a run that is already training; it never restarts one)
# and keep the Mac awake while it lives. Stops when the runner wrote trained/carpet_halt (a HALT) or logged "CARPET ALL COMPLETE".
# Start (from anywhere): nohup bash tools/carpet_watchdog.sh > /dev/null 2>&1 &     Log: ~/g2_logs/carpet_watchdog.log.  Stop: kill <pid of this script>.  Never uses pkill.
RL="$(cd "$(dirname "$0")/.." && pwd)/rl_training/opencat-gym"; LOG="$HOME/g2_logs/carpet_watchdog.log"; mkdir -p "$HOME/g2_logs"
cd "$RL" || exit 1
while true; do
  if ! pgrep -f "[p]hase_carpet.py run" > /dev/null; then
    if [ -e trained/carpet_halt ]; then
      echo "$(date '+%I:%M:%S %p') runner stopped for a decision or a fix (trained/carpet_halt): watchdog exits" >> "$LOG"; exit 1
    fi
    if [ -e trained/phase_carpet.log ] && tail -n 5 trained/phase_carpet.log | grep -q "CARPET ALL COMPLETE"; then
      echo "$(date '+%I:%M:%S %p') plan complete: watchdog exits" >> "$LOG"; exit 0
    fi
    echo "$(date '+%I:%M:%S %p') runner not running: (re)launching" >> "$LOG"
    (nohup ../../.venv/bin/python phase_carpet.py run >> trained/phase_carpet.stdout 2>&1 &)
    sleep 5
    RPID=$(pgrep -f "[p]hase_carpet.py run" | head -1)
    [ -n "$RPID" ] && (nohup caffeinate -ims -w "$RPID" > /dev/null 2>&1 &)
  fi
  sleep 120
done
