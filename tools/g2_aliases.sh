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
  stop      -> g2cam-stop     then:  g2curate $name $sess

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
g2cam-stop() { pkill -f "camera_preview.py|face_preview.py" && echo "preview stopped" || echo "nothing running"; }
g2cam-info() { _g2py tools/camera_preview.py --info; }   # serial port + which model is on the module

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
# g2combine <name>  -- gather every session's curated set into <name>/upload/ (per-session subdirs)
g2combine() {
  local name="${1:?usage: g2combine <name>}"
  local u="$G2_CAP_ROOT/$name/upload" ui="$G2_CAP_ROOT/$name/upload_images"
  ( mkdir -p "$u"; rm -rf "$ui"; mkdir -p "$ui"; local k=0 m=0
    for s in "$G2_CAP_ROOT/$name"/session_*/curated; do
      [ -d "$s" ] || continue
      local n; n="$(basename "$(dirname "$s")")"
      mkdir -p "$u/$n"; cp "$s"/pos_*.jpg "$s"/pos_*.txt "$s"/neg_*.jpg "$u/$n/" 2>/dev/null
      for f in "$s"/pos_*.jpg; do [ -e "$f" ] || continue; k=$((k+1)); cp "$f" "$ui/$(printf '%s_%03d.jpg' "$name" $k)"; done
      for f in "$s"/neg_*.jpg; do [ -e "$f" ] || continue; m=$((m+1)); cp "$f" "$ui/$(printf '%s_neg_%03d.jpg' "$name" $m)"; done
    done
  )
  echo "upload (Roboflow/Colab, per-session + .txt) -> $u"
  echo "upload_images ($(ls "$ui"/*.jpg 2>/dev/null|wc -l|tr -d ' ') JPEGs only, for the SenseCraft browser) -> $ui"
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

# g2libcombine [classes]  -- build $G2_LIB_ROOT/upload/  (arg overrides $G2_VISION_CLASSES)
g2libcombine() {
  local cl="${1:-$G2_VISION_CLASSES}"
  [ -n "$cl" ] || { echo "set G2_VISION_CLASSES=\"...\" (id order) or pass it as an arg"; return 1; }
  _g2py tools/combine_for_upload.py "$G2_LIB_ROOT" --classes "$cl"
}
# g2libsubset <N> <class>  -- capped images-only upload set for the threshold test
#   (negatives auto-capped at ~N/4; jpg only so SenseCraft auto-label isn't cluttered)
g2libsubset() {
  local n="${1:?usage: g2libsubset <N> <class>}" cls="${2:?need a class name}"
  _g2py tools/combine_for_upload.py "$G2_LIB_ROOT" --classes "$cls" \
    --limit "$n" --neg-limit "$(( n / 4 ))" --images-only --out "$G2_LIB_ROOT/upload_$n"
}
g2libstatus() { cat "$G2_LIB_ROOT/_MANIFEST.md" 2>/dev/null || echo "no library yet at $G2_LIB_ROOT"; }

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

# g2watchab [vision|blind] [latest|final]  -- replay the Phase D A/B run in the
#   PyBullet GUI (latest checkpoint while training, or the final policy).
g2watchab() { ( cd "$G2_ROOT/rl_training/opencat-gym" && bash watch_ab.sh "$@" ); }

# g2climbwatch [episodes] [ledge-lo] [ledge-hi] [pin-tag]  -- replay the NEWEST
#   climb_* checkpoint in the PyBullet GUI. Auto-follows the current Phase F
#   climb run (picks the most-recently-written trained/climb_*.zip, incl mid-run
#   _steps checkpoints). Defaults: 8 eps, ledge 2.5-5 cm.
g2climbwatch() { ( "$G2_ROOT/rl_training/opencat-gym/climbwatch" "$@" ); }

# --------------------------------------------------------- voice / conversation

g2chat()  { _g2py -m pi_pipeline.voice --mode text; }    # type to Claude, replies via `say` (needs ANTHROPIC_API_KEY)
g2voice() { _g2py -m pi_pipeline.voice --mode voice; }   # wake word + mic + Piper TTS (needs audio deps + models)
g2audio() { _g2py -m pi_pipeline.voice.check_audio "${1:-devices}"; }   # devices | wake | stt | tts

# ------------------------------------------------------------------- memory

# g2mem [facts | log N | search <q> | recall <q> | export [--scrub] | wipe --yes]
g2mem() { _g2py -m pi_pipeline.memory "${@:-facts}"; }

# --------------------------------------------------------- config introspection

g2feat()   { _g2py -m pi_pipeline "${@:---profiles}"; }         # resolve G2_FEATURES; `g2feat --profiles` lists bring-up stages
g2traits() { _g2py -m pi_pipeline.personality "$@"; }           # resolve G2_TRAITS -> prompt / behaviour / bonds
g2diag()   { _g2py -m pi_pipeline.diag "${@:-list}"; }          # list | summarize [sid] | tail [sid] | replay <sid>

# ------------------------------------------------------- robot serial link (HW)

g2serial() { _g2py -m pi_pipeline.link.check_serial "${@:-ports}"; }   # ports | ping | send <cmd> | skills | rest
g2gait()   { _g2py pi_pipeline/gait/run_gait.py "$@"; }               # on-robot gait loop (--dry-run, --openloop, ...)
g2power()  { _g2py -m pi_pipeline.power "${@:-status}"; }             # status | headless | interactive | governor <n>

# --------------------------------------------------------------------- docs

g2docs() {
  cat <<'EOF'
Key docs (in docs/):
  guides/SOLO.md                       start here if carrying on without Claude
  guides/train-vision-model.md              full camera-model walkthrough
  vision/capture-checklist.md   the capture routine + standard pose set
  vision/person-recognition.md       recognition design + "G2, meet X" enrollment
  vision/detection-layer.md          one-model-slot / multi-model architecture
  vision/detector-bench.md    measured module behaviour + AE-lift + orientation
  guides/feature-flags.md                     staged bring-up (g2feat --profiles)
  guides/cheatsheet.md              the command reference (this + RL commands)
EOF
}

g2help() { grep -E '^g2[a-z-]*\(\)' "$G2_ROOT/tools/g2_aliases.sh" | sed 's/() *{.*# */\t/; s/() *{.*//'; }
