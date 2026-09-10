# Custom multi-class detection model for the Grove Vision AI V2 — what works

Written 2026-09-09 after a long session of dead ends. If you're picking this up,
**read the "Core constraint" section first** — it explains why most tutorials
fail on our device.

Companion: `capture-progress.md` (data/capture tracker),
`guides/train-vision-model.md` (the older SenseCraft-web single-class flow),
`detection-layer.md` (one-model-slot architecture).

Repo tooling for this flow: **`tools/gv2/`** —
`split_yolo_dataset.py` (library → train/val zip), `export_yolov8_gv2.sh`
(the arm64 local export + vela, exact pins inside), `vela_config_we2.ini`
(the Himax WE2 vela profile). Plus `tools/autobox_coco.py`,
`tools/combine_for_upload.py`, `tools/vision_diag.py`.

---

## Core constraint: the device firmware is frozen at Jan 2025

The Grove Vision AI V2's on-device firmware (`SSCMA-Micro`, latest release tag
`20250102`) does the pre/post-processing around the `.tflite` you flash — the
anchor decode, the objectness gate, NMS. **You flash only the model; the
firmware's decoder has to recognise its output head.**

Every training toolchain has moved forward since Jan 2025 and their exports
drifted out of sync with that frozen decoder. Symptoms of a mismatch:

