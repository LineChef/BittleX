#!/bin/bash
# After the first sim training (RUN_A) is DONE, run the search-focused one (RUN_B, built on RUN_A's approach values), then apply the result to G2 when the Pi is on and idle.
#   nohup caffeinate -i bash tools/sim_train/chain.sh RUN_A RUN_B >/dev/null 2>&1 &
A="${1:?run A}"; B="${2:?run B}"; HERE="$(cd "$(dirname "$0")" && pwd)"
until [ -f "$A/DONE" ]; do sleep 30; done
echo "$B" > "$HOME/g2_sim_train/CURRENT_RUN"
bash "$HERE/run.sh" "$B" --search --base "$A"
bash "$HERE/apply_when_ready.sh" "$B"
