# =============================================================================
# G2 project shell helpers  --  companion pipeline, camera, vision-model training
# =============================================================================
# Load once:
#     source /Users/markjohnson/Desktop/OneFolder/projects/bittleX/tools/g2_aliases.sh
# Add that line to ~/.zshrc to make it permanent.
#
# Every command below EXCEPT `g2` / `g2rl` runs in a subshell -- it works from
# any directory and leaves you exactly where you were. `g2` / `g2rl` cd on
# purpose (that's their job); `g2back` returns you.
#
# RL/gait helpers (g2train, g2watch) live in ~/.bash_profile, unchanged.
# `g2help` prints this list.  `docs/guides/cheatsheet.md` is the reference.
# =============================================================================

# G2_ROOT: honour an existing value, else the location of this file.
if [ -z "$G2_ROOT" ] || [ ! -d "$G2_ROOT/pi_pipeline" ]; then
  _g2_self="${BASH_SOURCE[0]:-${(%):-%x}}"                 # bash or zsh
  export G2_ROOT="$(cd "$(dirname "$_g2_self")/.." && pwd)"
  unset _g2_self
fi
# Raw capture root. Default is the multi-class library's raw folder; the old
# single-class face flow needs `export G2_CAP_ROOT=~/Desktop/g2_face_capture`.
export G2_CAP_ROOT="${G2_CAP_ROOT:-$HOME/Desktop/g2_capture_raw}"
_G2_PY="$G2_ROOT/pi_pipeline/.venv/bin/python"            # companion-pipeline venv

# run a python module/script from the repo, pipeline venv, WITHOUT moving the caller
_g2py() { ( cd "$G2_ROOT" && "$_G2_PY" "$@" ); }

# ---------------------------------------------------------------- environment

g2()     { cd "$G2_ROOT" && source pi_pipeline/.venv/bin/activate; }              # cd repo + pipeline venv
g2rl()   { cd "$G2_ROOT/rl_training/opencat-gym" && source "$G2_ROOT/.venv/bin/activate"; }  # cd RL dir + RL venv
g2back() { cd - >/dev/null && pwd; }                                             # return to the dir before g2/g2rl
g2test() { ( cd "$G2_ROOT" && "$_G2_PY" -m pytest pi_pipeline/tests/ -q ); }     # run the pipeline test suite

# ------------------------------------------------- camera capture + model train
# Walkthrough: docs/guides/train-vision-model.md   Routine + poses: docs/vision/capture-checklist.md

# g2cam <name> [session]  -- start the live capture preview at localhost:8080,
#                            saving to ~/Desktop/g2_face_capture/<name>/session_<n>/
g2cam() {
  local name="${1:?usage: g2cam <name> [session]   e.g. g2cam alex 1}" sess="${2:-1}"
  local out="$G2_CAP_ROOT/$name/session_$sess"
  ( pkill -f "camera_preview.py|face_preview.py" 2>/dev/null; sleep 1
    mkdir -p "$out"
    cd "$G2_ROOT" && G2_CAP_OUT="$out" G2_CAP_LABEL="$name" G2_CAM_RES=1 \
      nohup "$_G2_PY" tools/camera_preview.py > /tmp/g2cam.log 2>&1 & )
  sleep 5; open http://localhost:8080
  cat <<EOF

  capturing -> $out
  preview   -> http://localhost:8080   (click "Start capturing" for each pose)
  stop      -> g2cam-stop     then:  g2auto $name   (curate+dedup+promote+rebuild upload, automatic)

  STANDARD POSE SET  (docs/vision/capture-checklist.md)
   1. Close (~1.5 ft), straight on, neutral -- small head movement   ~8s
   2. Close, talking + a smile                                       ~6s
   3. Mid (~3 ft), straight on, neutral                              ~8s
   4. Mid -- slow head turn: full left -> full right -> back         ~10s
   5. Mid -- chin up (hold), then chin down (hold)                   ~8s
   6. Mid -- look away: left, right, up (not at the lens)            ~6s
   7. Mid -- hand near face / push hair back                         ~6s
   8. Far (~5-6 ft), straight on                                     ~6s
   9. Move to a 2nd spot / different light -- repeat 1 + 3           ~10s
   N. NEGATIVES -- step out of frame / point at a wall, ~12s
  Aim ~150-200 saved.  Vary room/light/hair between the 3 sessions.
EOF
}
g2cam-stop() { pkill -f "camera_preview.py|face_preview.py" && echo "preview stopped" || echo "nothing running"; }   # stop the capture preview   # stop the capture preview
g2cam-info() { _g2py tools/camera_preview.py --info; }   # serial port + which model is on the module

# ---- camera MOUNTED on G2 (plugged into the Pi, not the Mac) ----
# Needs  export G2_PI=<user>@g2pi.local  in your shell profile (kept out of the repo).
# Anything that fails or times out says so on the console with a "[g2]" line -- nothing fails silently.
_g2log() { echo "[g2] $*" >&2; }

