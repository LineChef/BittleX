#!/usr/bin/env bash
# Supervised exploration test on G2's Pi. g2-voice is stopped while it runs and is ALWAYS started again when it ends (systemd ExecStopPost),
# however it ends: a stop, a crash, a timeout or a reboot-free kill. Needs G2_PI (user@host) in the environment, like the other tools.
#   g2_explore.sh start [ROAM_S, default 600; 0 = no cap] | stationary [ROAM_S] | arm | disarm | halt | release | stop | status | logs | heard
#   `start` roams at once (Tier 1 is the default, user 2026-10-07); `stationary` is the opt-in stay-put mode (Tier 0) until `arm`.
set -euo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
UNIT=g2-explore
case "${1:-status}" in
  start|stationary)
    EXTRA=""; [ "$1" = stationary ] && EXTRA=" --stationary"
    ssh "$G2_PI" "rm -f ~/.g2_explore_cmd; sudo systemd-run --unit=$UNIT --collect --uid=\$(id -un) \
      -p WorkingDirectory=\$HOME/bittleX -p KillSignal=SIGTERM -p TimeoutStopSec=15 \
      -p ExecStartPre='+/bin/systemctl stop g2-voice' \
      -p ExecStopPost=\"+/bin/sh -c '\$HOME/bittleX/pi_pipeline/.venv/bin/python -m pi_pipeline.link.check_serial send d >/dev/null 2>&1; true'\" \
      -p ExecStopPost='+/bin/systemctl --no-block start g2-voice' \
      -E G2_FEATURES='+vision,+vision_perception,+vision_safety,+explore,-avoidance_act,-object_gallery' -E G2_LOG_HEARD=1 -E PYTHONFAULTHANDLER=1 \
      \$HOME/bittleX/pi_pipeline/.venv/bin/python -m pi_pipeline.explore_session --roam-s ${2:-600}$EXTRA" ;;
  arm|disarm|halt|release|stop)
    # only while a session is running: a command written to the file with no session would be read by the NEXT session as soon as it starts (a stale halt stopped a fresh run, 2026-10-07)
    ssh "$G2_PI" "if [ \"\$(systemctl is-active $UNIT)\" = active ]; then echo $1 > ~/.g2_explore_cmd; else echo 'no exploration session is running: $1 not sent (and not left behind)'; fi" ;;
  status) ssh "$G2_PI" "systemctl is-active $UNIT; systemctl is-active g2-voice" ;;
  logs)   ssh "$G2_PI" "journalctl -u $UNIT -n 60 --no-pager | cut -c1-200" ;;
  heard)  ssh "$G2_PI" "journalctl -u $UNIT -n 400 --no-pager | grep -E 'wake word heard|nothing recognized|heard:|naming request|answered|not a command|picture saved|no picture' | cut -c1-190 | tail -${2:-25}" ;;
  *) echo "usage: $0 start [ROAM_S, default 600; 0 = no cap] | stationary [ROAM_S] | arm | disarm | halt | release | stop | status | logs | heard"; exit 2 ;;
esac
