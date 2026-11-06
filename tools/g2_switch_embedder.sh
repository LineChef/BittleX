#!/usr/bin/env bash
# Move G2's object gallery to another embedder (user, 2026-11-06). Steps, each separate and each only when you run it:
#   g2_switch_embedder.sh push-model [FILE]   copy the model to the Pi's models folder and check its SHA-256 on both ends (default dinov2_small_int8.onnx from ~/g2_data/models_derived, the 8-bit file: same accuracy, a quarter of the size)
#   g2_switch_embedder.sh bench [KEY]         time it ON the Pi (needs the voice service stopped: a ViT does not fit beside it): load time, ms a picture, peak memory
#   g2_switch_embedder.sh switch [GALLERY]    back up the Pi's gallery.json, then put the rebuilt one (default ~/g2_data/gallery_rebuilt/gallery.json, made by tools/rebuild_gallery.py) in its place
#   g2_switch_embedder.sh revert              put the backed-up histogram gallery back
# The labelled pictures are never touched. The gallery file records its embedder, so once switched every part of the Pi (the interest watch, the promoted-picture loader) uses it by itself.
set -euo pipefail
: "${G2_PI:?set G2_PI to user@host of the Pi}"
M="$HOME/g2_data/models"
D="$HOME/g2_data/models_derived"
GAL="~/.local/share/g2/object_gallery"
case "${1:-}" in
  push-model)
    f="${2:-$D/dinov2_small_int8.onnx}"; n="$(basename "$f")"
    ssh "$G2_PI" 'mkdir -p ~/.local/share/g2/models'
    rsync -a --partial "$f" "$G2_PI:.local/share/g2/models/$n"
    a="$(shasum -a 256 "$f" | cut -d' ' -f1)"; b="$(ssh "$G2_PI" "sha256sum ~/.local/share/g2/models/$n" | cut -d' ' -f1)"
    [ "$a" = "$b" ] && echo "ok: $n on the Pi matches ($a)" || { echo "MISMATCH: $a vs $b"; exit 1; } ;;
  bench)
    if ssh "$G2_PI" 'systemctl is-active --quiet g2-voice'; then echo "the voice service is running: stop it first (g2stop voice), the model needs the memory"; exit 1; fi
    ssh "$G2_PI" "cd ~/bittleX && PYTHONPATH=. pi_pipeline/.venv/bin/python -m pi_pipeline.vision.embed_bench '${2:-dinov2_small_int8.onnx#cls}'" ;;
  switch)
    g="${2:-$HOME/g2_data/gallery_rebuilt/gallery.json}"; [ -f "$g" ] || { echo "no $g: run tools/rebuild_gallery.py first"; exit 1; }
    ssh "$G2_PI" "test ! -e /tmp/g2_exploring && cp -p $GAL/gallery.json $GAL/gallery.json.histogram-backup"
    rsync -a "$g" "$G2_PI:.local/share/g2/object_gallery/gallery.json" && echo "switched; the old gallery is gallery.json.histogram-backup" ;;
  revert)
    ssh "$G2_PI" "cp -p $GAL/gallery.json.histogram-backup $GAL/gallery.json" && echo "back to the histogram gallery" ;;
  *) sed -n 2,9p "$0"; exit 2 ;;
esac
