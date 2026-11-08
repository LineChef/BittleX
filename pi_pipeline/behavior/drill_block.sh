#!/bin/bash
# Run on the Pi: a block of transition-drill rounds back to back, one go for the block (owner, 2026-11-07). Stops at the first fall or a real void round; writes one file per round and a status file.
#   pi_pipeline/behavior/drill_block.sh VARIANT [LAST_ROUND] [FIRST_ROUND] [-- extra drill args, e.g. --turns-only]
#   G2_GYRO_BALANCE=0 pi_pipeline/behavior/drill_block.sh baseline 3        # the gyro-balance A/B: the same block with the env set to 0 and to 1
#   pi_pipeline/behavior/drill_block.sh stop                                # kill a running block; sends NOTHING to G2 (add "rest" to send krest, only when he is standing)
# Refuses to start while the g2-voice service is running (it shares the serial port: it ran beside the drill for 25 minutes on 2026-11-07).
D=${G2_HW_DIR:-$HOME/g2_runs/hw_$(date +%Y%m%d)}; mkdir -p "$D"; cd "$(dirname "$0")/../.." || exit 1
if [ "$1" = "stop" ]; then
  kill -TERM "$(cat "$D/runner.pid" 2>/dev/null)" 2>/dev/null
  for p in $(pgrep -f "behavior.transition_drill"); do kill -KILL "$p" 2>/dev/null; done
  echo "$(date +%T) STOPPED BY HAND" >> "$D/status_stop.txt"
  if [ "$2" = "rest" ]; then pi_pipeline/.venv/bin/python -c "
from pi_pipeline.link.serial_link import SerialLink
lk = SerialLink('/dev/serial0'); lk.connect(); lk.send('krest', read_reply=False, settle=0.0); print('krest sent')" 2>&1 | grep -v '^LOG' | tail -1
  else echo "drill killed; nothing sent to G2"; fi
  exit 0
fi
V=$1; N=${2:-3}; S=${3:-1}; shift 3 2>/dev/null; [ "$1" = "--" ] && shift
if systemctl is-active --quiet g2-voice; then echo "g2-voice is running: stop it first (sudo systemctl stop g2-voice)"; exit 1; fi
echo $$ > "$D/runner.pid"
[ "$S" = 1 ] && : > "$D/status_$V.txt"
for r in $(seq "$S" "$N"); do
  F=$D/${V}_r$r.txt
  echo "$(date +%T) start $V round $r" >> "$D/status_$V.txt"
  PYTHONUNBUFFERED=1 pi_pipeline/.venv/bin/python -m pi_pipeline.behavior.transition_drill --variant "$V" --cycles 10 "$@" 2>&1 | grep --line-buffered -v "^LOG\|Warning" > "$F"
  R=$(grep "^RESULT" "$F" | tail -1)
  echo "$(date +%T) end $V round $r :: $(grep -m1 '^battery' "$F") :: ${R:-NO RESULT LINE}" >> "$D/status_$V.txt"
  STOP=0; [ -z "$R" ] && STOP=1
  echo "$R" | grep -q "'fell': True" && STOP=1
  echo "$R" | grep -q "'void'" && STOP=1
  if [ $STOP = 1 ]; then echo "$(date +%T) STOPPED after round $r" >> "$D/status_$V.txt"; break; fi
done
echo "$(date +%T) BLOCK DONE $V" >> "$D/status_$V.txt"