| symptom | meaning |
|---|---|
| `boxes:[]` every frame, `inference` time normal | firmware ran the conv layers but its decoder produced nothing from the head → head format it doesn't recognise |
| **box flood** — 10-30 boxes/frame, high conf, on an anchor grid, `postprocess: 0ms`, confidence/IoU sliders do nothing | firmware is dumping raw anchor outputs — objectness gate + NMS never applied → head format it doesn't recognise |
| `Invoke failed` / Device Logger blank | quantisation broken OR head type unsupported (see SSCMA issues #276, #294, #319) |

A working model is **quiet on an empty scene** and puts **one box per real
object**.

**What firmware `20250102` DOES decode** (from its changelog + stock models):
- Swift-YOLO as exported by **SSCMA / ModelAssistant `2.0.0` branch** (all the
  stock SenseCraft models — Person Detection, Hand Gesture — are this)
- **Ultralytics YOLOv8** exported with **`ultralytics==8.2.8`** (per Seeed's
  official wiki `ma_deploy_yolov8`, last updated Apr 2024) — **confirmed working
  2026-09-09**, exported locally on Apple Silicon (recipe below)
- YOLO11 (added in the `20250102` release)
- **NOT** YOLO26. **NOT** RTMDet. **NOT** the SSCMA `main` / `fix/colab-py312-main`
  re-implemented Swift-YOLO head.

---

## Paths tried this session and their outcomes

| path | toolchain | on-device result |
|---|---|---|
| Ultralytics YOLOv8, `ultralytics==8.4.146`, `format=saved_model` (NHWC) | new ultralytics | **`boxes:[]`** — 8.4.x LiteRT/ai-edge-torch export ≠ 8.2.8 graph |
| YOLO26 (`yolo26_GV2.ipynb`) | ultralytics | trained fine, **0 detections** — firmware has no YOLO26 decode |
| SSCMA Swift-YOLO, `ModelAssistant` **`main`** branch (v1, junk boxes) | vendored stack, no mmcv, fast | **box flood** |
| SSCMA Swift-YOLO, `main` branch (v3, real boxes, mAP@50 0.87) | same | **box flood, identical** — proved it's the export head, not the data |
| SSCMA Swift-YOLO, **`fix/colab-py312`** (the `2.0.0` MMDet pipeline) | needs `mmcv 2.2` **source build, ~30 min, stalls Colab** | not completed — killed the build at 41 min |
| **Ultralytics YOLOv8n, `ultralytics==8.2.8`, `format=tflite int8`** — trained on Colab, **exported locally on Apple Silicon** (arm64 py3.9) | 8.2.8 onnx2tf path, then vela | ✅ **WORKS** — clean single boxes, quiet on empty scene, `postprocess: 1ms`. Detects up close; box geometry frozen near the training-average location (under-calibrated INT8 — only 100 calib images) |

Key realisation: v1 (bad boxes) and v3 (good boxes, mAP 0.87) flooded
**identically**. That rules out the training data. The common factor is the
`main`-branch export head. SSCMA issue **#319** is an unanswered maintainer
report of the same thing (a custom RTMDet, everything validated, "invoke fails"
while stock Swift-YOLO works — "is the toolchain ahead of the firmware decode?").

---

## The working recipe: `ultralytics==8.2.8`, exported locally on Apple Silicon

**2026-09-09 — this produced the first model the device actually decodes.**
3-class (`<you>`, `dog`, `cat`), YOLOv8n @ 192px, mAP@50 0.907 (`<you>` 0.995,
`dog` 0.867, `cat` 0.859). On device: one box per real object, quiet on an empty
scene, `postprocess: 1ms`. All three classes detect.

Seeed's official multi-class recipe is `wiki.seeedstudio.com/ma_deploy_yolov8` —
no mmcv, no COCO conversion, multi-class is just `nc` in `data.yaml`.

**The one non-obvious split:** Colab **trains** 8.2.8 fine but **cannot export**
it — Colab is Python 3.13 now and every `format=tflite` run hits the onnx2tf
`flatbuffer_direct` bug. Export must run on an environment old enough to match
the 8.2.8 toolchain: **arm64 Python 3.9** (`/usr/bin/python3` → 3.9.6 on this
Mac). **Not** the Homebrew `python3.11` at `/usr/local` — Intel/Rosetta → x86
TensorFlow → `Abort trap: 6` on AVX. `tools/gv2/export_yolov8_gv2.sh` builds the
right venv and refuses to run on x86.

### Full process, start to finish

Every command below refers to a file **in this repo** — nothing lives only in a
notebook or a scratch dir any more.

| # | step | command |
|---|---|---|
| 1 | **Capture** each class (motion-gated). Ask the tag name first; follow `docs/vision/capture-checklist.md`. | `g2cam <class> <session>` |
| 2 | **Curate** — dedup, contact sheet, writes YOLO `.txt` from the capture-time detector. | `curate_captures.py … --class-id N` (aliases `g2neg` for empty rooms) |
| 3 | **Promote** the good frames into the library. | `g2promote <class> <session>` |
| 4 | **Auto-box** any class whose captures had no boxes (pets), using a COCO YOLOv8. | `python tools/autobox_coco.py ~/Desktop/g2_vision_library/<class> --coco-class {person,dog,cat} --weights yolov8m.pt --imgsz 800 --overwrite` |
| 5 | **Combine** the library → one flat folder, class-ids rewritten from `--classes` order. | `python tools/combine_for_upload.py ~/Desktop/g2_vision_library --classes <you>,dog,cat --out ~/Desktop/g2_vision_library/upload_vN` |
| 6 | **Split + resize + zip** → the dataset the notebook eats. | `python tools/gv2/split_yolo_dataset.py ~/Desktop/g2_vision_library/upload_vN --classes <you>,dog,cat --imgsz 224 --out ~/Desktop/g2_vision_library/custom_data_yolo_vN.zip` |
| 7 | **Train** on Colab — `g2_yolov8_828_3class.ipynb`, T4 GPU, upload the zip from step 6, run top-to-bottom, download `best.pt`. | notebook: `yolo train detect model=yolov8n.pt data=/content/ds/data.yaml imgsz=192 epochs=100` |
| 8 | **Build a calibration set** — 300+ varied jpgs. Reuse `upload_vN` or a wider pull; a flat folder of `.jpg` is all the script needs. | (a folder path) |
| 9 | **Export + vela locally** — makes the arm64 venv, patches onnx2tf, exports INT8 tflite, vela → 100% NPU. | `tools/gv2/export_yolov8_gv2.sh best.pt <calib_dir> 3 <you>,dog,cat` |
| 10 | **Flash** — SenseCraft → device page → **Upload Model** → pick `gv2_out/best_full_integer_quant_vela.tflite`, add class names as Objects (**Add Object → type → Add Object again** per chip; plain Enter overwrites the one chip), Send. Or `python-sscma` serial (see "Also worth knowing"). | |
| 11 | **Verify** on device: quiet on empty scene, one box per object. Headless: `python tools/vision_diag.py <port> --secs 40`. | |
| 12 | **Cleanup** — delete the Colab runtime (wipes the uploaded photos). See the Cleanup section. | |

### What `export_yolov8_gv2.sh` does (and why each piece is load-bearing)

Exact pins live in the script (`ultralytics==8.2.8`, `tensorflow==2.16.2`,
`tf-keras==2.16.0`, `onnx==1.16.1`, `onnx2tf==1.17.5`, `onnxsim==0.4.36`,
`onnx_graphsurgeon==0.6.1`, `sng4onnx==2.0.1`, `numpy==1.26.4`,
`ethos-u-vela==5.0.0`). Three fixes are **mandatory** — each was a hard failure
without it:

| env / patch | error it fixes |
|---|---|
| `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` | `_pickle.UnpicklingError: Weights only load failed` (torch ≥2.6 defaults `weights_only=True`) |
| `TF_USE_LEGACY_KERAS=1` | `A KerasTensor cannot be used as input to a TensorFlow function` (onnx2tf 1.17.5 is Keras-2; TF 2.16 ships Keras-3) |
| patch `onnx2tf/onnx2tf.py`: `normalized_calib_data = (…) / std` → append `.astype(np.float32)` | `Cannot set tensor: Got FLOAT64 but expected FLOAT32 … serving_default_images:0` (INT8 calib normalisation promotes to float64) |

`onnxsim` (**not** `onnxslim` — different package) is also required, or onnx2tf
hits `MaxPool: unsupported operand … 'NoneType' and 'int'` on unsimplified
dynamic dims. A `No module named 'tflite_support'` at the very end is
**cosmetic** — `best_full_integer_quant.tflite` is already written; ignore it.

The INT8 **calibration set** is the `val:` list in the throwaway `data.yaml` the
script writes (`yolo export int8` calibrates on val). **Use 300+ varied images**
— the working model used only 100 and that is the leading suspect for its
"detects up close only, box frozen at the training-average position" behaviour.

vela runs with `tools/gv2/vela_config_we2.ini` (committed) —
`--accelerator-config ethos-u55-64 --system-config My_Sys_Cfg --memory-mode
My_Mem_Mode_Parent`. Output `gv2_out/*_vela.tflite`, ~2.3 MB, `ethos-u` op
present, 0 CPU ops.

### Dataset format (what step 6 produces / `yolo train` wants)

```
ds/
  data.yaml            # path: /content/ds  train: images/train  val: images/val  nc: 3  names: [<you>, dog, cat]
  images/train/*.jpg   images/val/*.jpg
  labels/train/*.txt   labels/val/*.txt     # YOLO: "<cls> cx cy w h" normalised; class ids 0/1/2
```
Negatives = image with **no** `.txt` → ultralytics treats as background.
`split_yolo_dataset.py` does a seeded, class-stratified split (default 15% val)
so every class + the negatives pool appears in val. Do **not** use
`yolo_to_coco_zip.py` here (that's for the dropped SSCMA path).

---

## The re-labelling pipeline (this is reusable — the key fix)

The `dog`/`cat` library images had **no boxes** (captured, never labelled;
training used `combine_for_upload.py --box-fallback` = a whole-frame box, which
taught the model a position prior → overfit flood on top of the head problem).

`tools/autobox_coco.py` fixes this — runs a COCO-pretrained YOLOv8 over a class
folder and writes real YOLO `.txt` boxes:

```bash
# venv with ultralytics + numpy<2
python tools/autobox_coco.py ~/Desktop/g2_vision_library/dog  --coco-class dog    --weights yolov8m.pt --conf 0.10 --imgsz 800 --overwrite
python tools/autobox_coco.py ~/Desktop/g2_vision_library/cat  --coco-class cat    --weights yolov8m.pt --conf 0.20 --imgsz 800 --max-boxes 2 --overwrite
python tools/autobox_coco.py ~/Desktop/g2_vision_library/<you> --coco-class person --weights yolov8m.pt --conf 0.25 --imgsz 800 --max-boxes 1 --overwrite
```

2026-09-09 results: `<you>` 230/238, `cat` 218/250, `dog` **127/250** (the rest
are motion-blurred junk — dog capture session had heavy blur; that class wants a
recapture with the subject held still). Writes class id `0` as a placeholder;
`combine_for_upload.py --classes` rewrites it from the class order.

Then combine → split → zip (steps 5–6 above):
```bash
python tools/combine_for_upload.py ~/Desktop/g2_vision_library --classes <you>,dog,cat \
  --out ~/Desktop/g2_vision_library/upload_vN
python tools/gv2/split_yolo_dataset.py ~/Desktop/g2_vision_library/upload_vN --classes <you>,dog,cat \
  --imgsz 224 --out ~/Desktop/g2_vision_library/custom_data_yolo_vN.zip
```
`split_yolo_dataset.py` resizes (224; train runs at 192, the margin keeps the
zip small), does the seeded class-stratified train/val split, and carries
negatives through as background. (The dropped SSCMA path used
`tools/yolo_to_coco_zip.py` instead — not needed now.)

`tools/vision_diag.py <port> --secs 40` — headless: pulls raw device boxes,
applies score-floor + NMS + top-K, flags "PLANTED" box locations (fire every
frame regardless of scene = overfit/garbage). Use it to judge a flashed model
without SenseCraft's preview.

---

## Fallback: Edge Impulse (structurally immune to the firmware problem)

EI is an officially supported target and compiles a **complete firmware binary**
(`.uf2`, drag-and-drop) — its own inference + post-processing baked in, **does
not run on Seeed's SSCMA-Micro firmware**, so the decoder-mismatch failure mode
can't happen.

- Model: **FOMO** (MobileNetV2 0.35 for the memory budget) → **class + centroid**,
  not bounding boxes. Fine for "is <you>/dog/cat in view and roughly where".
- Multi-class: yes. Labelling tool built into EI Studio, or upload pre-labelled.
- Cost: centroids not boxes; you flash the whole firmware (lose SenseCraft's
  4 model slots + its preview UI). Forum note: pick a real backbone + int8, not
  the tiny default, or you get a <50 kB useless model.

Take this route if pinned-8.2.8 YOLOv8 also floods.

---

## Also worth knowing

- **Local serial flashing (skip SenseCraft cloud):** `python-sscma` —
  `sscma.cli flasher model_int8_vela.tflite 0x400000`, then set class names with
  `AT+MODEL=1` + `AT+INFO="<base64 of {uuid,name,version,classes[]}>"`. Removes
  SenseCraft as a variable and stops uploading the model + class names to Seeed.
  Device holds up to 4 models (`0x400000 0x600000 0x800000 0xA00000`),
  `AT+MODELS?` lists them, `AT+MODEL=n` switches.
- **SSCMA export calibration bug (#276, #294):** `tools/export.py` INT8
  calibration only picks up **`.jpg`** files at the **top level** of
  `--image_path`. PNG or nested → silent bad quantisation → invoke fails. Fix:
  jpg, top-level, delete stale `calibration_image_sample_data_20x128x128x3_float32.npy`.
- **SenseCraft web training is single-class only** — not an option for
  multi-class.
- **Model size ceiling: ~2 MB** quantised (device flash slot). Our vela models
  are ~1 MB, fine.
- Firmware source: `github.com/Seeed-Studio/sscma-example-we2` (releases) /
  `SSCMA-Micro` submodule. No release since `20250102`; `main` has Dec-2025
  commits (face-embedding) but unreleased.

---

## Cleanup — ALWAYS the last step

Colab uploads the whole training set to the runtime VM. As soon as a model is
flashed and confirmed on the device, and the local keepers exist under
`~/Desktop/g2_vision_library/` (`best.pt`, the dataset zip, `*_vela.tflite`):

1. Every Colab notebook used this round → **Runtime → Disconnect and delete
   runtime**. That wipes the uploaded photos from Google's VM.
2. The `.ipynb` files in Drive are **code only, no photos** — keep them (also
   mirrored at `~/Desktop/g2_vision_library/` and `~/Downloads/`).

This is part of the process, not optional: the photos are personal data and
there's no reason to leave them on a third-party VM once the model is built.

---

## Adding `<spouse>` later (the 4-class model)

Run the **Full process** table again, changed only at:
- step 1–3: capture `<spouse>` (~140 raw, `capture-session-checklist.md`),
  `g2neg`/curate/`g2promote <spouse>`
- step 4: `autobox_coco.py <spouse-folder> --coco-class person`
- steps 5–6: `--classes <you>,<spouse>,dog,cat` (id order is append-only —
  `combine_for_upload.py` + `split_yolo_dataset.py` rewrite/read every label
  from that order; the existing `<you>`/`dog`/`cat` frames don't change)
- step 7: notebook `nc: 4` (the split's `data.yaml` already carries it)
- step 9: `export_yolov8_gv2.sh best.pt <calib_dir> 4 <you>,<spouse>,dog,cat`
- step 12: Cleanup, as always.

`ledge` still waits for the G2 camera mount.
