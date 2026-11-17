#!/usr/bin/env bash
# The commit skill's checks in one place (2026-11-17): the full suite ALONE, ruff, mode parity, docs, and the staged diff's privacy and attribution counts.
#   tools/g2_precommit_checks.sh [--no-suite] [--push-scan]
#     --no-suite   skip pytest (a change that touches no code under pi_pipeline/)
#     --push-scan  also scan the whole outgoing range origin/development..HEAD for attribution lines (guardrail A3); prints clean or the hit count, never the text
# Prints one PASS/FAIL line per check and exits 1 if any failed. The suite is never run next to another pytest (it stops: two suites at once is not allowed).
# Staging and the commit message stay manual. The privacy terms come from .gitprivacy-terms (the pre-commit hook's own list); only a COUNT is printed, never a term.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
SUITE=1; SCAN=0
for a in "$@"; do case "$a" in --no-suite) SUITE=0 ;; --push-scan) SCAN=1 ;; *) echo "usage: $0 [--no-suite] [--push-scan]" >&2; exit 2 ;; esac; done
fail=0
check() { local name="$1"; shift; if "$@" >/tmp/g2_pc.$$ 2>&1; then echo "PASS  $name"; else echo "FAIL  $name"; tail -n 6 /tmp/g2_pc.$$ | cut -c1-160; fail=1; fi; rm -f /tmp/g2_pc.$$; }
if [ "$SUITE" = 1 ]; then
  if pgrep -f "pytest" >/dev/null 2>&1; then echo "FAIL  suite: another pytest is running; run the suite alone" ; fail=1
  else check "full suite (pytest -n auto)" pi_pipeline/.venv/bin/pytest -n auto -q -p no:warnings; fi
fi
check "ruff" pi_pipeline/.venv/bin/ruff check
check "mode parity (check_modes)" python3 tools/check_modes.py
check "docs (check_docs)" python3 tools/check_docs.py
terms=".gitprivacy-terms"
if [ -f "$terms" ]; then
  pattern="$(grep -vE '^\s*(#|$)' "$terms" | paste -sd'|' -)"
  if [ -n "$pattern" ]; then
    n="$(git diff --cached | grep -ciwE "$pattern" || true)"
    if [ "${n:-0}" = "0" ]; then echo "PASS  staged diff: no private terms (count 0)"; else echo "FAIL  staged diff: $n line(s) match the privacy terms"; fail=1; fi
  fi
else echo "note: no .gitprivacy-terms, the privacy count was skipped"; fi
a="$(git diff --cached | grep -ciE "co-authored-by|generated with claude" || true)"
if [ "${a:-0}" = "0" ]; then echo "PASS  staged diff: no attribution lines"; else echo "FAIL  staged diff: $a attribution line(s)"; fail=1; fi
if [ "$SCAN" = 1 ]; then
  h="$(git log origin/development..HEAD --format=%B | grep -ciE "co-authored|anthropic|claude" || true)"
  if [ "${h:-0}" = "0" ]; then echo "PASS  outgoing range: no attribution (A3)"; else echo "FAIL  outgoing range: $h attribution line(s)"; fail=1; fi
fi
[ "$fail" = 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit $fail
