#!/bin/bash
# Runs the sim training wall stage (RUN_C, built on RUN_B's values), then deploys and applies when the Pi is on and idle.
#   nohup caffeinate -i bash tools/sim_train/chain.sh RUN_B RUN_C >/dev/null 2>&1 &
B="${1:?run B}"; C="${2:?run C}"; HERE="$(cd "$(dirname "$0")" && pwd)"
echo "$C" > "$HOME/g2_sim_train/CURRENT_RUN"
bash "$HERE/run.sh" "$C" --walls --base "$B"
bash "$HERE/apply_when_ready.sh" "$C"
