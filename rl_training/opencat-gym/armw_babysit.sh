#!/bin/bash
# Keeps the ARMW run going (as ARM2's, user 2026-10-25: training must not stop because nobody checked): restarts phase_armw.py if it exits before "ARMW COMPLETE" and no halt file exists.
cd "$(dirname "$0")"
while ! grep -q "ARMW COMPLETE" trained/phase_armw.log 2>/dev/null; do
  if ! pgrep -f "phase_armw.py run" >/dev/null && [ ! -f trained/armw_halt ]; then
    echo "[$(date '+%I:%M %p')] babysit: starting phase_armw.py run" >> trained/phase_armw.log
    nohup ../../.venv/bin/python phase_armw.py run >> trained/phase_armw_console.log 2>&1 &
  fi
  sleep 60
done
