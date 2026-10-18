#!/usr/bin/env bash
# Keep the pod training plan (the V6 recipe on the new payload) (rl_training/opencat-gym/phase_pod.py run) alive unattended (docs/plan-detail/v6-staged-training-plan.md). Every 2 minutes: if no runner process
# exists and the plan is not complete, relaunch it (the runner resumes from trained/pod_state.json and waits for a run that is already training; it never restarts one)
# and keep the Mac awake while it lives. Stops when the runner wrote trained/pod_halt (a DECISION NEEDED or a HALT) or logged "POD COMPLETE".
# Start (from anywhere): nohup bash tools/pod_watchdog.sh > /dev/null 2>&1 &     Log: ~/g2_logs/pod_watchdog.log.  Stop: kill <pid of this script>.  Never uses pkill.
RL="$(cd "$(dirname "$0")/.." && pwd)/rl_training/opencat-gym"; LOG="$HOME/g2_logs/pod_watchdog.log"; mkdir -p "$HOME/g2_logs"
cd "$RL" || exit 1
while true; do
  if ! pgrep -f "[p]hase_pod.py run" > /dev/null; then
    if [ -e trained/pod_halt ]; then
      echo "$(date '+%I:%M:%S %p') runner stopped for a decision or a fix (trained/pod_halt): watchdog exits" >> "$LOG"; exit 1
    fi
    if [ -e trained/phase_pod.log ] && tail -n 5 trained/phase_pod.log | grep -q "POD COMPLETE"; then
      echo "$(date '+%I:%M:%S %p') plan complete: watchdog exits" >> "$LOG"; exit 0
    fi
    echo "$(date '+%I:%M:%S %p') runner not running: (re)launching" >> "$LOG"
    (nohup ../../.venv/bin/python phase_pod.py run >> trained/phase_pod.stdout 2>&1 &)
    sleep 5
    RPID=$(pgrep -f "[p]hase_pod.py run" | head -1)
    [ -n "$RPID" ] && (nohup caffeinate -ims -w "$RPID" > /dev/null 2>&1 &)
  fi
  sleep 120
done
