#!/usr/bin/env bash
# Wait until no goal session is running on G2's Pi, then print when it ended (2026-11-17: written after a watcher that looked for the previous session's END line fired at once).
#   g2_wait_goal_end.sh [--max-min N]       default N = 60. Exit 0 when the goal_running file has been gone for two checks 10 s apart, 1 on timeout.
# Exit 3 when the Pi does not answer (it says so: an unreachable Pi is not an idle one). The signal is the file ~/.local/share/g2/goal_running that a goal session holds; the session log's END line is NOT used (the last session's END is still there when a new one starts).
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
MAX_MIN=60
[ "${1:-}" = "--max-min" ] && MAX_MIN="${2:-60}"
gone() { ssh -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" 'test ! -e ~/.local/share/g2/goal_running' 2>/dev/null; rc=$?; [ "$rc" = 255 ] && { echo "could not verify: the Pi did not answer" >&2; exit 3; }; return $rc; }
end=$(( $(date +%s) + MAX_MIN * 60 ))
while [ "$(date +%s)" -lt "$end" ]; do
  if gone; then sleep 10; if gone; then echo "goal ended at $(date '+%I:%M:%S %p')"; exit 0; fi; fi
  sleep 15
done
echo "timed out after $MAX_MIN min: a goal session is still running" >&2; exit 1
