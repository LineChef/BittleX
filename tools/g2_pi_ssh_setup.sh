#!/usr/bin/env bash
# Add (or update) the `Host g2pi.local` block in ~/.ssh/config that sends every ssh / rsync to the Pi through tools/g2_pi_connect.sh,
# so the tools keep working when the Mac cannot resolve the Pi's name. Idempotent; the block sits between marker lines and is replaced on a rerun.
#   bash tools/g2_pi_ssh_setup.sh            install / update
#   bash tools/g2_pi_ssh_setup.sh --remove   take the block out again
# A copy of the config is kept at ~/.ssh/config.bak-g2 before any change.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$HOME/.ssh/config"
BEGIN="# >>> g2pi (tools/g2_pi_ssh_setup.sh) >>>"
END="# <<< g2pi <<<"
mkdir -p "$HOME/.ssh" && touch "$CFG"
cp "$CFG" "$CFG.bak-g2"
STRIPPED=$(awk -v b="$BEGIN" -v e="$END" '$0 == b {skip = 1; next} $0 == e {skip = 0; next} !skip' "$CFG")
if [ "${1:-}" = "--remove" ]; then
  printf '%s\n' "$STRIPPED" > "$CFG"
  echo "removed the g2pi block from $CFG"
  exit 0
fi
# the block goes first: ssh uses the first value it finds for each option
{
  echo "$BEGIN"
  echo "Host g2pi.local"
  echo "  ProxyCommand bash \"$ROOT/tools/g2_pi_connect.sh\" %h %p"
  echo "$END"
  echo
  printf '%s\n' "$STRIPPED"
} > "$CFG"
echo "installed the g2pi block in $CFG (backup: $CFG.bak-g2)"
