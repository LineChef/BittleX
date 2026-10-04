#!/usr/bin/env bash
# Back up G2's memory DB (conversation log + facts) from the Pi to this machine.
#   G2_PI=<user>@g2pi.local bash tools/g2_memory_backup.sh          # or: g2membackup (g2_aliases.sh)
# Lands in $G2_BACKUP_DIR (default ~/Desktop/OneFolder/G2/memory-backups), outside the repo -- it holds conversations.
# Uses SQLite's serialize() on the Pi (a consistent snapshot of a live DB, nothing written on the Pi), then
# integrity-checks the copy. Restore: see docs/plan-detail/phase9-memory.md.
set -euo pipefail
host="${G2_PI:?set G2_PI=<user>@g2pi.local}"
dest="${G2_BACKUP_DIR:-$HOME/Desktop/OneFolder/G2/memory-backups}"
remote_db="${G2_REMOTE_MEMORY_DB:-.local/share/g2/g2_memory.db}"   # relative to the Pi user's home
mkdir -p "$dest"
out="$dest/g2_memory-$(date +%Y%m%d-%H%M%S).db"
ssh -o BatchMode=yes -o ConnectTimeout=6 "$host" python3 - "$remote_db" > "$out" <<'PY'
import os, sqlite3, sys
p = os.path.join(os.path.expanduser("~"), sys.argv[1])
c = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
sys.stdout.buffer.write(c.serialize())
PY
check="$(python3 -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('pragma integrity_check').fetchone()[0], c.execute('select count(*) from exchanges').fetchone()[0], c.execute('select count(*) from facts').fetchone()[0])" "$out")"
set -- $check
[ "$1" = ok ] || { echo "backup FAILED integrity check: $out" >&2; exit 1; }
echo "backed up: $out  ($2 exchanges, $3 facts)"
