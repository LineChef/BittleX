#!/bin/bash
# Keeps the ARM2 run going (as ARM1X's, user 2026-10-25: training must not stop because nobody checked): restarts phase_arm2.py if it exits before "ARM2 COMPLETE" and no halt file exists.
cd "$(dirname "$0")"
while ! grep -q "ARM2 COMPLETE" trained/phase_arm2.log 2>/dev/null; do
  if ! pgrep -f "phase_arm2.py run" >/dev/null && [ ! -f trained/arm2_halt ]; then
    echo "[$(date '+%I:%M %p')] babysit: starting phase_arm2.py run" >> trained/phase_arm2.log
    nohup ../../.venv/bin/python phase_arm2.py run >> trained/phase_arm2_console.log 2>&1 &
  fi
  sleep 60
done
