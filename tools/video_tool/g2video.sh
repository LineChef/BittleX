#!/bin/bash
# g2video sheet FILE [--from S] [--to S] [--step S] | g2video audio FILE [--from S] [--to S] [--min PEAK]
# Reads a clip on the Mac with macOS's own video framework (swift, AVFoundation): nothing is downloaded or sent anywhere. The frames are written to a NEW temp folder (the pictures show the home:
# delete the folder when done, never commit them); the contact sheet's path is printed.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/../../pi_pipeline/.venv/bin/python"
cmd="${1:-}"; file="${2:-}"
[ -n "$cmd" ] && [ -f "$file" ] || { echo "usage: g2video sheet|audio FILE [--from S] [--to S] [--step S] [--min PEAK]"; exit 2; }
shift 2
from=0; to=9999; step=0.5; minpeak=1500
while [ $# -gt 0 ]; do
  case "$1" in
    --from) from="$2"; shift 2 ;; --to) to="$2"; shift 2 ;; --step) step="$2"; shift 2 ;; --min) minpeak="$2"; shift 2 ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
case "$cmd" in
  sheet)
    dir="$(mktemp -d "${TMPDIR:-/tmp}/g2video.XXXXXX")" || exit 1
    swift "$HERE/frames.swift" "$file" "$dir" "$step" "$from" "$to" 2>/dev/null | grep -E "^(fps|frames)"
    "$PY" "$HERE/sheet.py" "$dir" "$dir/sheet.png" "$from" "$step" || { echo "no frames were written"; exit 1; }
    echo "contact sheet: $dir/sheet.png   (delete the folder $dir when done: it shows the home)"
    ;;
  audio) swift "$HERE/audio.swift" "$file" "$from" "$to" "$minpeak" 2>/dev/null ;;
  *) echo "usage: g2video sheet|audio FILE ..."; exit 2 ;;
esac
