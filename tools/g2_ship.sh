#!/usr/bin/env bash
# Commit, push and (when the robot's code changed) deploy, in one gated pass: the chain typed by hand 29 times on 2026-11-25.
#   tools/g2_ship.sh -m "commit message" [--no-deploy] [--no-suite] PATH [PATH ...]
# Stops at the first failing step and says which (exit codes below); never pipes the checks through anything (their exit code is the gate).
#   1. branch must be `development`; PATHs are staged by exact path (never `-A`, never a folder named `.`); the message may not name an assistant or carry an attribution line;
#   2. tools/g2_precommit_checks.sh (add --no-suite for a change under no pi_pipeline/ code);  fails -> exit 3, nothing is committed;
#   3. commit, then the [A3] scan of the whole outgoing range for attribution lines; a hit -> exit 4, nothing is pushed (fix with the owner);
#   4. push origin development; fails -> exit 5;
#   5. deploy (tools/g2_deploy_safe.sh: never while a run is on, verified) ONLY when this commit touched robot code under pi_pipeline/ (not its tests; a docs commit needs no deploy: owner, 2026-11-25) and --no-deploy was not given; fails -> exit 6.
# Exit 2: usage. G2_CHECKS and G2_DEPLOY override the two commands (the tests use stubs).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
CHECKS="${G2_CHECKS:-bash tools/g2_precommit_checks.sh}"; DEPLOY="${G2_DEPLOY:-bash tools/g2_deploy_safe.sh}"
MSG=""; NODEPLOY=0; NOSUITE=0; PATHS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -m) MSG="${2:-}"; shift 2 ;;
    --no-deploy) NODEPLOY=1; shift ;;
    --no-suite) NOSUITE=1; shift ;;
    --) shift; PATHS+=("$@"); break ;;
    -*) echo "unknown option $1"; exit 2 ;;
    *) PATHS+=("$1"); shift ;;
  esac
done
[ -n "$MSG" ] && [ "${#PATHS[@]}" -gt 0 ] || { echo "usage: $0 -m \"message\" [--no-deploy] [--no-suite] PATH [PATH ...]"; exit 2; }
for p in "${PATHS[@]}"; do case "$p" in .|./|..|*/|-A) echo "stage by exact file path, not '$p'"; exit 2 ;; esac; done
[ "$(git rev-parse --abbrev-ref HEAD)" = development ] || { echo "not on the development branch"; exit 2; }
if printf '%s' "$MSG" | grep -qiE "co-authored|anthropic|claude"; then echo "the commit message names an assistant or carries an attribution line: reword it"; exit 2; fi

echo "== stage"; git add -- "${PATHS[@]}" || exit 2
[ -n "$(git diff --cached --name-only)" ] || { echo "nothing staged"; exit 2; }
CODE=0; git diff --cached --name-only | grep '^pi_pipeline/' | grep -qv '^pi_pipeline/tests/' && CODE=1            # tests are not robot code: a tests-only commit needs no deploy
echo "== checks"
if [ "$NOSUITE" = 1 ]; then $CHECKS --no-suite; else $CHECKS; fi || { echo "the checks failed: nothing was committed (the staged files stay staged)"; exit 3; }
echo "== commit"; git commit -q -m "$MSG" || exit 3
HASH="$(git rev-parse --short HEAD)"
if git log origin/development..HEAD --format=%B | grep -iE "co-authored|anthropic"; then echo "[A3] the outgoing range has an attribution line: NOT pushed. Fix it with the owner."; exit 4; fi
echo "== push"; git push -q origin development || { echo "the push failed: committed as $HASH, not pushed"; exit 5; }
if [ "$CODE" = 1 ] && [ "$NODEPLOY" = 0 ]; then
  echo "== deploy (pi_pipeline/ changed)"; $DEPLOY || { echo "committed and pushed as $HASH but the deploy did not verify"; exit 6; }
else
  echo "== no deploy ($( [ "$NODEPLOY" = 1 ] && echo '--no-deploy' || echo 'nothing under pi_pipeline/ changed'))"
fi
echo "shipped $HASH"
