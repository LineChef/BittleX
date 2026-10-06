#!/usr/bin/env bash
# Logged firmware turn runs (kwkL, kwkR alternating) on G2's Pi (g2-voice is stopped for the duration and ALWAYS started again). Needs G2_PI.
#   g2_turns.sh start [RUNS] [LABEL] [extra baseline_runs args, e.g. --hold abba or --yaw-sign abba] | stop | status | logs | fetch
set -euo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
UNIT=g2-turns
case "${1:-status}" in
  start)
    ssh "$G2_PI" "sudo systemd-run --unit=$UNIT --collect --uid=\$(id -un) \
      -p WorkingDirectory=\$HOME/bittleX -p KillSignal=SIGINT -p TimeoutStopSec=20 \
      -p ExecStartPre='+/bin/systemctl stop g2-voice' \
      -p ExecStopPost='+/bin/systemctl --no-block start g2-voice' \
      \$HOME/bittleX/pi_pipeline/.venv/bin/python -m pi_pipeline.gait.turn_runs --runs ${2:-6} --label ${3:-turn_fw} ${*:4}" ;;
  stop)   ssh "$G2_PI" "sudo systemctl stop $UNIT" ;;
  status) ssh "$G2_PI" "systemctl is-active $UNIT || true; systemctl is-active g2-voice || true" ;;
  logs)   ssh "$G2_PI" "journalctl -u $UNIT -n 40 --no-pager | cut -c1-180" ;;
  fetch)  mkdir -p "${2:-$HOME/Desktop/OneFolder/G2/walk-logs}" && scp "$G2_PI:~/g2_runs/${3:-case_v21}_*.csv" "${2:-$HOME/Desktop/OneFolder/G2/walk-logs}/" ;;
  *) echo "usage: $0 start [RUNS] [LABEL] | stop | status | logs | fetch [DIR] [LABEL]"; exit 2 ;;
esac
