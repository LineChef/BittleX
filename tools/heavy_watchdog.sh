#!/usr/bin/env bash
# Keep the heavy-load training plan (rl_training/opencat-gym/phase_heavy.py run) alive unattended (docs/planned/heavy-load-training-plan.md). Every 2 minutes: if no runner process
# exists and the plan is not complete, relaunch it (the runner resumes from trained/heavy_state.json and waits for a run that is already training; it never restarts one)
# and keep the Mac awake while it lives. Stops when the runner wrote trained/heavy_halt (a DECISION NEEDED or a HALT) or logged "HEAVY COMPLETE".
# Start (from anywhere): nohup bash tools/heavy_watchdog.sh > /dev/null 2>&1 &     Log: ~/g2_logs/heavy_watchdog.log.  Stop: kill <pid of this script>.  Never uses pkill.
RL="$(cd "$(dirname "$0")/.." && pwd)/rl_training/opencat-gym"; LOG="$HOME/g2_logs/heavy_watchdog.log"; mkdir -p "$HOME/g2_logs"
cd "$RL" || exit 1
while true; do
  if ! pgrep -f "[p]hase_heavy.py run" > /dev/null; then
    if [ -e trained/heavy_halt ]; then
      echo "$(date '+%I:%M:%S %p') runner stopped for a decision or a fix (trained/heavy_halt): watchdog exits" >> "$LOG"; exit 1
    fi
    if [ -e trained/phase_heavy.log ] && tail -n 5 trained/phase_heavy.log | grep -q "HEAVY COMPLETE"; then
      echo "$(date '+%I:%M:%S %p') plan complete: watchdog exits" >> "$LOG"; exit 0
    fi
    echo "$(date '+%I:%M:%S %p') runner not running: (re)launching" >> "$LOG"
    (nohup ../../.venv/bin/python phase_heavy.py run >> trained/phase_heavy.stdout 2>&1 &)
    sleep 5
    RPID=$(pgrep -f "[p]hase_heavy.py run" | head -1)
    [ -n "$RPID" ] && (nohup caffeinate -ims -w "$RPID" > /dev/null 2>&1 &)
  fi
  sleep 120
done
