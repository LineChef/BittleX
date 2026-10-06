#!/usr/bin/env bash
# Supervised exploration test on G2's Pi. g2-voice is stopped while it runs and is ALWAYS started again when it ends (systemd ExecStopPost),
# however it ends: a stop, a crash, a timeout or a reboot-free kill. Needs G2_PI (user@host) in the environment, like the other tools.
#   g2_explore.sh start [ROAM_S, default 600; 0 = no cap] | arm | disarm | halt | release | stop | status | logs
set -euo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
UNIT=g2-explore
case "${1:-status}" in
  start)
    ssh "$G2_PI" "sudo systemd-run --unit=$UNIT --collect --uid=\$(id -un) \
      -p WorkingDirectory=\$HOME/bittleX -p KillSignal=SIGTERM -p TimeoutStopSec=15 \
      -p ExecStartPre='+/bin/systemctl stop g2-voice' \
      -p ExecStopPost='+/bin/systemctl --no-block start g2-voice' \
      -E G2_FEATURES='+vision,+vision_perception,+vision_safety,+explore,-avoidance_act,-object_gallery' -E G2_LOG_HEARD=1 \
      \$HOME/bittleX/pi_pipeline/.venv/bin/python -m pi_pipeline.explore_session --roam-s ${2:-600}" ;;
  arm|disarm|halt|release) ssh "$G2_PI" "echo $1 > ~/.g2_explore_cmd" ;;
  stop)   ssh "$G2_PI" "echo stop > ~/.g2_explore_cmd" ;;
  status) ssh "$G2_PI" "systemctl is-active $UNIT; systemctl is-active g2-voice" ;;
  logs)   ssh "$G2_PI" "journalctl -u $UNIT -n 60 --no-pager | cut -c1-200" ;;
  *) echo "usage: $0 start [ROAM_S, default 600; 0 = no cap] | arm | disarm | halt | release | stop | status | logs"; exit 2 ;;
esac
