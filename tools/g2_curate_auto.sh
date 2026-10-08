#!/usr/bin/env bash
# Keep the exploration picture library curated without anyone asking: every run pulls G2's new pictures to the Mac and re-curates all of them
# into training_data/exploration/auto (the previous result is replaced only when the new one is complete).
#   g2_curate_auto.sh run | install [MINUTES, default 30] | remove | status
# `install` adds a launchd agent (~/Library/LaunchAgents/com.g2.curate.plist) that runs `run` on that interval and at login. Nothing is downloaded from
# the internet: the pictures come from G2's Pi on the local network. A run is skipped when the Pi does not answer or an exploration session is active
# (the Pi is memory-tight then). Log: ~/g2_logs/curate_auto.log.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL=com.g2.curate
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/g2_logs/curate_auto.log"
IN="$HOME/g2_pictures/explore"
OUT="$ROOT/training_data/exploration/auto"
mkdir -p "$HOME/g2_logs"

say() { echo "$(date '+%Y-%m-%d %I:%M:%S %p')  $*" >> "$LOG"; echo "$*"; }

case "${1:-run}" in
  run)
    if [ -z "${G2_PI:-}" ]; then   # launchd has no shell profile: take the one line that sets it (the value is never printed)
      for f in "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.zprofile"; do
        [ -f "$f" ] && eval "$(grep -m1 '^export G2_PI=' "$f" 2>/dev/null)" && [ -n "${G2_PI:-}" ] && break
      done
    fi
    [ -n "${G2_PI:-}" ] || { say "G2_PI is not set: nothing to pull"; exit 0; }
    ssh -o ConnectTimeout=6 -o BatchMode=yes "$G2_PI" true 2>/dev/null || { say "the Pi does not answer: skipped"; exit 0; }
    if [ "$(ssh -o BatchMode=yes "$G2_PI" 'systemctl is-active g2-explore' 2>/dev/null)" = active ]; then
      say "an exploration session is running: skipped"; exit 0
    fi
    ssh "$G2_PI" 'test -d ~/.local/share/g2/explore_pictures' 2>/dev/null || { say "no exploration pictures on the Pi yet"; exit 0; }
    mkdir -p "$IN" && rsync -a "$G2_PI:.local/share/g2/explore_pictures/" "$IN/" >> "$LOG" 2>&1 || { say "pull failed"; exit 1; }
    NEW="$OUT.new"; rm -rf "$NEW"
    if "$ROOT/pi_pipeline/.venv/bin/python" "$ROOT/tools/curate_exploration.py" "$IN" "$NEW" >> "$LOG" 2>&1; then
      rm -rf "$OUT.old"; [ -d "$OUT" ] && mv "$OUT" "$OUT.old"; mv "$NEW" "$OUT"; rm -rf "$OUT.old"
      say "curated: $(find "$OUT/keep" -name '*.jpg' 2>/dev/null | wc -l | tr -d ' ') kept of $(find "$IN" -name '*.jpg' | wc -l | tr -d ' ') pictures -> $OUT"
    else
      rm -rf "$NEW"; say "curation failed (see the log above); the previous result is unchanged"; exit 1
    fi ;;
  install)
    MIN="${2:-30}"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<P
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$ROOT/tools/g2_curate_auto.sh</string><string>run</string></array>
  <key>StartInterval</key><integer>$((MIN * 60))</integer>
  <key>RunAtLoad</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>$HOME/g2_logs/curate_auto.launchd.log</string>
  <key>StandardErrorPath</key><string>$HOME/g2_logs/curate_auto.launchd.log</string>
</dict></plist>
P
    launchctl unload "$PLIST" 2>/dev/null; launchctl load "$PLIST" && echo "installed: runs every $MIN min and at login. log: $LOG" ;;
  remove)
    launchctl unload "$PLIST" 2>/dev/null; rm -f "$PLIST"; echo "removed" ;;
  status)
    launchctl list 2>/dev/null | grep -q "$LABEL" && echo "scheduled ($PLIST)" || echo "not scheduled"
    tail -n 5 "$LOG" 2>/dev/null ;;
  *) echo "usage: $0 run | install [MINUTES] | remove | status"; exit 2 ;;
esac