# ssh with a 6 s connect timeout; reports it when the Pi can't be reached / the call times out (ssh rc 255)
_g2ssh() {
  local host="$1"; shift
  ssh -o BatchMode=yes -o ConnectTimeout=6 "$host" "$@"; local rc=$?
  [ $rc -eq 255 ] && _g2log "ssh to $host failed or timed out (6 s connect timeout) -- is the Pi on and on the network?"
  return $rc
}

# start the camera preview on the Pi, tunnel it to localhost:8080, open it.  $1 host  $2 remote command  $3 local log
_g2_preview() {
  local host="$1" remote="$2" log="$3" i up=""
  _g2ssh "$host" true || return 1
  g2pcam-stop >/dev/null 2>&1
  _g2ssh "$host" 'mkdir -p ~/bittleX/tools' || return 1
  scp -q -o ConnectTimeout=6 "$G2_ROOT/tools/camera_preview.py" "$host:bittleX/tools/" \
    || { _g2log "copying camera_preview.py to $host failed or timed out"; return 1; }
  ( ssh -o BatchMode=yes -o ConnectTimeout=6 -L 8080:127.0.0.1:8080 "$host" "$remote" > "$log" 2>&1 & )
  for i in $(seq 1 40); do curl -s -m 1 -o /dev/null http://localhost:8080/ && { up=1; break; }; sleep 0.5; done
  if [ -z "$up" ]; then
    _g2log "no camera feed after 20 s (timed out). Is the camera plugged into the Pi's data USB port? Last lines of $log:"
    tail -3 "$log" >&2 2>/dev/null; g2pcam-stop >/dev/null 2>&1; return 1
  fi
  open http://localhost:8080      # must open within ~10s or the preview stops itself
}

# g2pcam <name> [session]  -- run the preview on the Pi, tunnel it to localhost:8080,
#                             open it; captures land on the Pi in ~/g2_cap/<name>/session_<n>/
g2pcam() {
  local name="${1:-self}" sess="${2:-1}" host="${G2_PI:?set G2_PI=<user>@g2pi.local (see docs/guides/cheatsheet.md)}"
  local out="g2_cap/$name/session_$sess"
  _g2_preview "$host" "mkdir -p ~/$out; G2_CAP_OUT=~/$out G2_CAP_LABEL=$name ~/bittleX/pi_pipeline/.venv/bin/python -W ignore ~/bittleX/tools/camera_preview.py" /tmp/g2pcam.log || return 1
  echo "preview -> http://localhost:8080   saving on the Pi to ~/$out"
  echo "closing the tab stops it.  then:  g2pcam-pull $name $sess   (copy to the Mac for g2curate)"
}
# g2see  -- just LOOK: live feed + detection boxes from the camera mounted on G2 (plugged into the Pi) at
#           localhost:8080. No name, nothing saved, no capture folder. Closing the tab stops it. Same
#           G2_PI requirement as g2pcam; stop early with g2pcam-stop.
g2see() {
  local host="${G2_PI:?set G2_PI=<user>@g2pi.local (see docs/guides/cheatsheet.md)}"
  _g2_preview "$host" "G2_CAP_OUT=/tmp/g2_see ~/bittleX/pi_pipeline/.venv/bin/python -W ignore ~/bittleX/tools/camera_preview.py" /tmp/g2see.log || return 1
  echo "live view -> http://localhost:8080   (close the tab to stop; g2pcam-stop kills it early)"
}
# g2pcam-pull <name> [session]  -- copy a Pi capture to $G2_CAP_ROOT/<name>/session_<n>/ (then g2curate/g2auto as usual)
g2pcam-pull() {
  local name="${1:?usage: g2pcam-pull <name> [session]}" sess="${2:-1}" host="${G2_PI:?set G2_PI=<user>@g2pi.local}"
  mkdir -p "$G2_CAP_ROOT/$name/session_$sess" || return 1
  rsync -av -e "ssh -o BatchMode=yes -o ConnectTimeout=6" "$host:g2_cap/$name/session_$sess/" "$G2_CAP_ROOT/$name/session_$sess/" \
    || { _g2log "rsync from $host failed or timed out (is the Pi on, and does ~/g2_cap/$name/session_$sess exist?)"; return 1; }
}
# g2membackup  -- snapshot the Pi's memory DB (conversations + facts) to $G2_BACKUP_DIR (default ~/Desktop/OneFolder/G2/memory-backups); needs G2_PI
g2clean() { ( cd "$G2_ROOT" && "$_G2_PY" tools/g2_cleanup.py "$@" ); }          # dry-run list of scratch files (Mac + Pi); `g2clean --apply` deletes them
g2membackup() { bash "$G2_ROOT/tools/g2_memory_backup.sh"; }
# g2wifi list|status|scan|add <ssid>|remove <ssid>  -- manage the Wi-Fi networks the Pi auto-joins (add a phone hotspot as a backup); needs G2_PI
g2wifi() { bash "$G2_ROOT/tools/g2_wifi.sh" "$@"; }
g2pcam-stop() {   # kill the tunnel + the preview process on the Pi
  pkill -f "ssh .*-L 8080:127.0.0.1:8080" 2>/dev/null
  [ -n "$G2_PI" ] && { _g2ssh "$G2_PI" 'ps -eo pid,comm,args | awk "\$2 ~ /^python/ && /camera_preview/ {print \$1}" | xargs -r kill' \
    || { _g2log "could not stop the preview on the Pi (tunnel closed locally)"; return 1; }; }
  echo "pi preview stopped"
}

