#!/usr/bin/env bash
# Deploy the last COMMIT to G2's Pi only when the Pi is idle, then verify what is there (the deploy-pi skill's steps in one place).
#   g2_deploy_safe.sh [--wait]     --wait: if a goal, exploration, punt or baseline is running, wait for it to end (tools/g2_wait_goal_end.sh) and then deploy; default: refuse (exit 2)
# Exit codes: 0 deployed and the Pi's .deployed_commit matches HEAD; 1 the deploy failed; 2 the Pi is not idle; 3 deployed but the hash does not match HEAD.
# Never deploys while anything runs (a deploy restarts the voice service). The deploy itself is tools/g2_deploy_when_online.sh --once.
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# goal_running marks only a goal run inside the voice service; a goal run the old stop-and-run way (the g2-goal unit, or `goals run` by hand) has no such file, so it is checked by unit and by process too (2026-11-27: a deploy restarted the voice service under a pick-up drill that ran that way)
idle() { ssh -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" 'test ! -e ~/.local/share/g2/goal_running && [ "$(systemctl is-active g2-explore g2-punt g2-baseline g2-goal | grep -vc inactive)" = 0 ] && ! pgrep -f "pi_pipeline[.]goals run" >/dev/null' 2>/dev/null; }
if ! idle; then
  if [ "${1:-}" = "--wait" ]; then bash "$ROOT/tools/g2_wait_goal_end.sh" || exit 2; idle || { echo "still not idle after the wait: not deploying" >&2; exit 2; }
  else echo "the Pi is not idle (a goal, exploration, punt or baseline is running, or it did not answer): not deploying. Use --wait to wait for it." >&2; exit 2; fi
fi
changed="$(git -C "$ROOT" status --porcelain pi_pipeline | grep -v '^??' | wc -l | tr -d ' ')"
[ "$changed" != "0" ] && echo "note: $changed uncommitted change(s) under pi_pipeline/ are NOT deployed (the deploy ships HEAD)"
bash "$ROOT/tools/g2_deploy_when_online.sh" --once > /tmp/g2_deploy_safe.$$ 2>&1; rc=$?
tail -n 2 /tmp/g2_deploy_safe.$$ | cut -c1-140; rm -f /tmp/g2_deploy_safe.$$
[ $rc -ne 0 ] && { echo "deploy failed (exit $rc)" >&2; exit 1; }
dep="$(ssh -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" 'cat ~/bittleX/pi_pipeline/.deployed_commit' 2>/dev/null | tr -d '[:space:]')"
head_full="$(git -C "$ROOT" rev-parse HEAD)"
echo "HEAD $(git -C "$ROOT" rev-parse --short HEAD), the Pi has: ${dep:-unknown}"
ssh -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" 'echo "services: $(systemctl is-active g2-voice g2-explore g2-punt g2-baseline | tr "\n" " ")"' 2>/dev/null
if [ -n "$dep" ] && [[ "$head_full" == "$dep"* ]]; then echo "OK: deployed and verified"; exit 0; fi
echo "MISMATCH: the Pi's commit is not HEAD" >&2; exit 3
