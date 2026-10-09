#!/usr/bin/env bash
# Stop whatever is controlling G2 on the Pi the safe way (user, 2026-10-09: always rest G2 before stopping anything, to prevent falls).
#   g2_safe_stop.sh [explore|baseline|voice|all]      default: all of them that are running. Needs G2_PI.
# Never `systemctl stop` a G2 service directly: a walk or a turn that is cut off mid-stride leaves the legs wherever they were, and resting from a stride dropped G2 on his side.
# explore: asks the session to stop (it settles into a balanced stand, then lies down, then exits); baseline: SIGINT (the walk loop sends rest); voice: the loop rests on stop.
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
WHAT="${1:-all}"
ssh "$G2_PI" 'bash -s' "$WHAT" <<'REMOTE'
what="$1"
active() { systemctl is-active --quiet "$1"; }
wait_inactive() { for _ in $(seq 1 40); do active "$1" || return 0; sleep 0.5; done; return 1; }
if [ "$what" = all ] || [ "$what" = explore ]; then
  if active g2-explore; then
    echo stop > ~/.g2_explore_cmd; echo "asked the exploration session to stop (balance, rest, exit)"
    wait_inactive g2-explore && echo "exploration session ended" || { echo "still running after 20 s: SIGINT"; sudo systemctl kill -s SIGINT g2-explore; wait_inactive g2-explore; }
  fi
fi
if [ "$what" = all ] || [ "$what" = baseline ]; then
  if active g2-baseline; then sudo systemctl kill -s SIGINT g2-baseline; echo "SIGINT to the baseline run (it sends rest)"; wait_inactive g2-baseline && echo "baseline ended"; fi
fi
if [ "$what" = voice ]; then
  if active g2-voice; then sudo systemctl stop g2-voice; echo "voice service stopped"; fi
fi
REMOTE
