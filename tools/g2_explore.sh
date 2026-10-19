#!/usr/bin/env bash
# Supervised exploration test on G2's Pi. g2-voice is stopped while it runs and is ALWAYS started again when it ends (systemd ExecStopPost),
# however it ends: a stop, a crash, a timeout or a reboot-free kill. Needs G2_PI (user@host) in the environment, like the other tools.
#   g2_explore.sh start [ROAM_S, default 600; 0 = no cap] | stationary [ROAM_S] | arm | disarm | halt | release | stop | status | logs | heard | report [html]
#   `start` / `stationary` ask for the floor first when its label is unknown or over an hour old (see floor_gate below); `report` shows the last roam's report.
#   `start` roams at once (Tier 1 is the default, user 2026-10-07); `stationary` is the opt-in stay-put mode (Tier 0) until `arm`.
set -euo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
UNIT=g2-explore
PYPI='$HOME/bittleX/pi_pipeline/.venv/bin/python'

# A roam needs a fresh floor label: its walks record it, and a run with no fresh label cannot feed the body fits (tools/g2_ingest.py). Asked on every start when the label is
# unknown or older than G2_FLOOR_MAX_AGE_H (default 1). Without a terminal there is nobody to ask, so the start is refused until the label is set (`g2floor tile`) or
# G2_FLOOR_SKIP=1 says to go without one.
floor_gate() {
  [ "${G2_FLOOR_SKIP:-0}" = 1 ] && return 0
  local got label age ans
  got=$(ssh "$G2_PI" "cd ~/bittleX && $PYPI -m pi_pipeline.telemetry surface-age" 2>/dev/null || true)
  label=${got%% *}; age=${got##* }
  if [ -n "$label" ] && [ "$label" != unknown ] && [ "$age" != "?" ] && awk -v a="$age" -v m="${G2_FLOOR_MAX_AGE_H:-1}" 'BEGIN{exit !(a<=m)}'; then
    return 0
  fi
  if [ -t 0 ]; then
    read -r -p "Floor label is '${label:-unknown}' (set ${age:-?} h ago). Which floor is G2 on now? [Enter keeps '${label:-unknown}']: " ans
    ans=${ans:-$label}
    if [ -z "$ans" ] || [ "$ans" = unknown ]; then echo "no floor given: this roam will not count for training"; return 0; fi
    ssh "$G2_PI" "cd ~/bittleX && $PYPI -m pi_pipeline.telemetry surface '$ans'" >/dev/null && echo "floor set to $ans"
    return 0
  fi
  echo "The floor label is '${label:-unknown}' (set ${age:-?} h ago). Set it first: g2floor <hardwood|tile|carpet|...>   (or G2_FLOOR_SKIP=1 to go without)." >&2
  return 3
}

case "${1:-status}" in
  start|stationary)
    floor_gate || exit $?
    EXTRA=""; [ "$1" = stationary ] && EXTRA=" --stationary"
    ssh "$G2_PI" "rm -f ~/.g2_explore_cmd; sudo systemd-run --unit=$UNIT --collect --uid=\$(id -un) \
      -p WorkingDirectory=\$HOME/bittleX -p KillSignal=SIGTERM -p TimeoutStopSec=15 \
      -p ExecStartPre='+/bin/systemctl stop g2-voice' \
      -p ExecStopPost=\"+/bin/sh -c '\$HOME/bittleX/pi_pipeline/.venv/bin/python -m pi_pipeline.link.check_serial send d >/dev/null 2>&1; true'\" \
      -p ExecStopPost='+/bin/systemctl --no-block start g2-voice' \
      -E G2_FEATURES='+vision,+vision_perception,+vision_safety,+explore,-avoidance_act,-object_gallery' -E G2_LOG_HEARD=1 -E PYTHONFAULTHANDLER=1 -E G2_PROFILE=${G2_PROFILE:-0} -E VISION_SENSOR_OPT=${VISION_SENSOR_OPT:-0} -E G2_WALL_KEEP_ALL=${G2_WALL_KEEP_ALL:-0} -E G2_SURVEY_LOOKS=${G2_SURVEY_LOOKS:-0} -E G2_SURVEY_CHECK=${G2_SURVEY_CHECK:-1} -E G2_AUDIO_GATE=${G2_AUDIO_GATE:-1} -E G2_NARRATE_START_QUIET_S=${G2_NARRATE_START_QUIET_S:-8} -E G2_WALL_STEER=${G2_WALL_STEER:-1} -E G2_IMU_CONTACT=${G2_IMU_CONTACT:-1} -E G2_INTEREST_FALLBACK_S=${G2_INTEREST_FALLBACK_S:-300} -E G2_SURVEY_FIRST_S=${G2_SURVEY_FIRST_S:-30} -E G2_SURVEY_COOLDOWN_S=${G2_SURVEY_COOLDOWN_S:-60} \
      \$HOME/bittleX/pi_pipeline/.venv/bin/python -m pi_pipeline.explore_session --roam-s ${2:-600}$EXTRA" ;;
  arm|disarm|halt|release|stop)
    # only while a session is running: a command written to the file with no session would be read by the NEXT session as soon as it starts (a stale halt stopped a fresh run, 2026-10-07)
    ssh "$G2_PI" "if [ \"\$(systemctl is-active $UNIT)\" = active ]; then echo $1 > ~/.g2_explore_cmd; else echo 'no exploration session is running: $1 not sent (and not left behind)'; fi" ;;
  status) ssh "$G2_PI" "systemctl is-active $UNIT; systemctl is-active g2-voice" ;;
  report) # the report of the latest exploration (walks, speech lag, camera, wake word, checks); `report html` also saves the page here and opens it
    ssh "$G2_PI" "cd ~/bittleX && $PYPI -m pi_pipeline.diag report --kind explore --html /tmp/g2_explore_report.html"
    if [ "${2:-}" = html ]; then
      OUT="$HOME/g2_logs/explore_report_$(date +%Y%m%d_%H%M%S).html"; mkdir -p "$HOME/g2_logs"
      scp -q "$G2_PI:/tmp/g2_explore_report.html" "$OUT" && echo "saved $OUT" && { open "$OUT" 2>/dev/null || true; }
    fi ;;
  logs)   ssh "$G2_PI" "journalctl -u $UNIT -n 60 --no-pager | cut -c1-200" ;;
  heard)  ssh "$G2_PI" "journalctl -u $UNIT -n 400 --no-pager | grep -E 'wake word heard|nothing recognized|heard:|naming request|answered|not a command|picture saved|no picture' | cut -c1-190 | tail -${2:-25}" ;;
  *) echo "usage: $0 start [ROAM_S, default 600; 0 = no cap] | stationary [ROAM_S] | arm | disarm | halt | release | stop | status | logs | heard | report [html]"; exit 2 ;;
esac
