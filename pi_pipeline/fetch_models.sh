#!/usr/bin/env bash
# pi_pipeline/fetch_models.sh
# Download the voice models into ./models/ (repo root). Idempotent — skips files
# that already exist. Run from anywhere, on the Mac or the Pi:
#     bash pi_pipeline/fetch_models.sh
#
# Decided set for the Pi Zero 2 W (rationale in pi_pipeline/voice/README.md):
#   STT   vosk-model-small-en-us-0.15   ~40 MB zip / ~300 MB RAM at runtime — the
#         only Vosk English model that fits (the others are 1-2 GB)
#   TTS   en_US-ryan-low     primary   16 kHz 'low' tier — lightest available
#         en_US-ryan-medium  upgrade   22 kHz, same voice, cleaner — switch to it
#                                      if `benchmark_pi.py --all-voices` shows its
#                                      synth < ~0.7x realtime with RAM to spare
#   (Piper 'x_low' voices are gone from the current piper-voices repo; 'low' is
#   the floor. If 'low' still can't hit real-time, the fallbacks are a longer
#   "thinking" cue over the synth gap, shorter replies, or pre-synth'd stock
#   phrases — not a lighter model.)

set -euo pipefail
cd "$(dirname "$0")/.."                       # repo root
mkdir -p models/piper

HF=https://huggingface.co/rhasspy/piper-voices/resolve/main/en
ok()  { printf '\033[1;32m  ok   %s\033[0m\n' "$*"; }
hdr() { printf '\033[1;36m==> %s\033[0m\n' "$*"; }

# piper <lang> <speaker> <quality>   e.g.  piper en_US ryan low
piper() {
  local lang=$1 spk=$2 q=$3 name="$1-$2-$3"
  if [ -s "models/piper/$name.onnx" ] && [ -s "models/piper/$name.onnx.json" ]; then
    ok "$name (already present)"; return
  fi
  hdr "Piper $name"
  curl -fL# -o "models/piper/$name.onnx"      "$HF/$lang/$spk/$q/$name.onnx"
  curl -fL# -o "models/piper/$name.onnx.json" "$HF/$lang/$spk/$q/$name.onnx.json"
  ok "$name"
}

# ---- Vosk small English --------------------------------------------------
if [ -f models/vosk/am/final.mdl ]; then
  ok "vosk-model-small-en-us-0.15 (already present)"
else
  hdr "Vosk small English"
  tmp=$(mktemp -d)
  curl -fL# -o "$tmp/v.zip" https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
  unzip -q "$tmp/v.zip" -d "$tmp"
  rm -rf models/vosk && mv "$tmp/vosk-model-small-en-us-0.15" models/vosk && rm -rf "$tmp"
  ok "models/vosk"
fi

# ---- Piper voices ------------------------------------------------------
piper en_US ryan low
piper en_US ryan medium

echo
echo "models/  ->  $(du -sh models 2>/dev/null | cut -f1)"
echo "then set the voice in .env:   PIPER_MODEL_PATH=models/piper/en_US-ryan-low.onnx"
