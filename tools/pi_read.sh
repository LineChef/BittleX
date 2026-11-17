#!/usr/bin/env bash
# Read-only questions to G2's Pi with FIXED subcommands: nothing else can be run through this script, so one narrow permission rule can cover it (2026-11-17).
#   pi_read.sh status                      what is running (voice, exploration, punt, baseline, a goal), the deployed commit, the Pi's clock and whether it is NTP-synced
#   pi_read.sh battery                     the last pack readings (volts, newest last) and the percent for the newest
#   pi_read.sh journal [PATTERN [SINCE]]   the voice service's log lines matching PATTERN (default g2.goal) since SINCE (default "10 minutes ago"), last 40
#   pi_read.sh falls                       the three newest fall records (file names)
#   pi_read.sh goal-log [N]                the last N (default 20) lines of the goal session log
#   pi_read.sh goal-running                prints RUNNING or IDLE (a goal session holds ~/.local/share/g2/goal_running)
# Needs G2_PI. PATTERN is a plain extended regex of letters, digits, space, | : _ . - only; SINCE likewise; anything else is refused.
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
sub="${1:-status}"; shift || true
r() { ssh -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" "$1"; }
safe() { [[ "$1" =~ ^[A-Za-z0-9_.:\ \|\-]+$ ]] || { echo "refused: only letters, digits, space and | : _ . - are allowed" >&2; exit 2; }; }
case "$sub" in
  status) r 'echo "services: $(systemctl is-active g2-voice g2-explore g2-punt g2-baseline | tr "\n" " ")"; if [ -e ~/.local/share/g2/goal_running ]; then echo "goal: RUNNING"; else echo "goal: idle"; fi; echo "deployed: $(cat ~/bittleX/pi_pipeline/.deployed_commit 2>/dev/null)"; echo "clock: $(date) ntp-synced: $(timedatectl show -p NTPSynchronized --value)"; echo "up: $(uptime -p)"' ;;
  battery) r 'tail -n 3 ~/.local/share/g2/battery_voltage.csv; line=$(tail -n 1 ~/.local/share/g2/battery_voltage.csv); v=$(echo "$line" | cut -d, -f2); t=$(echo "$line" | cut -d, -f1); cd ~/bittleX && PYTHONPATH=. pi_pipeline/.venv/bin/python -c "from pi_pipeline.power import battery; print(\"newest: %d percent (logged $t; the log is only as fresh as that time: the run gate reads the pack again)\" % battery.pack_percent(float(\"$v\")))" 2>/dev/null' ;;
  journal) pat="${1:-g2.goal}"; since="${2:-10 minutes ago}"; safe "$pat"; safe "$since"
           r "journalctl -u g2-voice --since '$since' --no-pager | grep -E '$pat' | sed 's/g2pi python\[[0-9]*\]: //' | cut -c1-200 | tail -n 40" ;;
  falls) r 'ls -t ~/.local/share/g2/falls/*.json 2>/dev/null | head -3' ;;
  goal-log) n="${1:-20}"; [[ "$n" =~ ^[0-9]+$ ]] || { echo "refused: N must be a number" >&2; exit 2; }
            r "tail -n $n ~/.local/share/g2/goal_session.log | cut -c1-200" ;;
  goal-running) r 'test -e ~/.local/share/g2/goal_running && echo RUNNING || echo IDLE' ;;
  *) echo "usage: $0 status|battery|journal [PATTERN [SINCE]]|falls|goal-log [N]|goal-running" >&2; exit 2 ;;
esac
