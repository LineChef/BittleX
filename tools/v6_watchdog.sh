#!/usr/bin/env bash
# Keep the V6 training plan (rl_training/opencat-gym/phase_v6.py run) alive unattended (docs/plan-detail/v6-staged-training-plan.md). Every 2 minutes: if no runner process
# exists and the plan is not complete, relaunch it (the runner resumes from trained/v6_state.json and waits for a run that is already training; it never restarts one)
# and keep the Mac awake while it lives. Stops when the runner wrote trained/v6_halt (a DECISION NEEDED or a HALT) or logged "V6 COMPLETE".
# Start (from anywhere): nohup bash tools/v6_watchdog.sh > /dev/null 2>&1 &     Log: ~/g2_logs/v6_watchdog.log.  Stop: kill <pid of this script>.  Never uses pkill.
RL="$(cd "$(dirname "$0")/.." && pwd)/rl_training/opencat-gym"; LOG="$HOME/g2_logs/v6_watchdog.log"; mkdir -p "$HOME/g2_logs"
cd "$RL" || exit 1
while true; do
  if ! pgrep -f "[p]hase_v6.py run" > /dev/null; then
    if [ -e trained/v6_halt ]; then
      echo "$(date '+%I:%M:%S %p') runner stopped for a decision or a fix (trained/v6_halt): watchdog exits" >> "$LOG"; exit 1
    fi
    if [ -e trained/phase_v6.log ] && tail -n 5 trained/phase_v6.log | grep -q "V6 COMPLETE"; then
      echo "$(date '+%I:%M:%S %p') plan complete: watchdog exits" >> "$LOG"; exit 0
    fi
    echo "$(date '+%I:%M:%S %p') runner not running: (re)launching" >> "$LOG"
    (nohup ../../.venv/bin/python phase_v6.py run >> trained/phase_v6.stdout 2>&1 &)
    sleep 5
    RPID=$(pgrep -f "[p]hase_v6.py run" | head -1)
    [ -n "$RPID" ] && (nohup caffeinate -ims -w "$RPID" > /dev/null 2>&1 &)
  fi
  sleep 120
done
