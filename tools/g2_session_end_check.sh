#!/usr/bin/env bash
# Read-only end-of-session checks (the session-end skill's steps 1 to 3, 2026-11-17). Moves nothing, deletes nothing.
#   tools/g2_session_end_check.sh
# Prints: services and the Pi's clock, the voice service's board clues this boot, any waiting deploy watcher, the guardrail integrity check, HEAD against what the Pi has and unpushed commits, tracked changes,
# and the cleanup dry run's DELETE / DECIDE counts. Writing STATUS and memory stays manual. If the Pi does not answer it says "could not verify"; it never assumes G2 is safe. Needs G2_PI.
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
echo "== the Pi"; bash tools/pi_read.sh status || echo "could not verify: the Pi did not answer (it may be off); ask the owner to confirm G2's state by eye"
echo "== board clues this boot (a clue, not proof of posture)"
bash tools/pi_read.sh journal "board|silent|deaf|laying|fall|not answering" "3 hours ago" 2>&1 | tail -n 6
pid="$(cat ~/g2_logs/deploy_waiter.pid 2>/dev/null)"; if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then echo "deploy watcher: ARMED (pid $pid): it ships HEAD when the Pi answers"; else echo "deploy watcher: none"; fi
echo "== guardrails"; python3 .claude/guardrails_check.py 2>&1 | tail -n 3
echo "== git"; echo "HEAD $(git rev-parse --short HEAD); unpushed: $(git log origin/development..HEAD --oneline | wc -l | tr -d ' '); tracked changes: $(git status --porcelain | grep -vc '^??')"
echo "== cleanup dry run (nothing is deleted here)"; python3 tools/g2_cleanup.py --no-pi 2>&1 | grep -E "^(DELETE|DECIDE)" | head -4
echo "== still to do by hand: G2 at rest (ask the owner), STATUS and the one project-state memory, the next session's first step"
