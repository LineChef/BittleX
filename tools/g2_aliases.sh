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
# `g2help` prints this list.  `docs/reference/cheatsheet.md` is the reference.
# =============================================================================

# G2_ROOT: honour an existing value, else the location of this file.
if [ -z "$G2_ROOT" ] || [ ! -d "$G2_ROOT/pi_pipeline" ]; then
  _g2_self="${BASH_SOURCE[0]:-${(%):-%x}}"                 # bash or zsh
  export G2_ROOT="$(cd "$(dirname "$_g2_self")/.." && pwd)"
  unset _g2_self
fi
export G2_CAP_ROOT="${G2_CAP_ROOT:-$HOME/Desktop/g2_face_capture}"
_G2_PY="$G2_ROOT/pi_pipeline/.venv/bin/python"            # companion-pipeline venv

# run a python module/script from the repo, pipeline venv, WITHOUT moving the caller
_g2py() { ( cd "$G2_ROOT" && "$_G2_PY" "$@" ); }

# ---------------------------------------------------------------- environment

g2()     { cd "$G2_ROOT" && source pi_pipeline/.venv/bin/activate; }              # cd repo + pipeline venv
g2rl()   { cd "$G2_ROOT/rl_training/opencat-gym" && source "$G2_ROOT/.venv/bin/activate"; }  # cd RL dir + RL venv
g2back() { cd - >/dev/null && pwd; }                                             # return to the dir before g2/g2rl
g2test() { ( cd "$G2_ROOT" && "$_G2_PY" -m pytest pi_pipeline/tests/ -q ); }     # run the pipeline test suite

# ------------------------------------------------- camera capture + model train
# Walkthrough: docs/train-a-visual-model.md   Routine + poses: docs/research/capture-session-checklist.md

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
  echo "capturing -> $out    (stop: g2cam-stop)"
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
  local name="${1:?usage: g2combine <name>}" u="$G2_CAP_ROOT/$1/upload"
  ( mkdir -p "$u"
    for s in "$G2_CAP_ROOT/$name"/session_*/curated; do
      [ -d "$s" ] || continue
      local n; n="$(basename "$(dirname "$s")")"
      mkdir -p "$u/$n"; cp "$s"/pos_*.jpg "$s"/pos_*.txt "$s"/neg_*.jpg "$u/$n/" 2>/dev/null
    done )
  echo "combined -> $u"; ls "$u"
}

# ------------------------------------------------------------- vision runtime

# g2vision [labels]  -- run the detection pipeline over serial, print live detections
#                       e.g. g2vision person     or    g2vision person,alex
g2vision() {
  local port; port="$(ls /dev/cu.usbmodem* 2>/dev/null | head -1)"
  ( cd "$G2_ROOT" && VISION_LABELS="${1:-person}" "$_G2_PY" -m pi_pipeline.vision serial "${port:-/dev/cu.usbmodem58FA1045341}" )
}
g2vision-demo() { _g2py -m pi_pipeline.vision demo; }    # mock feed, no hardware

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
  SOLO.md                              start here if carrying on without Claude
  train-a-visual-model.md              full camera-model walkthrough
  research/capture-session-checklist.md   the capture routine + standard pose set
  research/person-recognition.md       recognition design + "G2, meet X" enrollment
  research/detection-layer.md          one-model-slot / multi-model architecture
  research/vision-detector-bench.md    measured module behaviour + AE-lift + orientation
  feature-flags.md                     staged bring-up (g2feat --profiles)
  hardware-readiness.md                day-1 checklists
  reference/cheatsheet.md              the command reference (this + RL commands)
EOF
}

g2help() { grep -E '^g2[a-z-]*\(\)' "$G2_ROOT/tools/g2_aliases.sh" | sed 's/() *{.*# */\t/; s/() *{.*//'; }
