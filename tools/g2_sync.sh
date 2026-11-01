#!/usr/bin/env bash
# One job for every copy from G2's Pi to this Mac (user, 2026-11-01: "consolidate when all the data transfers from the pi ... to ensure they all happen regularly").
#   g2_sync.sh run [--force TASK|all]    the tasks that are due (each has its own interval); --force runs one task (or all) now, due or not
#   g2_sync.sh status                    each task: when it last worked, how old that copy is, and STALE when it is older than it should be
# The tasks (name, every N minutes, stale after N hours, what it does):
#   goals      30    24   goal journal / state / lessons / turn log / memory log (tools/g2_goal_pull.sh; it curates on the Pi first) -> ~/Desktop/G2Memory/goals
#   pictures   30    48   exploration pictures, then the curated library (tools/g2_curate_auto.sh run)
#   walklogs   30    72   automatic walk logs: ingest and the calibration step (tools/g2_cal_auto.sh run)
#   walls      30    72   wall pictures and the wall estimator's log -> ~/Desktop/G2Memory/g2_pictures/wall
#   memorydb   1440  48   a snapshot of the memory DB, conversations and facts (tools/g2_memory_backup.sh; read-only on the Pi); keeps 14 daily and 8 weekly copies
#   logs       1440  72   the command, noise, API call and power logs and the diag sessions (~/g2_logs) -> ~/Desktop/G2Memory/logs
# Runs from the background loop (tools/g2_bg_jobs.sh, every 30 min), after every deploy and after every `g2goal run`. Skipped when the Pi does not answer, or while an
# exploration, a goal session, a walk or a hardware test is running (the Pi is memory-tight then). One task failing does not stop the others. Nothing is downloaded from
# the internet: everything comes from the Pi on the local network. Status: ~/Desktop/G2Memory/sync_status.json; log: ~/g2_logs/sync.log.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEM="$HOME/Desktop/G2Memory"
STATUS="$MEM/sync_status.json"
LOG="$HOME/g2_logs/sync.log"
mkdir -p "$HOME/g2_logs" "$MEM"
TASKS="goals:30:24 pictures:30:48 walklogs:30:72 walls:30:72 memorydb:1440:48 logs:1440:72"

say() { echo "$(date '+%Y-%m-%d %I:%M:%S %p')  $*" >> "$LOG"; echo "$*"; }

if [ -z "${G2_PI:-}" ]; then                     # a background loop has no shell profile: take the one line that sets it (the value is never printed)
  for f in "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.zprofile"; do
    [ -f "$f" ] && eval "$(grep -m1 '^export G2_PI=' "$f" 2>/dev/null)" && [ -n "${G2_PI:-}" ] && break
  done
fi

stamp() {   # stamp TASK ok|failed MESSAGE
  python3 - "$STATUS" "$1" "$2" "${3:-}" <<'PY'
import json, sys, time
p, task, result, msg = sys.argv[1:5]
try:
    d = json.load(open(p))
except (OSError, ValueError):
    d = {}
t = d.setdefault(task, {})
now = time.strftime("%Y-%m-%d %H:%M:%S")
t["last_try"], t["result"], t["message"] = now, result, msg[:200]
if result == "ok":
    t["last_ok"] = now
json.dump(d, open(p, "w"), indent=1)
PY
}

