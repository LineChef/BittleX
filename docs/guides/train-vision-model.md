# Train a visual model for G2 — full walkthrough

Every step and command to go from "nothing" to "a custom detection model running
on the Grove Vision AI V2", doable by one person. Written for a face/person
recognition model (`alex`), but the same flow trains any object model.

Related: `vision/capture-checklist.md` (the capture routine),
`vision/person-recognition.md` (design + the enrollment concept),
`vision/detection-layer.md` (multi-model architecture),
[Detection layer](../vision/detection-layer.md#measured-detector-behaviour) (measured module behaviour).

---

0 · Prerequisites
-----------------

- Grove Vision AI V2 + its camera, USB-C cable (data, not charge-only).
- A **SenseCraft AI** account (`sensecraft.seeed.cc`) — free.
- Chrome or Edge (SenseCraft needs WebSerial; Safari won't work).
- The repo, with the venv: `source pi_pipeline/.venv/bin/activate`.
- Camera plugged into the Mac. Confirm: `ls /dev/cu.usbmodem*`.

> **Only one program can hold the port at a time.** SenseCraft's in-app "disconnect" does NOT release the
> browser's serial port — the **SenseCraft tab must be closed** before any local
> script can open `/dev/cu.usbmodem*` (else "Resource busy"; `lsof` shows
> Google Chrome).

---

1 · Put a base detection model on the module
--------------------------------------------

Used only to generate pre-label boxes during capture — it is replaced by the
trained model later.

1. SenseCraft → **Models** → **Model Library**.
2. Filter: search `person`, Supported Devices = **Grove - Vision AI V2**.
3. Open **"Person Detection--Swift YOLO"** → **Deploy Model** → connect the
   module over USB → flash (~1–2 min).
4. (Optional, tighter face boxes but misses far/turned shots: **Face Detection**
   instead.)

Verify what's loaded:
```
python - <<'PY'
import time,serial,glob,json,base64
s=serial.Serial(glob.glob("/dev/cu.usbmodem*")[0],921600,timeout=.4);time.sleep(2.5)
s.write(b"AT+INFO?\r\n");time.sleep(.5)
d=json.loads(s.read(8192).decode("utf-8","replace").strip())["data"]["info"]
print(base64.b64decode(d+"="*(-len(d)%4)).decode("utf-8","replace")[:240])
PY
```

---

2 · Camera orientation (do this ONCE, then lock it)
---------------------------------------------------

The sensor outputs its native orientation — often **90° rotated**. That matters:

- Person Detection is trained on *upright* people: On a sideways feed it
  misses the subject in most frames → few pre-labels. (Session-1 test: 46 boxes / 342
  frames sideways.)
- Rotating on the module is not possible: no AT command, and camera sensors can't do
  a 90° transpose (only H/V flip).

So **physically rotate the camera module 90°** until its raw feed is upright
(check the preview *before* pressing "rotate view"). Note which way — that's the
orientation it will be mounted in on G2, and it must match for all sessions. Then note
the `--rotate` value curate needs for that orientation (try 0 first; 90/180/270 if rotated; the
contact sheet shows whether it is upside-down).

---

3 · Capture a session
---------------------

Full detail incl. the **standard pose set** (run it every session): `vision/capture-checklist.md`. Short form:

1. Decide the **tag name** (`alex`), **which session** (1, 2, or 3).
2. Room as bright as reasonable (the `--rotate`/AE settings help, but light is
   the real lever).
3. Launch the live preview:
   ```
   export G2_CAP_OUT=~/Desktop/G2Memory/g2_face_capture/alex/session_1
   export G2_CAP_LABEL=alex G2_CAM_RES=1
   mkdir -p "$G2_CAP_OUT"; rm -f "$G2_CAP_OUT"/*.jpg "$G2_CAP_OUT"/*.json
   python tools/camera_preview.py &
   open http://localhost:8080
   ```
   It sets the sensor to 480 + an auto-exposure lift, streams the feed with the
   detection box drawn, and (while "Start capturing" is on) saves
   `alex_NNNN.jpg` + `alex_NNNN.json` (the box, for pre-labels).

   **Motion-gated saving is on by default** (`G2_CAP_GATE=12`): a held pose saves
   ~1 frame (plus one every `G2_CAP_KEEPALIVE=8` s), and frames flow again when
   the subject moves, so near-identical shots do not pile up. The status line shows
   `saved N (M skipped, static)`. Move *slowly and deliberately* through each
   pose and it captures the whole arc; freeze and it stops. `G2_CAP_GATE=0`
   restores the old "save every 4th frame" behaviour.
4. Pose sequence — capturing can stay ON the whole time; the subject moves slowly:
   - distance: close (~1.5 ft) → mid (~3 ft) → far (~5–6 ft), straight on
   - head: slow full turn L↔R; chin up; chin down; look away L/R/up
   - expression: talking, smile, neutral, surprised
   - occlusion: hand near face, push hair back
   - second spot / light: repeat close + mid
   - Aim for **~90–120 saved** (motion-gated, so most are distinct), then ~12 s
     **negatives** (step out of frame / point at a wall).
5. Stop the preview: `pkill -f camera_preview.py`.

**3 sessions per person**, different rooms / lighting / clothes (session 1 can be
one look, e.g. hair up; 2–3 the normal look).

---

4 · Curate the raw batch
------------------------

```
python tools/curate_captures.py \
    ~/Desktop/G2Memory/g2_face_capture/alex/session_1 \
    ~/Desktop/G2Memory/g2_face_capture/alex/session_1/curated \
    --positives 100 --negatives 15 --class-id 0 --label-region face --rotate 0
```

- Scores every frame (brightness / contrast / sharpness), drops rejects,
  **removes near-duplicates** (two passes: a held pose → 1 frame but a slow
  head-turn keeps its arc; then a tight global pass drops a pose captured
  twice), spread-samples across the timeline, rotates upright, writes a **YOLO
  `.txt` per positive** from the detection box (`--label-region face` tightens it
  toward the face; the *image* stays full-frame — never crop training images for
  a detector). The summary prints `dedup: dropped N near-duplicate positives`.
  Tune with `--hash-thresh` (held-pose pass, higher = thin harder, default 8) /
  `--dup-thresh` (global pass, default 4); `--no-dedup` keeps everything.
- Outputs `pos_NNNN.jpg` (+ `.txt`), `neg_NNNN.jpg`, `_contact_sheet.png`,
  `_summary.txt`.
- Read the printout: it reports **usable positives + negatives this
  session** and the **running total toward ~100** across all curated sessions
  for that person.
- Open `_contact_sheet.png`: images upright? (else change `--rotate`.) Poses
  varied? Faces exposed?
- Some "negatives" may actually be the subject (Person Detection missed them) — at
  upload, delete those or label them `alex`; don't use them as real negatives.

Re-run with tweaked flags freely — it's non-destructive (raw frames kept).
`--min-sharpness` lower if good frames are tossed as blurry.

---

5 · Promote to the library, then combine for upload
---------------------------------------------------

Keep two folders (see `vision/capture-progress.md`): **`g2_capture_raw/`**
(disposable — raw + curate output) and **`g2_vision_library/`** (KEEP — only
curated, labelled, upload-ready, one subfolder per class).

**Promote** each reviewed curated session into the library — it continues the
per-class numbering and updates `_MANIFEST.md`:

```
python tools/promote_to_library.py \
    ~/Desktop/G2Memory/g2_capture_raw/person/session_1/curated \
    --library ~/Desktop/G2Memory/g2_vision_library --class person
```
(Idempotent — a promoted session is skipped unless `--force`.)

**Combine** the library into one flat `upload/` folder when it's time to train.
It renames to avoid collisions and rewrites each label's class-id from the
`--classes` ORDER (so the library stays reorder-safe — the id lives in the class
list, not baked into the files):

```
python tools/combine_for_upload.py ~/Desktop/G2Memory/g2_vision_library \
    --classes person,dog,cat,ledge
# -> ~/Desktop/G2Memory/g2_vision_library/upload/   (import THIS folder in step 6)
```

`--classes` order = class-id order = the `VISION_LABELS` order. It also runs on a raw
root (`<class>/session_*/curated/…`) if the library is skipped.

---

6 · Train in SenseCraft
-----------------------

1. Models → Training → Image Object Detection: tab → **Image Collection
   Training** (NOT "Quick Training" — that has no upload).
2. Step 1: object name: `alex`.
3. Step 2: skip the "Connect" (that is live capture; files already exist).
4. Step 3: **Import Dataset** → the `upload/` folder. The `.txt` files are
   YOLO pre-labels; images land under **Labeled** with boxes **already drawn**.
   - Do NOT run SenseCraft's auto-label: it single-classes everything. The
     `.txt` files already carry the right class per image.
   - Review the boxes; assign each class-id to its name (`0`→`person`, …).
   - Unlabeled (no-box) frames: box them by hand, or delete.
   - Negatives: leave unlabeled. Delete any that actually show a class.
   - Need ≥10 labeled; aim for all.
5. Step 4: target device **Grove Vision AI V2** → **Start Training**
   (~10–30 min, cloud).

### Where the labels come from — almost nothing is labelled by hand

Object detection is **one flat dataset, all classes uploaded together**; the
class is set by the id in each `.txt`, not by folders. There is no "upload one
class at a time" and there never will be — the model trains on all classes
jointly. `combine_for_upload.py --classes a,b,c` builds that folder and writes
`classes.txt` / `data.yaml` alongside.

The boxes are made **at capture time**, not by hand:

- `person`: box source: Person-Detection base model → `.json` sidecar → `curate` writes the `.txt`; manual effort: **none** — already labelled in the library
- `dog`, `cat`: box source: capture with a **COCO-80** model loaded → sidecar has dog/cat boxes → `curate` writes `.txt`; manual effort: none for frames it caught; hand-box the misses
- `ledge`: box source: nothing auto-detects it; manual effort: **box it** — see below

**Labelling `ledge`** (the only real work): it's one repeated object on a slow
pan, so —
- Roboflow is fastest: upload just the `ledge` images, use *Label Assist* /
  "repeat previous box", export **YOLO v8**, drop the `.txt` files next to the
  jpgs, `g2promote ledge`. ~20-30 min for ~200 frames.
- Or: box ~1 frame in 10 in any labeller, then
  `python tools/interp_labels.py <curated_dir> --class-id 3` interpolates a box
  onto every frame between the keyframes; spot-check the ones it flags as far
  from a keyframe, then promote.

> Architecture lock: whatever path is taken, the model has to be
> **Swift-YOLO** — the GV2 firmware's box decoder understands nothing else. A
> standard Ultralytics YOLOv8 model (e.g. from an Ultralytics Colab) will flash,
> run on the NPU, and return `boxes:[]` forever. SenseCraft **web** training is
> Swift-YOLO but single-class; **multi-class needs the SSCMA Swift-YOLO Colab**
> (`vision/capture-progress.md` has the status + the `torch==2.0.0` blocker).

### Multi-class -- training ON TOP OF person detection

To get one model that does person detection AND recognises individuals
(`person` + `alex` + household + pets), instead of a single-class model that
replaces it:

1. Try "Retrain" on the library person model first. Model Library ->
   "Person Detection--Swift YOLO" -> look for **Retrain / Train your own /
   Clone to project / Edit dataset**. If present, it opens that model's dataset
   (thousands of person images) in Training -- add a class `alex`, import the
   `alex/upload/`, assign the boxes to `alex`, train. That's literally on top of
   it: keeps the big `person` class and adds a new one.
2. No retrain option -> a 2-class project: Training -> a project / multi-class
   object-detection flow (NOT the single-object "Image Collection Training").
   Classes `person` + `alex`. Import `alex/upload/` as `alex`; add a few hundred
   varied generic-person images (Roboflow Universe "person detection" dataset, or
   the COCO `person` subset) as `person` so it still detects strangers. Train.
3. Class ids: curate writes class `0`. For `[person=0, alex=1]` re-run
   `curate_captures.py <session> --class-id 1 ...`, or just pick the class in
   SenseCraft's labeller (box already drawn).
4. `.env`: `VISION_LABELS=person,alex` (class-id order) +
   `G2_BONDS=alex:1.0:affectionate`.

This is the "interaction model" in `vision/detection-layer.md` -- add each
household member / pet as another class in the same project over time.

---

7 · Deploy + verify
-------------------

1. Training done → **Deploy to device** → connect module → flash (~1–2 min).
   (SenseCraft's "please flash first" on the preview after a dropped tab is a UI
   glitch — the flash usually succeeded; verify below.)
2. Close the SenseCraft tab (frees the port).
3. Check what's on the module (the `AT+INFO?` snippet from step 1) — expect
   `"classes":["alex"]`, `"isCustom":true`.
4. Run it through the pipeline:
   ```
   VISION_LABELS=alex python -m pi_pipeline.vision serial /dev/cu.usbmodem58FA1045341
   ```
   Point it at the subject → `alex` boxes with a score; nothing on an empty room.
   0 detections = the dataset was too weak (dark / too few / one condition) —
   recapture better and retrain. It's cheap and repeatable.

---

8 · Wire into G2
----------------

`.env` (gitignored):
```
VISION_LABELS=person,alex            # in the model's class-id order
G2_BONDS=alex:1.0:affectionate       # name:closeness:disposition[:kind]
```
Now `Bonds` returns a real disposition for `alex`; before training, an
unrecognised person defaulted to `curious`.

---

Troubleshooting
---------------

- "Resource busy" opening the serial port: SenseCraft/Chrome tab still holds WebSerial — **close the tab** (or unplug/replug USB).
- Few pre-labels (`raw pos` low in curate): Feed is sideways → Person Detection misses the subject. **Rotate the camera 90°** (step 2). Also: far / backlit / heavy-occlusion poses just won't get a person box — hand-label those.
- Curated images upside-down / sideways: Wrong `--rotate` — try 90 / 180 / 270; the contact sheet shows it.
- Dark / grainy frames: `G2_CAM_RES=1` + the AE lift are on by default in `camera_preview.py`; graininess past that is **low light** — add lamps. Longer exposure (brighter) trades against motion blur — hold still on poses.
- Only a handful of positives after curate: De-dup was collapsing distinct poses (fixed: consecutive-only). If still low, it's genuinely a capture-coverage problem — capture more easy (close/mid straight-on) frames.
- Trained model detects nothing: Dataset below the floor — dark, too few (<~40 varied), one lighting/background. Recapture in daylight, 3 varied sessions, retrain.
- Model flashes + runs (`inference: ~90ms` in Device Logger) but `boxes:[]` on every frame, any threshold: **Wrong architecture.** GV2 firmware only decodes the **Swift-YOLO** head. A standard Ultralytics YOLOv8 export runs but its detection tensor is unreadable → permanent empty boxes. Must train/export via SSCMA. See Capture progress.
- Model confuses two people: Coarse at 192 px — more data per person, or move to face-embedding recognition (`vision/person-recognition.md` "upgrade path").

What lives where
----------------

- Capture routine → `vision/capture-checklist.md`
- This end-to-end → here
- Why recognition + the "G2, meet X" enrollment concept → `vision/person-recognition.md`
- One-model-slot / multi-model architecture → `vision/detection-layer.md`
- Measured module numbers, the AE-lift finding → [Detection layer](../vision/detection-layer.md#measured-detector-behaviour)
- `tools/curate_captures.py --help` for all curate flags

Device constraints and the working recipe
-----------------------------------------

If you're picking this up,
**read the "Core constraint" section first** — it explains why most tutorials
fail on the device.

Companion: `capture-progress.md` (data/capture tracker),
`guides/train-vision-model.md` (the older SenseCraft-web single-class flow),
`detection-layer.md` (one-model-slot architecture).

Repo tooling for this flow: **`tools/gv2/`** —
`split_yolo_dataset.py` (library → train/val zip), `export_yolov8_gv2.sh`
(the arm64 local export + vela, exact pins inside), `vela_config_we2.ini`
(the Himax WE2 vela profile). Plus `tools/autobox_coco.py`,
`tools/combine_for_upload.py`, `tools/vision_diag.py`.

---

### Core constraint: the device firmware is frozen at Jan 2025

The Grove Vision AI V2's on-device firmware (`SSCMA-Micro`, latest release tag
`20250102`) does the pre/post-processing around the `.tflite` you flash — the
anchor decode, the objectness gate, NMS. **You flash only the model; the
firmware's decoder has to recognise its output head.**

Every training toolchain has moved forward since Jan 2025 and their exports
drifted out of sync with that frozen decoder. Symptoms of a mismatch:

- `boxes:[]` every frame, `inference` time normal: firmware ran the conv layers but its decoder produced nothing from the head → head format it doesn't recognise
- box flood: 10-30 boxes/frame, high conf, on an anchor grid, `postprocess: 0ms`, confidence/IoU sliders do nothing: firmware is dumping raw anchor outputs — objectness gate + NMS never applied → head format it doesn't recognise
- `Invoke failed` / Device Logger blank: quantisation broken OR head type unsupported (see SSCMA issues #276, #294, #319)

A working model is **quiet on an empty scene** and puts **one box per real
object**.

**What firmware `20250102` DOES decode** (from its changelog + stock models):
- Swift-YOLO as exported by **SSCMA / ModelAssistant `2.0.0` branch** (all the
  stock SenseCraft models — Person Detection, Hand Gesture — are this)
- Ultralytics YOLOv8: exported with **`ultralytics==8.2.8`** (per Seeed's
  official wiki `ma_deploy_yolov8`, last updated Apr 2024) — **confirmed working**, exported locally on Apple Silicon (recipe below)
- YOLO11 (added in the `20250102` release)
- NOT: YOLO26. **NOT** RTMDet. **NOT** the SSCMA `main` / `fix/colab-py312-main`
  re-implemented Swift-YOLO head.

---

### The working recipe: `ultralytics==8.2.8`, exported locally on Apple Silicon

**This produced the first model the device actually decodes.**
3-class (`<you>`, `dog`, `cat`), YOLOv8n @ 192px, mAP@50 0.907 (`<you>` 0.995,
`dog` 0.867, `cat` 0.859). On device: one box per real object, quiet on an empty
scene, `postprocess: 1ms`. All three classes detect.

Seeed's official multi-class recipe is `wiki.seeedstudio.com/ma_deploy_yolov8` —
no mmcv, no COCO conversion, multi-class is just `nc` in `data.yaml`.

The one non-obvious split: Colab **trains** 8.2.8 fine but **cannot export**
it — Colab is Python 3.13 now and every `format=tflite` run hits the onnx2tf
`flatbuffer_direct` bug. Export must run on an environment old enough to match
the 8.2.8 toolchain: **arm64 Python 3.9** (`/usr/bin/python3` → 3.9.6 on this
Mac). **Not** the Homebrew `python3.11` at `/usr/local` — Intel/Rosetta → x86
TensorFlow → `Abort trap: 6` on AVX. `tools/gv2/export_yolov8_gv2.sh` builds the
right venv and refuses to run on x86.

#### Full process, start to finish

Every command below refers to a file **in this repo** — nothing lives only in a
notebook or a scratch dir any more.

- 1: step: **Capture** each class (motion-gated). Ask the tag name first; follow `docs/vision/capture-checklist.md`.; command: `g2cam <class> <session>`
- 2: step: **Curate** — dedup, contact sheet, writes YOLO `.txt` from the capture-time detector.; command: `curate_captures.py … --class-id N` (aliases `g2neg` for empty rooms)
- 3: step: **Promote** the good frames into the library.; command: `g2promote <class> <session>`
- 4: step: **Auto-box** any class whose captures had no boxes (pets), using a COCO YOLOv8.; command: `python tools/autobox_coco.py ~/Desktop/G2Memory/g2_vision_library/<class> --coco-class {person,dog,cat} --weights yolov8m.pt --imgsz 800 --overwrite`
- 5: step: **Combine** the library → one flat folder, class-ids rewritten from `--classes` order.; command: `python tools/combine_for_upload.py ~/Desktop/G2Memory/g2_vision_library --classes <you>,dog,cat --out ~/Desktop/G2Memory/g2_vision_library/upload_vN`
- 6: step: **Split + resize + zip** → the dataset the notebook eats.; command: `python tools/gv2/split_yolo_dataset.py ~/Desktop/G2Memory/g2_vision_library/upload_vN --classes <you>,dog,cat --imgsz 224 --out ~/Desktop/G2Memory/g2_vision_library/custom_data_yolo_vN.zip`
- 7: step: **Train** on Colab — `g2_yolov8_828_3class.ipynb`, T4 GPU, upload the zip from step 6, run top-to-bottom, download `best.pt`.; command: notebook: `yolo train detect model=yolov8n.pt data=/content/ds/data.yaml imgsz=192 epochs=100`
- 8: step: **Build a calibration set** — 300+ varied jpgs. Reuse `upload_vN` or a wider pull; a flat folder of `.jpg` is all the script needs.; command: (a folder path)
- 9: step: **Export + vela locally** — makes the arm64 venv, patches onnx2tf, exports INT8 tflite, vela → 100% NPU.; command: `tools/gv2/export_yolov8_gv2.sh best.pt <calib_dir> 3 <you>,dog,cat`
- 10: step: **Flash** — SenseCraft → device page → **Upload Model** → pick `gv2_out/best_full_integer_quant_vela.tflite`, add class names as Objects (**Add Object → type → (see below)
- 11: step: **Verify** on device: quiet on empty scene, one box per object. Headless: `python tools/vision_diag.py <port> --secs 40`.
- 12: step: **Cleanup** — delete the Colab runtime (wipes the uploaded photos). See the Cleanup section.

- 10: **Flash** — SenseCraft → device page → **Upload Model** → pick `gv2_out/best_full_integer_quant_vela.tflite`, add class names as Objects (**Add Object → type → Add Object again** per chip; plain Enter overwrites the one chip), Send. Or `python-sscma` serial (see "Also worth knowing").


#### What `export_yolov8_gv2.sh` does (and why each piece is load-bearing)

Exact pins live in the script (`ultralytics==8.2.8`, `tensorflow==2.16.2`,
`tf-keras==2.16.0`, `onnx==1.16.1`, `onnx2tf==1.17.5`, `onnxsim==0.4.36`,
`onnx_graphsurgeon==0.6.1`, `sng4onnx==2.0.1`, `numpy==1.26.4`,
`ethos-u-vela==5.0.0`). Three fixes are **mandatory** — each was a hard failure
without it:

- `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`: `_pickle.UnpicklingError: Weights only load failed` (torch ≥2.6 defaults `weights_only=True`)
- `TF_USE_LEGACY_KERAS=1`: `A KerasTensor cannot be used as input to a TensorFlow function` (onnx2tf 1.17.5 is Keras-2; TF 2.16 ships Keras-3)
- patch `onnx2tf/onnx2tf.py`: `normalized_calib_data = (…) / std` → append `.astype(np.float32)`: `Cannot set tensor: Got FLOAT64 but expected FLOAT32 … serving_default_images:0` (INT8 calib normalisation promotes to float64)

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

#### Dataset format (what step 6 produces / `yolo train` wants)

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

### The re-labelling pipeline (this is reusable — the key fix)

The `dog`/`cat` library images had **no boxes** (captured, never labelled;
training used `combine_for_upload.py --box-fallback` = a whole-frame box, which
taught the model a position prior → overfit flood on top of the head problem).

`tools/autobox_coco.py` fixes this — runs a COCO-pretrained YOLOv8 over a class
folder and writes real YOLO `.txt` boxes:

```bash
# venv with ultralytics + numpy<2
python tools/autobox_coco.py ~/Desktop/G2Memory/g2_vision_library/dog  --coco-class dog    --weights yolov8m.pt --conf 0.10 --imgsz 800 --overwrite
python tools/autobox_coco.py ~/Desktop/G2Memory/g2_vision_library/cat  --coco-class cat    --weights yolov8m.pt --conf 0.20 --imgsz 800 --max-boxes 2 --overwrite
python tools/autobox_coco.py ~/Desktop/G2Memory/g2_vision_library/<you> --coco-class person --weights yolov8m.pt --conf 0.25 --imgsz 800 --max-boxes 1 --overwrite
```

Results: `<you>` 230/238, `cat` 218/250, `dog` **127/250** (the rest
are motion-blurred junk — dog capture session had heavy blur; that class wants a
recapture with the subject held still). Writes class id `0` as a placeholder;
`combine_for_upload.py --classes` rewrites it from the class order.

Then combine → split → zip (steps 5–6 above):
```bash
python tools/combine_for_upload.py ~/Desktop/G2Memory/g2_vision_library --classes <you>,dog,cat \
  --out ~/Desktop/G2Memory/g2_vision_library/upload_vN
python tools/gv2/split_yolo_dataset.py ~/Desktop/G2Memory/g2_vision_library/upload_vN --classes <you>,dog,cat \
  --imgsz 224 --out ~/Desktop/G2Memory/g2_vision_library/custom_data_yolo_vN.zip
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

### Fallback: Edge Impulse (structurally immune to the firmware problem)

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

### Also worth knowing

- Local serial flashing (skip SenseCraft cloud): `python-sscma` —
  `sscma.cli flasher model_int8_vela.tflite 0x400000`, then set class names with
  `AT+MODEL=1` + `AT+INFO="<base64 of {uuid,name,version,classes[]}>"`. Removes
  SenseCraft as a variable and stops uploading the model + class names to Seeed.
  Device holds up to 4 models (`0x400000 0x600000 0x800000 0xA00000`),
  `AT+MODELS?` lists them, `AT+MODEL=n` switches.
- SSCMA export calibration bug (#276, #294): `tools/export.py` INT8
  calibration only picks up **`.jpg`** files at the **top level** of
  `--image_path`. PNG or nested → silent bad quantisation → invoke fails. Fix:
  jpg, top-level, delete stale `calibration_image_sample_data_20x128x128x3_float32.npy`.
- SenseCraft web training is single-class only: not an option for
  multi-class.
- Model size ceiling: ~2 MB: quantised (device flash slot). The vela models
  are ~1 MB, fine.
- Firmware source: `github.com/Seeed-Studio/sscma-example-we2` (releases) /
  `SSCMA-Micro` submodule. No release since `20250102`; `main` has Dec-2025
  commits (face-embedding) but unreleased.

---

### Cleanup — ALWAYS the last step

Colab uploads the whole training set to the runtime VM. As soon as a model is
flashed and confirmed on the device, and the local keepers exist under
`~/Desktop/G2Memory/g2_vision_library/` (`best.pt`, the dataset zip, `*_vela.tflite`):

1. Every Colab notebook used this round → **Runtime → Disconnect and delete
   runtime**. That wipes the uploaded photos from Google's VM.
2. The `.ipynb` files in Drive are **code only, no photos** — keep them (also
   mirrored at `~/Desktop/G2Memory/g2_vision_library/` and `~/Downloads/`).

This is part of the process, not optional: the photos are personal data and
there's no reason to leave them on a third-party VM once the model is built.

---

### Adding `<spouse>` later (the 4-class model)

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
