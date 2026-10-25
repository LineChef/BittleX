#!/bin/bash
# Keeps the ARM1X run going (user, 2026-10-25: training must not stop because nobody checked): restarts phase_armx.py if it exits before "ARM1X COMPLETE" and no halt file exists.
cd "$(dirname "$0")"
while ! grep -q "ARM1X COMPLETE" trained/phase_armx.log 2>/dev/null; do
  if ! pgrep -f "phase_armx.py run" >/dev/null && [ ! -f trained/armx_halt ]; then
    echo "[$(date '+%I:%M %p')] babysit: starting phase_armx.py run" >> trained/phase_armx.log
    nohup ../../.venv/bin/python phase_armx.py run >> trained/phase_armx_console.log 2>&1 &
  fi
  sleep 60
done