# g2curate <name> [session] [rotate]  -- filter a raw capture -> <session>/curated/
#   (score, de-dup, rotate upright, YOLO pre-labels). rotate default 0 (camera
#   mounted upright); use 90/180/270 if the contact sheet comes out rotated.
g2curate() {
  local name="${1:?usage: g2curate <name> [session] [rotate]}" sess="${2:-1}" rot="${3:-0}"
  local d="$G2_CAP_ROOT/$name/session_$sess"
  _g2py tools/curate_captures.py "$d" \
    --positives 100 --negatives 15 --class-id 0 --label-region face --rotate "$rot"
  open "$d/curated/_contact_sheet.png" 2>/dev/null
}

# ---- persistent training library (multi-class) --------------------------------
# docs/vision/capture-progress.md.  Two folders:
#   raw (disposable):  ~/Desktop/g2_capture_raw/<class>/session_<k>/[curated/]
#   library (KEEP):     ~/Desktop/g2_vision_library/<class>/  + _MANIFEST.md
# Capture/curate into the raw root:  export G2_CAP_ROOT=~/Desktop/g2_capture_raw
# then  g2cam <class> <k>  ...  g2curate <class> <k> <rot>   (pass --class-id via
# `_g2py tools/curate_captures.py` directly for a non-zero id / a --target).
export G2_LIB_ROOT="${G2_LIB_ROOT:-$HOME/Desktop/g2_vision_library}"

# g2promote <class> [session]  -- copy a reviewed curated session into the library
g2promote() {
  local cls="${1:?usage: g2promote <class> [session]}" sess="${2:-1}"
  _g2py tools/promote_to_library.py \
    "$G2_CAP_ROOT/$cls/session_$sess/curated" --library "$G2_LIB_ROOT" --class "$cls"
}
# g2neg [session] [rotate] [min-sharpness]  -- curate an empty-room sweep as pure
#   negatives + add to the library. min-sharpness defaults to 25 (drops the
#   motion-blur from walking; a flat room scene still passes).
g2neg() {
  local sess="${1:-1}" rot="${2:-0}" sharp="${3:-25}" d="$G2_CAP_ROOT/negatives/session_$sess"
  _g2py tools/curate_captures.py "$d" "$d/curated" --all-negatives --rotate "$rot" \
    --min-sharpness "$sharp"
  open "$d/curated/_contact_sheet.png" 2>/dev/null
  _g2py tools/promote_to_library.py "$d/curated" --library "$G2_LIB_ROOT"
}
# Class-id ORDER for the library. Set it in your shell / .env (the real names
# are personal, so they're not committed):  export G2_VISION_CLASSES="a,b,dog,cat,ledge"
: "${G2_VISION_CLASSES:=}"

g2libstatus() { cat "$G2_LIB_ROOT/_MANIFEST.md" 2>/dev/null || echo "no library yet at $G2_LIB_ROOT"; }   # print the vision library manifest (images per class)

# g2auto [classes] [--dry-run]  -- the FULL automated pipeline: for every
#   pending raw session (curate -> dedup-against-library -> promote), then
#   rebuild the 150/class optimized upload set. Capture (g2cam) is the only
#   manual step; run this after and it produces $G2_LIB_ROOT/upload_optimized/upload/,
#   ready to import into SenseCraft. Idempotent -- safe to re-run any time,
#   already-promoted sessions are skipped automatically.
g2auto() {
  local cls=""
  if [ -n "${1:-}" ] && [ "${1:-}" != "--dry-run" ]; then cls="--classes $1"; shift; fi
  _g2py tools/auto_process_captures.py --library "$G2_LIB_ROOT" --raw-root "$G2_CAP_ROOT" $cls "$@"
}

# ------------------------------------------------------------- vision runtime

# g2vision [labels]  -- run the detection pipeline over serial, print live detections
#   no arg  -> uses VISION_LABELS / VISION_MIN_SCORE from .env (the deployed model)
#   with arg -> overrides the label(s) for this run, e.g. g2vision person
g2vision() {
  local port; port="$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)"
  ( cd "$G2_ROOT"
    [ -n "$1" ] && export VISION_LABELS="$1"
    "$_G2_PY" -m pi_pipeline.vision serial "${port:-/dev/cu.usbmodem58FA1045341}" )
}
g2vision-demo() { _g2py -m pi_pipeline.vision demo; }    # mock feed, no hardware

