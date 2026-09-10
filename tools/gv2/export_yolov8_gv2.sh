#!/usr/bin/env bash
# Ultralytics YOLOv8 .pt  ->  firmware-20250102-compatible *_vela.tflite
# for the Grove Vision AI V2. This is the export half of the 2026-09-09 recipe
# (train on Colab, export here) -- see docs/research/grove-vision-v2-custom-model.md.
#
#   tools/gv2/export_yolov8_gv2.sh  best.pt  <calib_images_dir>  [nc]  [name1,name2,...]
#
#   best.pt            weights downloaded from the Colab training run
#   calib_images_dir   flat folder of .jpg used for INT8 calibration
#                      -- USE 300+ VARIED images (100 gave "up close only")
#   nc / names         optional; only used to write the throwaway data.yaml
#                      (calibration doesn't need correct labels, just images)
#
# Output: ./gv2_out/<stem>_vela.tflite   (+ the intermediate full_integer_quant)
#
# MUST run on arm64 Python 3.9 (/usr/bin/python3 on this Mac). x86 Python pulls
# an AVX TensorFlow build that aborts. The script refuses to run on x86.
set -euo pipefail

PT="${1:?usage: export_yolov8_gv2.sh best.pt calib_dir [nc] [names]}"
CALIB="${2:?need a calibration images dir}"
NC="${3:-3}"
NAMES="${4:-c0,c1,c2}"
IMGSZ=192

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VELA_CFG="$HERE/vela_config_we2.ini"
WORK="${GV2_WORK:-$PWD/gv2_work}"
OUT="$PWD/gv2_out"
VENV="$WORK/.venv"
PYBASE="${GV2_PYTHON:-/usr/bin/python3}"

command -v "$PYBASE" >/dev/null || { echo "no $PYBASE"; exit 1; }
ARCH="$("$PYBASE" -c 'import platform;print(platform.machine())')"
[ "$ARCH" = "arm64" ] || { echo "FATAL: $PYBASE is $ARCH, need arm64 (x86 TF aborts on AVX)"; exit 1; }

mkdir -p "$WORK" "$OUT"

if [ ! -x "$VENV/bin/python" ]; then
  echo "== creating arm64 venv at $VENV =="
  "$PYBASE" -m venv "$VENV"
  "$VENV/bin/pip" -q install --upgrade pip
  # exact pins from the working 2026-09-09 env
  "$VENV/bin/pip" -q install \
    "ultralytics==8.2.8" "tensorflow==2.16.2" "tf-keras==2.16.0" \
    "onnx==1.16.1" "onnx2tf==1.17.5" "onnxsim==0.4.36" \
    "onnx_graphsurgeon==0.6.1" "sng4onnx==2.0.1" "numpy==1.26.4" \
    "ethos-u-vela==5.0.0"
fi
PY="$VENV/bin/python"

echo "== patching onnx2tf INT8 calib normalisation (float64 -> float32) =="
"$PY" - <<'EOF'
import onnx2tf, os
p = os.path.join(os.path.dirname(onnx2tf.__file__), "onnx2tf.py")
s = open(p).read()
old = "normalized_calib_data = (calib_data[idx] - mean) / std\n"
new = "normalized_calib_data = ((calib_data[idx] - mean) / std).astype(np.float32)\n"
if old in s:
    open(p, "w").write(s.replace(old, new)); print("  patched")
elif new in s:
    print("  already patched")
else:
    raise SystemExit("  PATCH TARGET NOT FOUND -- onnx2tf changed, re-derive the fix")
EOF

# throwaway data.yaml: val = the calibration images
CALIB_ABS="$(cd "$CALIB" && pwd)"
cat > "$WORK/calib.yaml" <<EOF
path: $CALIB_ABS
train: .
val: .
nc: $NC
names: [$(echo "$NAMES" | sed 's/,/, /g')]
EOF

export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 TF_USE_LEGACY_KERAS=1
PT_ABS="$(cd "$(dirname "$PT")" && pwd)/$(basename "$PT")"
STEM="$(basename "${PT%.*}")"

echo "== yolo export (format=tflite imgsz=$IMGSZ int8) =="
cd "$WORK"
"$VENV/bin/yolo" export model="$PT_ABS" format=tflite imgsz="$IMGSZ" int8 data="$WORK/calib.yaml"

QUANT="$(dirname "$PT_ABS")/${STEM}_saved_model/${STEM}_full_integer_quant.tflite"
[ -f "$QUANT" ] || QUANT="$(find "$(dirname "$PT_ABS")" -name '*_full_integer_quant.tflite' | head -1)"
[ -f "$QUANT" ] || { echo "FATAL: no *_full_integer_quant.tflite produced"; exit 1; }
cp "$QUANT" "$OUT/${STEM}_full_integer_quant.tflite"

echo "== vela (ethos-u55-64, Himax WE2 config) =="
"$VENV/bin/vela" --accelerator-config ethos-u55-64 --config "$VELA_CFG" \
  --system-config My_Sys_Cfg --memory-mode My_Mem_Mode_Parent \
  --output-dir "$OUT" "$OUT/${STEM}_full_integer_quant.tflite"

VELA="$OUT/${STEM}_full_integer_quant_vela.tflite"
echo
echo "DONE -> $VELA"
"$PY" - "$VELA" <<'EOF'
import sys, os
p = sys.argv[1]
print(f"  {os.path.getsize(p)/1e6:.2f} MB  (device flash slot is ~2 MB)")
b = open(p, "rb").read()
print("  contains 'ethos-u' op:", b.find(b"ethos-u") != -1)
EOF
echo "  flash via SenseCraft Upload Model, or python-sscma serial (see the doc)"
