#!/usr/bin/env bash
# The last step of a wrap-up (owner, 2026-11-25): deploy what is waiting, then rest G2, stop the voice service and shut the Pi down so everything can be charged.
#   tools/g2_session_shutdown.sh [--dry-run]       needs G2_PI
# Order, and it stops (exit non-zero, nothing shut down) at the first step that fails:
#   1. the Pi must answer (else "could not verify": nothing is sent);
#   2. code under pi_pipeline/ that is changed but not committed stops it (the deploy ships the last COMMIT): commit first;
#   3. the Pi's deployed commit is compared with HEAD for pi_pipeline/ only (a docs commit needs no deploy: owner, 2026-11-25); if it differs the deploy runs (tools/g2_deploy_safe.sh: never while a goal runs) and must verify;
#   4. G2 is rested and the voice service stopped the safe way (tools/g2_safe_stop.sh voice);
#   5. `sudo shutdown -h now`, then it waits for the Pi to stop answering. Cut the power after the green light stops blinking.
# --dry-run prints what it would do and sends nothing. G2_SSH, G2_DEPLOY and G2_SAFE_STOP override the three commands (the tests use stubs).
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
SSH="${G2_SSH:-ssh}"; DEPLOY="${G2_DEPLOY:-bash tools/g2_deploy_safe.sh}"; SAFE_STOP="${G2_SAFE_STOP:-bash tools/g2_safe_stop.sh voice}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
say() { echo "== $*"; }
run() { if [ "$DRY" = 1 ]; then echo "(dry run) would run: $*"; else eval "$@"; fi; }

say "1. the Pi answers?"
if ! $SSH -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" true 2>/dev/null; then
  echo "could not verify: the Pi does not answer (it may be off already). Nothing was sent."; exit 2
fi

say "2. code waiting to be committed?"
if ! git diff --quiet HEAD -- pi_pipeline || [ -n "$(git ls-files --others --exclude-standard -- pi_pipeline | head -1)" ]; then
  echo "changes under pi_pipeline/ are not committed: the deploy ships the last commit. Commit them (the commit skill), then run this again. Nothing was shut down."; exit 3
fi

say "3. code waiting to be deployed?"
dep="$($SSH -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" 'cat ~/bittleX/pi_pipeline/.deployed_commit' 2>/dev/null | tr -d '[:space:]')"
if [ -z "$dep" ] || ! git cat-file -e "$dep^{commit}" 2>/dev/null; then
  echo "the Pi's deployed commit is unknown ('$dep'): deploying HEAD"; need=1
elif git diff --quiet "$dep" HEAD -- pi_pipeline ':(exclude)pi_pipeline/tests'; then
  echo "nothing to deploy: the Pi has $dep and pi_pipeline/ has not changed since (docs commits are not deployed)"; need=0
else
  echo "the Pi has $dep; pi_pipeline/ changed since: deploying HEAD $(git rev-parse --short HEAD)"; need=1
fi
if [ "$need" = 1 ]; then
  run "$DEPLOY" || { echo "the deploy did not verify (exit $?): the Pi was NOT shut down."; exit 4; }
fi

say "4. rest G2 and stop the voice service (the safe way)"
run "$SAFE_STOP" || { echo "the safe stop failed: the Pi was NOT shut down."; exit 5; }

say "5. shut the Pi down"
run "$SSH -o ConnectTimeout=8 -o BatchMode=yes \"$G2_PI\" 'sudo shutdown -h now'" || true
if [ "$DRY" = 1 ]; then echo "(dry run) done: nothing was sent."; exit 0; fi
for i in $(seq 1 15); do
  sleep 4
  if ! $SSH -o ConnectTimeout=4 -o BatchMode=yes "$G2_PI" true 2>/dev/null; then
    echo "the Pi no longer answers: shut down. Wait for the green light to stop blinking before cutting the power."; exit 0
  fi
done
echo "the Pi still answers after 60 s: the shutdown may not have run. Check by hand."; exit 6