minutes_since_ok() {   # minutes since TASK last worked (a big number when never)
  python3 - "$STATUS" "$1" <<'PY'
import json, sys, time
try:
    t = json.load(open(sys.argv[1])).get(sys.argv[2], {}).get("last_ok")
    print(int((time.time() - time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S"))) / 60) if t else 10 ** 6)
except (OSError, ValueError):
    print(10 ** 6)
PY
}

pi_busy() {   # prints what is running on the Pi when a sync must wait; nothing when it is free
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$G2_PI" '
    for s in g2-explore g2-goal; do [ "$(systemctl is-active $s 2>/dev/null)" = active ] && echo "$s"; done
    pgrep -fa "pi_pipeline.(goals run|behavior.ball_chase|behavior.claw_look|behavior.three_point)|run_gait.py|fw_skill_log.py|explore_session" | grep -v pgrep | head -1 | cut -c1-80' 2>/dev/null
}

prune_memorydb() {   # keep the 14 newest daily copies and one copy per week for 8 weeks
  python3 - "$MEM/memory-backups" <<'PY'
import os, re, sys, time
d = sys.argv[1]
files = sorted(f for f in os.listdir(d) if re.match(r"g2_memory-\d{8}-\d{6}\.db$", f)) if os.path.isdir(d) else []
by_day = {}
for f in files:
    by_day[f[10:18]] = f                                           # the newest copy of each day
days = sorted(by_day, reverse=True)
keep = set(by_day[x] for x in days[:14])
weeks = {}
for x in days:
    wk = time.strftime("%G-%V", time.strptime(x, "%Y%m%d"))
    weeks.setdefault(wk, by_day[x])
keep |= set(list(weeks.values())[:8])
for f in files:
    if f not in keep:
        os.remove(os.path.join(d, f))
        print("removed old memory copy", f)
PY
}

do_task() {
  case "$1" in
    goals)    G2_PI="$G2_PI" bash "$ROOT/tools/g2_goal_pull.sh" ;;
    pictures) G2_PI="$G2_PI" bash "$ROOT/tools/g2_curate_auto.sh" run ;;
    walklogs) G2_PI="$G2_PI" bash "$ROOT/tools/g2_cal_auto.sh" run ;;
    walls)
      mkdir -p "$MEM/g2_pictures/wall/ring"
      rsync -a "$G2_PI:g2_wall_pics/" "$MEM/g2_pictures/wall/" 2>/dev/null
      rsync -a "$G2_PI:.local/share/g2/wall_pics/" "$MEM/g2_pictures/wall/ring/" 2>/dev/null
      rsync -a "$G2_PI:.local/share/g2/wall_dryrun.jsonl" "$MEM/g2_pictures/wall/wall_dryrun.jsonl" 2>/dev/null
      true ;;
    memorydb) G2_PI="$G2_PI" bash "$ROOT/tools/g2_memory_backup.sh" && prune_memorydb ;;
    logs)
      mkdir -p "$MEM/logs/diag"
      for f in command_log.jsonl noise.jsonl api_calls.jsonl power_log.jsonl; do
        rsync -a "$G2_PI:.local/share/g2/$f" "$MEM/logs/$f" 2>/dev/null
      done
      rsync -a "$G2_PI:g2_logs/" "$MEM/logs/diag/" ;;
    *) echo "unknown task $1"; return 2 ;;
  esac
}

case "${1:-status}" in
  run)
    LOCK="$HOME/g2_logs/sync.lock"                                                   # one sync at a time (the background loop, a deploy, the page's Sync now button)
    if ! mkdir "$LOCK" 2>/dev/null; then
      if kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null; then say "another sync is running: skipped"; exit 0; fi
      rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null || { say "could not take the sync lock: skipped"; exit 0; }
    fi
    echo $$ > "$LOCK/pid"; trap 'rm -rf "$LOCK"' EXIT
    force=""
    [ "${2:-}" = "--force" ] && force="${3:-all}"
    [ -n "${G2_PI:-}" ] || { say "G2_PI is not set: nothing to sync"; exit 0; }
    ssh -o ConnectTimeout=8 -o BatchMode=yes "$G2_PI" true 2>/dev/null || { say "the Pi does not answer: nothing synced"; exit 0; }
    busy="$(pi_busy)"
    if [ -n "$busy" ]; then say "the Pi is busy ($busy): nothing synced, the next run tries again"; exit 0; fi
    for spec in $TASKS; do
      name="${spec%%:*}"; rest="${spec#*:}"; every="${rest%%:*}"
      if [ -z "$force" ] || { [ "$force" != all ] && [ "$force" != "$name" ]; }; then
        [ -n "$force" ] && continue                                                 # --force TASK: only that task
        [ "$(minutes_since_ok "$name")" -lt "$((every - 2))" ] && continue          # not due yet
      fi
      out="$(do_task "$name" 2>&1)"; rc=$?
      echo "$out" >> "$LOG"
      if [ $rc = 0 ]; then stamp "$name" ok "$(printf '%s' "$out" | tail -1)"; say "$name: ok"
      else stamp "$name" failed "$(printf '%s' "$out" | tail -1)"; say "$name: FAILED ($(printf '%s' "$out" | tail -1 | cut -c1-120))"; fi
    done ;;
  status)
    for spec in $TASKS; do
      name="${spec%%:*}"; rest="${spec#*:}"; every="${rest%%:*}"; stale_h="${rest#*:}"
      python3 - "$STATUS" "$name" "$every" "$stale_h" <<'PY'
import json, sys, time
p, name, every, stale_h = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
try:
    t = json.load(open(p)).get(name, {})
except (OSError, ValueError):
    t = {}
ok = t.get("last_ok")
if ok:
    age_h = (time.time() - time.mktime(time.strptime(ok, "%Y-%m-%d %H:%M:%S"))) / 3600
    when = time.strftime("%b %-d %-I:%M %p", time.strptime(ok, "%Y-%m-%d %H:%M:%S"))
    age = f"{age_h * 60:.0f} min" if age_h < 1 else f"{age_h:.1f} h" if age_h < 48 else f"{age_h / 24:.1f} days"
    flag = "  STALE" if age_h > stale_h else ""
    print(f"{name:9s} last copy {when} ({age} ago){flag}" + ("" if t.get("result") == "ok" else f"  (last try failed: {t.get('message', '')[:80]})"))
else:
    print(f"{name:9s} never copied yet  STALE")
PY
    done ;;
  *) echo "usage: $0 run [--force TASK|all] | status"; exit 2 ;;
esac
