#!/usr/bin/env bash
# Copy G2's goal data from the Pi to this Mac, so it can be read while G2 is off (user, 2026-11-01):
#   G2_PI=<user>@<host> bash tools/g2_goal_pull.sh          # or: g2goal pull (g2_aliases.sh)
# Lands in $G2_GOALS_DIR (default ~/Desktop/G2Memory/goals), outside the repo:
#   goal_journal.jsonl, goal_state.json, goals.json, goal_overrides.json   the goal sessions, what he learned, your goals and overrides
#   punt_settings.json, wall_settings.json, chase_pace.json                 the chase and wall settings in use, his measured walk and turn pace
#   turn_log.jsonl                                                          every chase turn and why
#   lessons.jsonl                                                           the lessons he saved to memory (facts with source goal_lesson), read-only from his memory DB
#   history/YYYYMMDD/                                                       the same files as they were at the first pull of each day (nothing is lost if the Pi's copy is reset)
#   memory_log.jsonl                                                        the Pi's memory readings every 10 s (diag/memlog.py; `g2mem` summarizes it, from this copy when G2 is off)
#   goal_curation/curation_report.md                                        what the last curation retired, deleted and flagged (and why)
#   pulled_at.txt                                                           when this copy was taken
# Run automatically after every deploy (tools/g2_deploy_when_online.sh) and after `g2goal run`. G2 off: it says so and leaves the last copy as it is. Reads only on the Pi.
set -uo pipefail
host="${G2_PI:?set G2_PI=<user>@<host>}"
dest="${G2_GOALS_DIR:-$HOME/Desktop/G2Memory/goals}"
mkdir -p "$dest"
if ! ssh -o BatchMode=yes -o ConnectTimeout=6 "$host" true 2>/dev/null; then
  echo "G2 is offline: the copy in $dest is from $(cat "$dest/pulled_at.txt" 2>/dev/null || echo 'never')"
  exit 0
fi
# curate the Pi's goal data first (retire old-scoring attempts, check the saved lessons, rotate logs: `g2goal curate`), then copy the curated data down
ssh -o BatchMode=yes -o ConnectTimeout=6 "$host" 'cd ~/bittleX && PYTHONPATH=. pi_pipeline/.venv/bin/python -m pi_pipeline.goals curate' 2>&1 | sed 's/^/curate: /'
day="$dest/history/$(date +%Y%m%d)"
if [ ! -d "$day" ] && ls "$dest"/*.json* >/dev/null 2>&1; then             # keep the copy as it was before today's first pull
  mkdir -p "$day" && cp -p "$dest"/*.json* "$day/" 2>/dev/null
fi
files="memory_log.jsonl goal_curation/curation_report.md goal_journal.jsonl goal_state.json goals.json goal_overrides.json punt_settings.json wall_settings.json chase_pace.json turn_log.jsonl"
# one tar over ssh of the files that exist (the Mac's openrsync has no --ignore-missing-args, and a missing file must not stop the others)
ssh -o BatchMode=yes -o ConnectTimeout=6 "$host" "cd ~/.local/share/g2 && tar cf - \$(ls $files 2>/dev/null)" | tar xpf - -C "$dest" \
  || echo "some files could not be copied; the rest are in $dest"
ssh -o BatchMode=yes -o ConnectTimeout=6 "$host" python3 - > "$dest/lessons.jsonl.tmp" <<'PY'
import json, os, sqlite3
p = os.path.expanduser("~/.local/share/g2/g2_memory.db")
if os.path.exists(p):
    c = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    for i, ts, fact in c.execute("select id, ts, fact from facts where source = 'goal_lesson' order by id"):
        print(json.dumps({"id": i, "time": ts, "lesson": fact}))
PY
[ $? = 0 ] && mv "$dest/lessons.jsonl.tmp" "$dest/lessons.jsonl" || rm -f "$dest/lessons.jsonl.tmp"
python3 - "$dest" <<'PY'
import os, shutil, sys                                                        # the Mac copy's history: 14 days daily, older ones only the Sundays
sys.path.insert(0, os.path.expanduser(os.environ.get("G2_ROOT", ".")))
try:
    from pi_pipeline.goals.curate import prune_mac_history
    for line in prune_mac_history(sys.argv[1]):
        print("curate:", line)
except Exception as e:                                                          # never stops the pull
    print("curate: history pruning skipped:", e)
PY
date "+%Y-%m-%d %-I:%M %p %Z" > "$dest/pulled_at.txt"
echo "goal data copied to $dest: $(cd "$dest" && ls *.json* 2>/dev/null | tr '\n' ' ')"
