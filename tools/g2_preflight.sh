#!/usr/bin/env bash
# Read-only preflight before a hardware session (the hw-session skill's step 2, 2026-11-17). Moves nothing, changes nothing.
#   tools/g2_preflight.sh
# Prints: what is running on the Pi (and whether a goal holds the focus lock), the deployed commit against HEAD, the Pi's clock and NTP state, the floor label, and the last pack reading with its percent
# (read from the voice service's battery log; the pack is read again by the run's own gate, so this is a heads-up, not the gate). Needs G2_PI.
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "== the Pi"; bash "$ROOT/tools/pi_read.sh" status
dep="$(ssh -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" 'cat ~/bittleX/pi_pipeline/.deployed_commit' 2>/dev/null | tr -d '[:space:]')"
head_full="$(git -C "$ROOT" rev-parse HEAD)"
if [ -n "$dep" ] && [[ "$head_full" == "$dep"* ]]; then echo "deployed == HEAD ($(git -C "$ROOT" rev-parse --short HEAD))"; else echo "NOTE: deployed ${dep:-unknown} differs from HEAD $(git -C "$ROOT" rev-parse --short HEAD): ship with tools/g2_deploy_safe.sh before testing new code"; fi
echo "== the pack (last logged reading)"; bash "$ROOT/tools/pi_read.sh" battery
echo "== the floor label (ask the owner every time; this is only what it reads now)"
( source "$ROOT/tools/g2_aliases.sh" >/dev/null 2>&1; g2floor 2>&1 | tail -n 1 )
echo "== gallery grooming (runs at the start of a hardware session: g2groom)"
if [ -f "$HOME/.local/share/g2/groom_last" ]; then echo "last run: $(cat "$HOME/.local/share/g2/groom_last"); applies: $(grep -q '"apply": *true' "$HOME/.local/share/g2/groom.json" 2>/dev/null && echo yes || echo 'no (report only)')"; else echo "never run: run g2groom now"; fi
echo "== the owner's go is still needed before anything moves G2"