# g2visioneval [label] [secs]  -- timed measurement: detection rate / confidence /
#   floor / flicker for the dataset-size threshold test. Stand in frame at
#   close/mid/far. Add a 3rd arg 'empty' + point at a clear scene for the
#   false-fire check.  e.g.  g2visioneval <label> 30   |   g2visioneval <label> 30 empty
g2visioneval() {
  local port; port="$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)"
  local extra=""; [ "$3" = "empty" ] && extra="--expect-empty"
  ( cd "$G2_ROOT" && "$_G2_PY" -m pi_pipeline.vision eval \
      "${port:-/dev/cu.usbmodem58FA1045341}" --label "${1:-}" --secs "${2:-30}" $extra )
}


# g2watchrun [--realtime]  -- watch the training run that is going on RIGHT NOW: the actual episodes it is simulating, streamed from the run itself (no simulation of
#   its own, not an approximation; it joins wherever the run is). Default = follow live at training speed (about 4-5x real time); --realtime = each episode at real
#   speed, then the newest. Needs a run started after 2026-10-09 (older runs have no stream) and your own terminal for the window. Costs the run nothing when closed.
g2watchrun() {
  ( cd "$G2_ROOT/rl_training/opencat-gym" && "$G2_ROOT/.venv/bin/python" watch_live.py "$@" )
}

# g2watchsim [TAG] [watch_trained args]  -- (the old g2watchrun) a FRESH simulation of a run's newest checkpoint in the PyBullet GUI (a fresh simulation with the run's environment, not a recording), by default WITH the training course: surface steps, snag obstacles, ledges.  --calm = the flat scoring world instead.
#   g2watchsim            the run that wrote the newest checkpoint (the one in progress)
#   g2watchsim v3_20m     a given run;   g2watchsim v3_20m --dr-push 0.35   adds random shoves
#   g2watchsim list       the runs with their newest checkpoint and how long ago it was written;   g2watchsim which   prints the tag it would watch
# Runs in a subshell (leaves you where you are); needs your own terminal for the GUI window; it slows the training a little while open. (`g2watch` / `g2watch-checkpoint` in ~/.bash_profile replay in the default world.)
g2watchsim() {
  local d="$G2_ROOT/rl_training/opencat-gym" ck="$G2_ROOT/rl_training/opencat-gym/trained/checkpoints"
  _g2run_tag() { ls -t "$ck"/*_steps.zip 2>/dev/null | head -1 | sed -E 's#.*/##; s/_[0-9]+_steps\.zip$//'; }
  case "${1:-}" in
    list)
      ls -t "$ck"/*_steps.zip 2>/dev/null | while read -r f; do
        b="${f##*/}"; t="${b%_*_steps.zip}"; n="${b#${t}_}"; n="${n%_steps.zip}"
        echo "$t $n $(( ( $(date +%s) - $(stat -f %m "$f") ) / 60 ))"
      done | awk '!seen[$1]++ {printf "%-34s newest checkpoint %9d steps, written %d min ago\n", $1, $2, $3}' | head -15
      return 0 ;;
    which) _g2run_tag; return 0 ;;
  esac
  local tag
  if [ -z "${1:-}" ] || [[ "${1:-}" == --* ]]; then tag="$(_g2run_tag)"; else tag="$1"; shift; fi
  [ -n "$tag" ] || { echo "no checkpoints in $ck: is a run in progress?"; return 1; }
  local newest; newest="$(ls -t "$ck/${tag}"_*_steps.zip 2>/dev/null | head -1)"
  [ -n "$newest" ] && echo "watching $tag from ${newest##*/} ($(( ( $(date +%s) - $(stat -f %m "$newest") ) / 60 )) min old)" || echo "no checkpoint for $tag yet: using its final policy if there is one"
  ( cd "$d" && ./watch_v3.sh "$tag" "$@" )
}

# --------------------------------------------------------- voice / conversation

g2chat()  { _g2py -m pi_pipeline.voice --mode text; }    # type to Claude, replies via `say` (needs ANTHROPIC_API_KEY)
g2voice() { _g2py -m pi_pipeline.voice --mode voice; }   # wake word + mic + Piper TTS (needs audio deps + models)
g2audio() { _g2py -m pi_pipeline.voice.check_audio "${1:-devices}"; }   # devices | wake | stt | tts

# ------------------------------------------------------------------- memory

