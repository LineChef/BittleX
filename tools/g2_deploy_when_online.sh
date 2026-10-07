#!/usr/bin/env bash
# Wait for G2's Pi to come online, then deploy pi_pipeline/ and the deployed policy to it (rsync, as docs/guides/pi-bring-up.md section 7) and restart g2-voice. Needs G2_PI.
#   g2_deploy_when_online.sh [--once] [--max-hours N]     --once: check one time, deploy if the Pi answers, else exit 1.  default wait: 24 h
# Log: ~/g2_logs/deploy_<time>.log. Writes ~/g2_logs/deploy_done when the deploy succeeded. The Pi's own .env, .venv and memory data are never touched.
# g2-voice is NOT restarted while a baseline run (g2-baseline) is active: that unit stops g2-voice itself and starts it again when it ends.
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGDIR="$HOME/g2_logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/deploy_$(date +%Y%m%d_%H%M%S).log"
ONCE=0; MAX_H=24
while [ $# -gt 0 ]; do case "$1" in --once) ONCE=1 ;; --max-hours) MAX_H="$2"; shift ;; *) echo "usage: $0 [--once] [--max-hours N]"; exit 2 ;; esac; shift; done
say() { echo "$(date '+%I:%M:%S %p')  $*" | tee -a "$LOG"; }
reachable() { ssh -o BatchMode=yes -o ConnectTimeout=5 "$G2_PI" true 2>/dev/null; }

rm -f "$LOGDIR/deploy_done"
say "waiting for the Pi (max ${MAX_H} h, once=$ONCE); log $LOG"
deadline=$(( $(date +%s) + MAX_H * 3600 ))
until reachable; do
  [ "$ONCE" = 1 ] && { say "the Pi does not answer"; exit 1; }
  [ "$(date +%s)" -ge "$deadline" ] && { say "gave up: the Pi never came online"; exit 1; }
  sleep 30
done
say "the Pi answers; letting its services settle for 25 s"
[ "$ONCE" = 1 ] || sleep 25
reachable || { say "the Pi stopped answering; not deploying"; exit 1; }

say "rsync pi_pipeline/"
rsync -az --itemize-changes --exclude .venv --exclude __pycache__ --exclude memory/data --exclude .pytest_cache --exclude .env \
      "$ROOT/pi_pipeline/" "$G2_PI:bittleX/pi_pipeline/" 2>&1 | tee -a "$LOG" | tail -n 25
[ "${PIPESTATUS[0]}" = 0 ] || { say "rsync of pi_pipeline failed"; exit 1; }
POLICY=$(python3 -c "import sys; sys.path.insert(0, '$ROOT/pi_pipeline/gait'); import residual_policy as r; print(r.DEFAULT_POLICY)")
say "rsync policy $POLICY"
rsync -az "$ROOT/rl_training/opencat-gym/trained/$POLICY" "$ROOT/rl_training/opencat-gym/trained/$POLICY.json" "$G2_PI:bittleX/rl_training/opencat-gym/trained/" 2>&1 | tee -a "$LOG"
[ "${PIPESTATUS[0]}" = 0 ] || { say "rsync of the policy failed"; exit 1; }

say "checking the new code imports on the Pi"
ssh "$G2_PI" 'cd ~/bittleX && pi_pipeline/.venv/bin/python -c "import pi_pipeline.voice.api_log, pi_pipeline.voice.usage, pi_pipeline.voice.conversation; print(\"imports ok\")"' 2>&1 | tee -a "$LOG"
[ "${PIPESTATUS[0]}" = 0 ] || { say "the new code does not import on the Pi; NOT restarting g2-voice"; exit 1; }

if ssh "$G2_PI" 'systemctl is-active --quiet g2-baseline'; then
  say "a baseline run is active: leaving g2-voice alone (it restarts after the run); the new code loads then"
else
  say "restarting g2-voice"
  ssh "$G2_PI" 'sudo -n systemctl restart g2-voice; sleep 3; systemctl is-active g2-voice' 2>&1 | tee -a "$LOG"
fi
say "DEPLOYED. API call log on the Pi: ~/.local/share/g2/api_calls.jsonl  (python -m pi_pipeline.voice.api_log --last 40)"
date > "$LOGDIR/deploy_done"
