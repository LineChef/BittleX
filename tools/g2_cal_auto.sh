#!/usr/bin/env bash
# The unattended real-data calibration step: pull G2's automatic run logs from the Pi (when it is online), ingest them, and let the calibration builder
# build / harm-check / approve a snapshot by its rules (tools/g2_calibrate.py `auto`; docs/rl/real-data-pipeline.md).
#   g2_cal_auto.sh run | install [MINUTES, default 60] | remove | status
# `install` adds a launchd agent (~/Library/LaunchAgents/com.g2.calibrate.plist). Nothing is downloaded from the internet (the logs come from G2's Pi on the local
# network). The harm check scores policies on every core, so it waits until nothing else is running on the Mac (no training, benchmark or other test): while the
# V3 queue trains, a finished snapshot just waits. A first snapshot, a change beyond noise or an epoch change is never applied without you (`g2cal approve ID`).
# Log: ~/g2_logs/cal_auto.log.
# NOTE: `install` (launchd) needs /bin/bash to have Full Disk Access, because macOS blocks launchd agents from scripts under ~/Desktop. The reliable way is tools/g2_bg_jobs.sh.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL=com.g2.calibrate
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/g2_logs/cal_auto.log"
PY="$ROOT/.venv/bin/python"          # the RL-training venv (the harm check runs the sim); the fitting itself needs only numpy
mkdir -p "$HOME/g2_logs"
say() { echo "$(date '+%Y-%m-%d %I:%M:%S %p')  $*" >> "$LOG"; echo "$*"; }

case "${1:-run}" in
  run)
    if [ -z "${G2_PI:-}" ]; then      # launchd has no shell profile: take the one line that sets it (the value is never printed)
      for f in "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.zprofile"; do
        [ -f "$f" ] && eval "$(grep -m1 '^export G2_PI=' "$f" 2>/dev/null)" && [ -n "${G2_PI:-}" ] && break
      done
    fi
    if [ -n "${G2_PI:-}" ] && ssh -o ConnectTimeout=6 -o BatchMode=yes "$G2_PI" true 2>/dev/null; then
      mkdir -p "$HOME/g2_data/raw_auto" "$HOME/g2_data/detections"
      rsync -a "$G2_PI:g2_runs/auto/" "$HOME/g2_data/raw_auto/" >> "$LOG" 2>&1 || say "sync of the run logs failed"
      rsync -a "$G2_PI:g2_runs/detections/" "$HOME/g2_data/detections/" >> "$LOG" 2>&1 || true
    else
      say "the Pi does not answer: using the logs already on the Mac"
    fi
    [ -d "$HOME/g2_data/raw_auto" ] || { say "no run logs yet"; exit 0; }
    "$PY" "$ROOT/tools/g2_ingest.py" 2>&1 | head -n 1 | while read -r l; do say "ingest: $l"; done
    say "calibration: $("$PY" "$ROOT/tools/g2_calibrate.py" auto 2>&1 | tail -n 3 | tr '\n' ' ')" ;;
  install)
    MIN="${2:-60}"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$ROOT/tools/g2_cal_auto.sh</string><string>run</string></array>
  <key>StartInterval</key><integer>$((MIN * 60))</integer>
  <key>RunAtLoad</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>$HOME/g2_logs/cal_auto.launchd.log</string>
  <key>StandardErrorPath</key><string>$HOME/g2_logs/cal_auto.launchd.log</string>
</dict></plist>
P
    launchctl unload "$PLIST" 2>/dev/null; launchctl load "$PLIST" && echo "installed: runs every $MIN min and at login. log: $LOG" ;;
  remove)
    launchctl unload "$PLIST" 2>/dev/null; rm -f "$PLIST"; echo "removed" ;;
  status)
    launchctl list 2>/dev/null | grep -q "$LABEL" && echo "scheduled ($PLIST)" || echo "not scheduled"
    "$PY" "$ROOT/tools/g2_calibrate.py" status
    tail -n 5 "$LOG" 2>/dev/null ;;
  *) echo "usage: $0 run | install [MINUTES] | remove | status"; exit 2 ;;
esac
