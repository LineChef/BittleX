#!/usr/bin/env bash
# Wait for G2's Pi to come online, then deploy pi_pipeline/ and the deployed policy to it (rsync, as docs/guides/pi-bring-up.md section 7) and restart g2-voice. Needs G2_PI.
#   g2_deploy_when_online.sh [--once] [--max-hours N] [--replace]     --once: check one time, deploy if the Pi answers, else exit 1.  default wait: 24 h
#   g2_deploy_when_online.sh --cancel                      disarm the waiting watcher (it deploys ONCE, then exits; it never repeats on later power-ons)
# Only one waiting watcher may exist (pid in ~/g2_logs/deploy_waiter.pid): a second start refuses unless --replace. A watcher deploys whatever the working tree holds when the Pi answers, so a stale one
# can ship code hours after it was armed; check with `cat ~/g2_logs/deploy_waiter.pid` and cancel what you no longer want.
# It deploys the last COMMIT, never the working folder: pi_pipeline/ is exported from HEAD at deploy time (2026-10-18: a waiting watcher shipped
# half-finished, uncommitted code), and uncommitted changes under pi_pipeline/ are listed in the log as not deployed. Commit first, then deploy.
# Log: ~/g2_logs/deploy_<time>.log. Writes ~/g2_logs/deploy_done when the deploy succeeded. The Pi's own .env, .venv and memory data are never touched.
# g2-voice is NOT restarted while a baseline run (g2-baseline) is active: that unit stops g2-voice itself and starts it again when it ends.
set -uo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGDIR="$HOME/g2_logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/deploy_$(date +%Y%m%d_%H%M%S).log"
ONCE=0; MAX_H=24; REPLACE=0; CANCEL=0
while [ $# -gt 0 ]; do case "$1" in --once) ONCE=1 ;; --max-hours) MAX_H="$2"; shift ;; --replace) REPLACE=1 ;; --cancel) CANCEL=1 ;; *) echo "usage: $0 [--once] [--max-hours N] [--replace] | --cancel"; exit 2 ;; esac; shift; done
PIDFILE="$LOGDIR/deploy_waiter.pid"
OLD=$(cat "$PIDFILE" 2>/dev/null || true)
if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then ARMED=1; else ARMED=0; fi
if [ "$CANCEL" = 1 ]; then
  if [ "$ARMED" = 1 ]; then kill "$OLD"; rm -f "$PIDFILE"; echo "cancelled the waiting deploy watcher (pid $OLD)"; else echo "no deploy watcher is armed"; fi
  exit 0
fi
if [ "$ONCE" = 0 ]; then
  if [ "$ARMED" = 1 ]; then
    if [ "$REPLACE" = 1 ]; then kill "$OLD"; echo "replaced the armed watcher (pid $OLD)"; else echo "a deploy watcher is already armed (pid $OLD): use --replace or --cancel"; exit 3; fi
  fi
  echo $$ > "$PIDFILE"
fi
EXPORT=""
cleanup() { [ "$ONCE" = 0 ] && rm -f "$PIDFILE"; [ -n "$EXPORT" ] && rm -rf "$EXPORT"; [ -n "${CTL:-}" ] && ssh -o ControlPath="$CTL" -O exit "$G2_PI" 2>/dev/null; return 0; }
trap cleanup EXIT
say() { echo "$(date '+%I:%M:%S %p')  $*" | tee -a "$LOG"; }
# one ssh connection for the whole deploy (each new one cost about half a second; there were ten): every ssh and rsync below reuses it
CTL="$(mktemp -u "${TMPDIR:-/tmp}/g2ssh.XXXXXX")"
SSHO="-o ControlMaster=auto -o ControlPath=$CTL -o ControlPersist=120"
pissh() { ssh $SSHO "$@"; }
reachable() { ssh -o BatchMode=yes -o ConnectTimeout=5 $SSHO "$G2_PI" true 2>/dev/null; }

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

# never deploy while G2 is exploring or walking (user rule 2026-10-10; a deploy mid-run restarted the voice service on top of a running exploration)
if pissh "$G2_PI" 'systemctl is-active --quiet g2-explore || systemctl is-active --quiet g2-baseline || pgrep -f "[r]un_gait" >/dev/null || [ -n "$(find ~/.local/share/g2/goal_running -mmin -45 2>/dev/null)" ]'; then
  say "an exploration, a baseline run or a walk is running on the Pi: NOT deploying (stop it first: bash tools/g2_safe_stop.sh all)"
  exit 1
fi

HEAD_SHORT=$(git -C "$ROOT" rev-parse --short HEAD) || { say "not a git checkout: NOT deploying"; exit 1; }
EXPORT=$(mktemp -d "${TMPDIR:-/tmp}/g2deploy.XXXXXX")
git -C "$ROOT" archive HEAD pi_pipeline | tar -x -C "$EXPORT" || { say "could not export commit $HEAD_SHORT: NOT deploying"; exit 1; }
echo "$HEAD_SHORT" > "$EXPORT/pi_pipeline/.deployed_commit"       # recorded in every run log
DIRTY=$(git -C "$ROOT" status --porcelain -- pi_pipeline)
if [ -n "$DIRTY" ]; then
  say "NOTE: $(echo "$DIRTY" | wc -l | tr -d ' ') uncommitted change(s) under pi_pipeline/ are NOT deployed (only commit $HEAD_SHORT is):"
  echo "$DIRTY" | head -10 | tee -a "$LOG"
fi
say "rsync pi_pipeline/ (commit $HEAD_SHORT)"
# --checksum and no times: the export's file times are all the commit's, so files are compared by content; the filter drops the
# "time differs only" lines so the log lists the files that really changed
rsync -e "ssh $SSHO" -rlpz --checksum --itemize-changes --exclude .venv --exclude __pycache__ --exclude memory/data --exclude .pytest_cache --exclude .env \
      "$EXPORT/pi_pipeline/" "$G2_PI:bittleX/pi_pipeline/" 2>&1 | grep -Ev '^\.[fdL]\.\.T\.+ ' | tee -a "$LOG" | tail -n 25
[ "${PIPESTATUS[0]}" = 0 ] || { say "rsync of pi_pipeline failed"; exit 1; }
POLICY=$(sed -n 's/^DEFAULT_POLICY = "\([^"]*\)".*/\1/p' "$EXPORT/pi_pipeline/gait/residual_policy.py" | head -1)     # (not python: the system python3 has no numpy, the import failed, the name came back empty and rsync copied the wrong thing)
TR="$ROOT/rl_training/opencat-gym/trained"
[ -n "$POLICY" ] && [ -f "$TR/$POLICY" ] || { say "could not read DEFAULT_POLICY, or its file is missing: NOT syncing the policy"; exit 1; }
FILES=("$TR/$POLICY" "$TR/$POLICY.json")
# every policy an attachment's saved gait names (pi_pipeline/attachments/gait_profiles.json), so switching attachments never needs another deploy
# (plain json module only: the system python3 has no numpy, and this never imports pi_pipeline)
EXTRA=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("\n".join(sorted({e["policy"] for p in d.values() for e in ([p["current"]] if p.get("current") else []) + p.get("history", []) if e.get("policy")})))' \
        "$EXPORT/pi_pipeline/attachments/gait_profiles.json" 2>/dev/null || true)
for P in $EXTRA; do
  [ "$P" = "$POLICY" ] && continue
  if [ -f "$TR/$P" ] && [ -f "$TR/$P.json" ]; then FILES+=("$TR/$P" "$TR/$P.json"); else say "attachment policy $P (or its sidecar) is missing here: not synced"; fi
done
# the carpet-only policy ("G2, carpet mode" loads it; residual_policy.CARPET_POLICY), once one is promoted under that name; without it carpet mode keeps the default policy
CARPET=$(sed -n 's/^CARPET_POLICY = "\([^"]*\)".*/\1/p' "$EXPORT/pi_pipeline/gait/residual_policy.py" | head -1)
if [ -n "$CARPET" ] && [ -f "$TR/$CARPET" ] && [ -f "$TR/$CARPET.json" ]; then FILES+=("$TR/$CARPET" "$TR/$CARPET.json"); fi
# the import check runs on the Pi at the same time as the policy copy and the clean-up (about 12 s on the Pi: it was a separate wait)
IMPORT_OUT="$(mktemp "${TMPDIR:-/tmp}/g2imp.XXXXXX")"
say "checking the new code imports on the Pi (in parallel with the policy copy)"
( pissh "$G2_PI" 'cd ~/bittleX && pi_pipeline/.venv/bin/python -c "import pi_pipeline.voice.api_log, pi_pipeline.voice.usage, pi_pipeline.voice.conversation; print(\"imports ok\")"' > "$IMPORT_OUT" 2>&1; echo $? > "$IMPORT_OUT.rc" ) &
IMPORT_PID=$!
say "rsync ${#FILES[@]} policy file(s), one transfer"
rsync -e "ssh $SSHO" -az "${FILES[@]}" "$G2_PI:bittleX/rl_training/opencat-gym/trained/" 2>&1 | tee -a "$LOG"
[ "${PIPESTATUS[0]}" = 0 ] || { say "rsync of the policies failed"; exit 1; }

# keep the Pi's trained/ folder to the exported release candidates only (stray files there are leftovers of earlier syncs)
STRAY=$(pissh "$G2_PI" 'cd ~/bittleX/rl_training/opencat-gym/trained 2>/dev/null && ls -1 | grep -vE "^Release_Candidate[^ /]*_ppo\.onnx(\.json)?$"' 2>/dev/null || true)
if [ -n "$STRAY" ]; then
  say "removing $(echo "$STRAY" | wc -l | tr -d ' ') stray file(s) from the Pi's trained/ folder: $(echo "$STRAY" | head -5 | tr '\n' ' ')"
  echo "$STRAY" | pissh "$G2_PI" 'cd ~/bittleX/rl_training/opencat-gym/trained && xargs -d "\n" rm -rf --' 2>&1 | tee -a "$LOG"
fi

wait "$IMPORT_PID" 2>/dev/null
tee -a "$LOG" < "$IMPORT_OUT"
IMPORT_RC=$(cat "$IMPORT_OUT.rc" 2>/dev/null || echo 1); rm -f "$IMPORT_OUT" "$IMPORT_OUT.rc"
[ "$IMPORT_RC" = 0 ] || { say "the new code does not import on the Pi; NOT restarting g2-voice"; exit 1; }

if pissh "$G2_PI" 'systemctl is-active --quiet g2-baseline'; then
  say "a baseline run is active: leaving g2-voice alone (it restarts after the run); the new code loads then"
else
  say "restarting g2-voice"
  pissh "$G2_PI" 'sudo -n systemctl restart g2-voice; for i in 1 2 3 4 5 6 7 8 9 10; do systemctl is-active --quiet g2-voice && break; sleep 0.5; done; systemctl is-active g2-voice' 2>&1 | tee -a "$LOG"
fi
say "DEPLOYED. API call log on the Pi: ~/.local/share/g2/api_calls.jsonl  (python -m pi_pipeline.voice.api_log --last 40)"
( G2_PI="$G2_PI" nohup bash "$(dirname "$0")/g2_sync.sh" run --force goals >> "$LOG" 2>&1 & ) || true      # in the background, the deploy does not wait for it: a Mac copy of his goal data, readable while he is off (user, 2026-11-01); the other copies run on their own schedule
date > "$LOGDIR/deploy_done"
