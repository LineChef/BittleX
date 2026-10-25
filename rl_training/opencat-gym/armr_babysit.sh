#!/bin/bash
# Keeps the ARM1R chain running (user, 2026-10-25: training must not stop because nobody checked): restarts phase_armr.py if it exits before "ARM1R COMPLETE" and no halt file exists.
cd "$(dirname "$0")"
while ! grep -q "ARM1R COMPLETE" trained/phase_armr.log 2>/dev/null; do
  if ! pgrep -f "phase_armr.py run" >/dev/null && [ ! -f trained/armr_halt ]; then
    echo "[$(date '+%I:%M %p')] babysit: starting phase_armr.py run" >> trained/phase_armr.log
    nohup ../../.venv/bin/python phase_armr.py run >> trained/phase_armr_console.log 2>&1 &
  fi
  sleep 60
done