# g2mem [facts | log N | search <q> | recall <q> | export [--scrub] | wipe --yes]  -- inspect and edit G2's memory on this machine (the Mac's copy; `g2pimem` reads the real one on the Pi).
g2mem() { _g2py -m pi_pipeline.memory "${@:-facts}"; }
# g2pimem  -- G2's real memory on the Pi, in the review page (facts, conversations, what he noticed, pictures; an X on every record goes to a Trash with Undo,
# "Empty trash" is the only permanent delete). It runs in the background: the first call starts it, later calls just open the browser. `g2pimem stop` ends it.
# g2pimem <facts | log N | search <q> | usage | sightings N | ...>  prints text instead (the same CLI against the Pi; g2mem reads the Mac's copy).
g2pimem() {
  : "${G2_PI:?set G2_PI to user@host of the Pi}"
  case "${1:-ui}" in
    ui) python3 "$G2_ROOT/tools/g2_review.py" --tab facts ;;
    stop) python3 "$G2_ROOT/tools/g2_review.py" --stop ;;
    *) ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.memory $*" ;;
  esac
}
# g2pics  -- the pictures G2 saved while exploring (survey stops, objects you named), as thumbnails in the same review page (X on each, Trash with Undo).
# g2pics status = text summary from the Pi; g2pics pull = copy them to ~/g2_pictures/explore; g2pics stop = end the page.
g2pics() {
  : "${G2_PI:?set G2_PI to user@host of the Pi}"
  case "${1:-ui}" in
    ui|open) python3 "$G2_ROOT/tools/g2_review.py" --tab pictures ;;
    stop) python3 "$G2_ROOT/tools/g2_review.py" --stop ;;
    status) ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.vision.exploration_pictures" ;;
    pull)
      ssh "$G2_PI" 'test -d ~/.local/share/g2/explore_pictures' || { echo "no exploration pictures on the Pi yet"; return 0; }
      mkdir -p "$HOME/g2_pictures/explore" && rsync -a "$G2_PI:.local/share/g2/explore_pictures/" "$HOME/g2_pictures/explore/" \
        && echo "pictures copied to $HOME/g2_pictures/explore ($(find "$HOME/g2_pictures/explore" -name '*.jpg' | wc -l | tr -d ' ') jpg)" ;;
    *) echo "usage: g2pics [open|status|pull|stop]"; return 2 ;;
  esac
}

# g2walls  -- the wall pictures (the labelled recognition shots and the near-wall pictures kept in roams) as thumbnails on the Walls tab of the review page.
g2walls() {
  : "${G2_PI:?set G2_PI to user@host of the Pi}"
  python3 "$G2_ROOT/tools/g2_review.py" --tab walls
}
# g2wallstats [DAYS]  -- statistics from the wall and detection logs on the Pi: looks per state, the nearest wall in inches, the turns, the times he stayed near a wall.
g2wallstats() { : "${G2_PI:?set G2_PI to user@host of the Pi}"; ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.vision.wall_stats ${1:+--days $1}"; }
# g2wallreplay [DIR]  -- what an exploring G2 would do with each saved wall picture (runs on the Pi; default ~/g2_wall_pics); nothing moves.
g2wallreplay() { : "${G2_PI:?set G2_PI to user@host of the Pi}"; ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.vision.wall_replay ${1:-~/g2_wall_pics}"; }
# g2wallpic LABEL INCHES [ANGLE]  -- take one labelled wall picture on the Pi (stop the voice service first: bash tools/g2_safe_stop.sh voice); distance in inches from the lens to the base of the wall.
g2wallpic() {
  : "${G2_PI:?set G2_PI to user@host of the Pi}"
  [ $# -ge 2 ] || { echo "usage: g2wallpic LABEL INCHES [ANGLE_DEG]   e.g. g2wallpic wall_straight 16"; return 2; }
  ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.vision.wall_pictures shot --label '$1' --inches '$2' ${3:+--angle $3}"
}
# g2imu [rest|stand] [SECONDS]  -- record the raw IMU stream on the Pi (stop the voice service first: bash tools/g2_safe_stop.sh voice) and print its frame rate, accel bias and noise.
g2imu() { : "${G2_PI:?set G2_PI to user@host of the Pi}"; ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.gait.imu_capture --pose ${1:-rest} --seconds ${2:-60}"; }
# g2picscurate [IN_DIR] [OUT_DIR]  -- curate the pulled exploration pictures (default ~/g2_pictures/explore -> training_data/exploration/<date_time>): scores lighting and
# sharpness, sets aside pictures with people, removes near-duplicates, writes keep/ rejects/ contact sheets, manifest.json and summary.txt. Run `g2pics pull` first.
g2picscurate() { "$_G2_PY" "$G2_ROOT/tools/curate_exploration.py" "$@"; }

# g2cal [build|status|show [ID]|harm-check ID POLICY...|approve ID|revert|auto]  -- the real-data calibration builder (docs/rl/real-data-pipeline.md, Phase 3): fits what G2's run logs
#   support, writes numbered snapshots, scores policies in the old and new world (idle Mac only), and applies the approval rules. The background loop (`g2bg status`) runs `auto` every 30 min.
g2cal() { "$G2_ROOT/.venv/bin/python" "$G2_ROOT/tools/g2_calibrate.py" "$@"; }
g2calauto() { bash "$G2_ROOT/tools/g2_cal_auto.sh" "$@"; }   # run the real-data calibration step now (pull the Pi logs, ingest, calibrate); `g2calauto status` lists snapshots
# g2bg [start [MIN]|stop|status|once]  -- the Mac-side background loop (every 30 min): re-curates the exploration pictures and runs the calibration step. It ends at a restart/logout: `g2bg start` again.
g2bg() { bash "$G2_ROOT/tools/g2_bg_jobs.sh" "$@"; }

# g2data [sync|ingest|status]  -- G2's automatic run logs on the Mac (docs/rl/real-data-pipeline.md). With no argument: sync, then ingest, then status.
#   sync = copy the Pi's run logs and detection logs to ~/g2_data (the Pi keeps its copy); ingest = measure every run, apply the quality gates, store it compressed (nothing deleted; a run that fails a gate is quarantined with its reasons);
#   status = how many runs are usable, by hardware epoch, floor and pack voltage, and why the others are not.
g2data() {
  : "${G2_PI:?set G2_PI to user@host of the Pi}"
  _sync() { mkdir -p "$HOME/g2_data/raw_auto" "$HOME/g2_data/detections" && rsync -a "$G2_PI:g2_runs/auto/" "$HOME/g2_data/raw_auto/" && { rsync -a "$G2_PI:g2_runs/detections/" "$HOME/g2_data/detections/" 2>/dev/null; true; } && echo "synced: $(ls "$HOME"/g2_data/raw_auto/*/*.csv 2>/dev/null | wc -l | tr -d ' ') run logs in ~/g2_data/raw_auto"; }
  case "${1:-all}" in
    sync) _sync ;;
    ingest|status) "$_G2_PY" "$G2_ROOT/tools/g2_ingest.py" ;;
    all) _sync && "$_G2_PY" "$G2_ROOT/tools/g2_ingest.py" ;;
    *) echo "usage: g2data [sync|ingest|status]"; return 2 ;;
  esac
}

# g2reset [status|logs]  -- restart G2's voice loop on the Pi (prints "restarting voice loop..." then "voice loop restarted"; G2 also says "I am online." out loud when he is back) (use it when G2 does not answer voice commands; works even when he cannot hear you). If an exploration session is running it is ended first.
# It waits until the service says it is listening (about 30 s). g2reset status = what is running, since when, and the last thing G2 heard; g2reset logs = the last lines of the voice service log.
g2reset() {
  : "${G2_PI:?set G2_PI to user@host of the Pi}"
  case "${1:-restart}" in
    status) ssh "$G2_PI" 'systemctl is-active g2-voice g2-explore g2-baseline | paste -sd" " ; systemctl show g2-voice -p ActiveEnterTimestamp --value; journalctl -u g2-voice --no-pager | grep -i "heard" | tail -2 | cut -c1-140' ;;
    logs) ssh "$G2_PI" 'journalctl -u g2-voice -n 40 --no-pager | grep -v VoskAPI | cut -c1-190' ;;
    restart)
      echo "restarting voice loop..."
      ssh "$G2_PI" 'if systemctl is-active --quiet g2-baseline; then echo "a baseline run is active: not restarting (g2_baseline.sh stop first)"; exit 3; fi
        systemctl is-active --quiet g2-explore && sudo systemctl stop g2-explore
        t=$(date +%H:%M:%S); sudo systemctl restart g2-voice; n=0
        until journalctl -u g2-voice --since "$t" --no-pager | grep -q "voice loop ready"; do n=$((n+1)); [ $n -ge 45 ] && { echo "not ready after 90 s: g2reset logs"; exit 1; }; sleep 2; done
        echo "voice loop restarted: G2 is listening"' ;;
    *) echo "usage: g2reset [status|logs]"; return 2 ;;
  esac
}

# g2attach [status|list|none|head|arm|save ATTACHMENT POLICY [--trim T] [--payload P]]  -- which attachment G2 wears on the neck, and the gait saved for each (docs/planned/attachments.md).
# g2attach head = set it on the Pi, print the hardware checklist, restart the voice loop (g2reset) so the matching gait and firmware check apply. save = make POLICY that
# attachment's current gait in pi_pipeline/attachments/gait_profiles.json here on the Mac (then commit and deploy). Swap the hardware with G2 powered off.
g2attach() {
  : "${G2_PI:?set G2_PI to user@host of the Pi}"
  case "${1:-status}" in
    status|list) ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.attachments $1" ;;
    none|head|arm) ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.attachments use $1" && g2reset ;;
    save) shift; _g2py -m pi_pipeline.attachments save "$@" ;;
    *) echo "usage: g2attach [status|list|none|head|arm|save ATTACHMENT POLICY [--trim T] [--payload P]]"; return 2 ;;
  esac
}

# g2floor [LABEL]  -- show or set the floor G2 is on (hardwood, tile, carpet, ...); every automatic run log records it, and fits are per floor. g2floor status = the automatic run logs.
g2floor() {
  : "${G2_PI:?set G2_PI to user@host of the Pi}"
  case "${1:-show}" in
    status) ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.telemetry status" ;;
    epochs) ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.telemetry epochs" ;;
    show) ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.telemetry surface" ;;
    *) ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.telemetry surface '$*'" ;;
  esac
}

# --------------------------------------------------------- config introspection

g2feat()   { _g2py -m pi_pipeline "${@:---profiles}"; }         # resolve G2_FEATURES; `g2feat --profiles` lists bring-up stages
g2traits() { _g2py -m pi_pipeline.personality "$@"; }           # resolve G2_TRAITS -> prompt / behaviour / bonds
g2diag()   { _g2py -m pi_pipeline.diag "${@:-list}"; }          # list | summarize [sid] | tail [sid] | replay <sid>

# ------------------------------------------------------- robot serial link (HW)

g2serial() { _g2py -m pi_pipeline.link.check_serial "${@:-ports}"; }   # ports | ping | send <cmd> | skills | rest
g2power()  { _g2py -m pi_pipeline.power "${@:-status}"; }             # status | headless | interactive | governor <n>

# ----------------------------------------------------------- operate G2 (Mac -> Pi)
# These need G2_PI (user@host of the Pi) in your environment. They are the everyday controls; the workflows are in docs/guides/cheatsheet.md.

# g2ssh  -- open a shell on the Pi.
g2ssh() { : "${G2_PI:?set G2_PI to user@host of the Pi}"; ssh "$G2_PI" "$@"; }
# g2deploy [--once|--cancel|--max-hours N|--replace]  -- push pi_pipeline/ and the deployed policy to the Pi and restart the voice service. With no flag it WAITS for the Pi (up to 24 h) and deploys once;
#   --once deploys now if the Pi answers. It refuses while an exploration or a walk is running. Never deploy while testing.
g2deploy() { bash "$G2_ROOT/tools/g2_deploy_when_online.sh" "$@"; }
# g2explore [start [ROAM_S]|stationary|arm|disarm|halt|release|stop|status|logs|heard]  -- run and supervise an exploration session on the Pi (the voice service is stopped for it and always comes back). `halt` freezes it, `release` clears the freeze.
g2explore() { bash "$G2_ROOT/tools/g2_explore.sh" "$@"; }
# g2stop [voice|explore]  -- the SAFE stop: rest G2 first, then stop what controls him. Use this, never a plain service stop mid-stride.
g2stop() { bash "$G2_ROOT/tools/g2_safe_stop.sh" "$@"; }
# g2rest  -- send rest (`d`) to G2 right now. For when he is moving and nothing is in control; if the voice service holds the port, run g2stop voice first.
g2rest() { : "${G2_PI:?set G2_PI to user@host of the Pi}"; ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.link.check_serial send d"; }
# g2baseline [start [RUNS] [LABEL]|stop|status|logs|fetch]  -- logged walks on the Pi (the voice service is stopped for them and restarted after). `fetch` copies the logs to the Mac.
g2baseline() { bash "$G2_ROOT/tools/g2_baseline.sh" "$@"; }
# g2walk [RUNS] [LABEL]  -- RUNS (default 1) logged 12.5 s walks at 0.10 m/s with the deployed policy, on the Pi. The voice service is stopped for them and restarted after; G2 speaks before each run so you can set him at the start of the lane. Logs: ~/g2_runs/<LABEL>_*.csv on the Pi; `g2baseline fetch` copies them here.
g2walk() { bash "$G2_ROOT/tools/g2_baseline.sh" start "${1:-1}" "${2:-walk}"; }
# g2turns [start [RUNS]|stop|status|logs|fetch]  -- logged firmware turn runs (kwkL and kwkR alternating) on the Pi, to measure the real turn rate.
g2turns() { bash "$G2_ROOT/tools/g2_turns.sh" "$@"; }
# g2walklog LOG.csv [LOG.csv ...]  -- summarize walk logs: roll, pitch and yaw, the first fall, battery voltage.
g2walklog() { _g2py tools/walk_log_summary.py "$@"; }
# g2policy TAG NAME [--dry-run]  -- promote a trained checkpoint to G2's default: export it with its sidecar as Release_Candidate<NAME>, set DEFAULT_POLICY, run the tests, commit, then arm the deploy. The user's call only.
g2policy() { bash "$G2_ROOT/tools/g2_promote_policy.sh" "$@"; }
# g2api [HOURS]  -- Claude API calls, tokens and approximate cost on the Pi over the last HOURS (default 24), by source. Use it to watch cost.
g2api() { : "${G2_PI:?set G2_PI to user@host of the Pi}"; ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.voice.api_log --hours ${1:-24}"; }
# g2crash [N]  -- why did the voice service or an exploration session crash? The last N (default 5) unclean ends, with the stage and the resources at the time.
g2crash() { : "${G2_PI:?set G2_PI to user@host of the Pi}"; ssh "$G2_PI" "cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.diag.crashwatch ${1:-5}"; }

# ---------------------------------------------------------- bring-up and checks
# g2doctor [--serial]  -- the bring-up readiness checklist: .env, API key, models, dependencies, serial port, audio, disk. --serial also pings the board.
g2doctor() { _g2py -m pi_pipeline.doctor "$@"; }
# g2bringup [--list|--restart|--from ID]  -- the guided, resumable hardware bring-up sequence.
g2bringup() { _g2py -m pi_pipeline.bringup "$@"; }
# g2app [--serial|--bench|--trace FILE]  -- the whole robot as one program (voice loop + behavior runtime). Mock by default; --serial talks to the BiBoard; --bench blocks autonomous movement.
g2app() { _g2py -m pi_pipeline.app "$@"; }
# g2check  -- the docs checks: broken links, facts in the wrong page, orphan pages, stale generated pages (the pre-commit hook runs it).
g2check() { _g2py tools/check_docs.py "$@"; }
# g2bundle [--out DIR] [--base /docs]  -- build the docs bundle (every page as site-ready Markdown, a navigation manifest and a search index) into build/docs-bundle for the website. CI builds and publishes it on every push; this is the local preview. Format: docs/guides/docs-bundle.md.
g2bundle() { _g2py tools/build_docs_bundle.py "$@"; }
# g2docsgen  -- regenerate the generated docs: the backlog, the shell-helpers page, the environment-variable reference and the results index. Run it after changing an item heading, an alias comment or the result files.
g2docsgen() { ( cd "$G2_ROOT" && python3 tools/gen_backlog.py && python3 tools/gen_helpers_doc.py && python3 tools/gen_env_reference.py && python3 tools/gen_results_index.py ); }

# ------------------------------------------------------- simulation and training
# These run from rl_training/opencat-gym with the RL venv; they work from any directory.

# g2train TAG [--steps N] [--force]  -- start a training run with the full pre-run checklist (start_run.sh): a new tag, no run already going, no leftover viewers. Never start a 20M unasked.
g2train() { "$G2_ROOT/rl_training/opencat-gym/start_run.sh" "$@"; }
# g2eta plan --steps 3e6 --tail stage | now --target 20e6 --tail final20m | check  -- timing estimates read from the trainer's logs. Quote them (with a completion clock) whenever you launch anything.
g2eta() { _g2py tools/eta.py "$@"; }
# g2preflight  -- must print ALL PASS before a 20M run is offered: the RL tests, audits, a smoke run, benchmark scoring and replay checks.
g2preflight() { ( cd "$G2_ROOT/rl_training/opencat-gym" && "$G2_ROOT/.venv/bin/python" preflight.py "$@" ); }
# g2rltest  -- run the RL test files (the pipeline's own suite is g2test).
g2rltest() { ( cd "$G2_ROOT/rl_training/opencat-gym" && "$G2_ROOT/.venv/bin/python" -m pytest -q test_*.py ); }
# g2watch [trained/TAG_ppo]  -- replay the newest finished policy (or the one named) in the PyBullet GUI. Needs your own terminal for the window.
g2watch() {
  ( cd "$G2_ROOT/rl_training/opencat-gym" || exit 1
    ckpt="${1:-$(ls -t trained/*_ppo.zip | head -1 | sed 's/\.zip$//')}"
    echo "watching $ckpt"; "$G2_ROOT/.venv/bin/python" watch_trained.py "$ckpt" )
}
# g2tb [stop]  -- open TensorBoard for the training runs at localhost:6006 (starts it if needed); `g2tb stop` ends it.
g2tb() {
  if [ "$1" = stop ]; then pkill -f "tensorboard.*tensorboard_logs" && echo "tensorboard stopped" || echo "not running"; return; fi
  pgrep -f "tensorboard.*tensorboard_logs" >/dev/null || ( cd "$G2_ROOT/rl_training/opencat-gym" && nohup "$G2_ROOT/.venv/bin/python" -m tensorboard.main --logdir trained/tensorboard_logs/ --port 6006 >/dev/null 2>&1 & )
  sleep 2; open http://localhost:6006/
}

# --------------------------------------------------------------------- docs

# g2docs  -- print the list of key docs (the full index is docs/README.md)
g2docs() {
  cat <<'EOF'
Key docs (in docs/):
  guides/cheatsheet.md                 the commands, grouped by what you are doing
  guides/operating-g2.md               safety, stopping G2, power on and off
  guides/train-vision-model.md              full camera-model walkthrough
  vision/capture-checklist.md   the capture routine + standard pose set
  vision/person-recognition.md       recognition design + "G2, meet X" enrollment
  vision/detection-layer.md          one-model-slot / multi-model architecture
  vision/detector-bench.md    measured module behaviour + AE-lift + orientation
  guides/feature-flags.md                     staged bring-up (g2feat --profiles)
EOF
}

# g2help  -- print the bare list of helpers with their one-line comments.
g2help() { grep -E '^g2[a-z-]*\(\)' "$G2_ROOT/tools/g2_aliases.sh" | grep -v '^g2help' | sed 's/() *{.*# */\t/; s/() *{.*//'; }
