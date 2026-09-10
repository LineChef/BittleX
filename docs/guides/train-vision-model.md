# Train a visual model for G2 — full walkthrough

Every step and command to go from "nothing" to "a custom detection model running
on the Grove Vision AI V2", so you can do it solo. Written for a face/person
recognition model (`alex`), but the same flow trains any object model.

Related: `vision/capture-checklist.md` (the capture routine),
`vision/person-recognition.md` (design + the enrollment concept),
`vision/detection-layer.md` (multi-model architecture),
`vision/detector-bench.md` (measured module behaviour).

---

## 0 · Prerequisites

- Grove Vision AI V2 + its camera, USB-C cable (data, not charge-only).
- A **SenseCraft AI** account (`sensecraft.seeed.cc`) — free.
- **Chrome or Edge** (SenseCraft needs WebSerial; Safari won't work).
- The repo, with the venv: `source pi_pipeline/.venv/bin/activate`.
- Camera plugged into the Mac. Confirm: `ls /dev/cu.usbmodem*`.

> **Port is single-owner.** SenseCraft's in-app "disconnect" does NOT release the
> browser's serial port — you must **close the SenseCraft tab** before any local
> script can open `/dev/cu.usbmodem*` (else "Resource busy"; `lsof` shows
> Google Chrome).

---

## 1 · Put a base detection model on the module

Used only to generate pre-label boxes during capture — you'll overwrite it with
your trained model later.

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

## 2 · Camera orientation (do this ONCE, then lock it)

The sensor outputs its native orientation — often **90° rotated**. That matters:

- **Person Detection is trained on *upright* people.** On a sideways feed it
  misses you in most frames → few pre-labels. (Session-1 test: 46 boxes / 342
  frames sideways.)
- **We can't rotate on the module** — no AT command, and camera sensors can't do
  a 90° transpose (only H/V flip).

So **physically rotate the camera module 90°** until its raw feed is upright
(check the preview *before* pressing "rotate view"). Note which way — that's the
orientation you'll mount it on G2, and it must match for all sessions. Then note
the `--rotate` value curate needs for that orientation (try 0 first; 90/180/270 if rotated; the
contact sheet tells you if it's upside-down).

---

## 3 · Capture a session

Full detail incl. the **standard pose set** (run it every session): `vision/capture-checklist.md`. Short form:

1. Ask yourself: **tag name** (`alex`), **which session** (1, 2, or 3).
2. Room as bright as reasonable (the `--rotate`/AE settings help, but light is
   the real lever).
3. Launch the live preview:
   ```
   export G2_CAP_OUT=~/Desktop/g2_face_capture/alex/session_1
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
   you move — so you don't drown in near-identical shots. The status line shows
   `saved N (M skipped, static)`. Move *slowly and deliberately* through each
   pose and it captures the whole arc; freeze and it stops. `G2_CAP_GATE=0`
   restores the old "save every 4th frame" behaviour.
4. Pose sequence — you can leave capturing ON the whole time; move slowly:
   - **distance:** close (~1.5 ft) → mid (~3 ft) → far (~5–6 ft), straight on
   - **head:** slow full turn L↔R; chin up; chin down; look away L/R/up
   - **expression:** talking, smile, neutral, surprised
   - **occlusion:** hand near face, push hair back
   - **second spot / light:** repeat close + mid
   - Aim for **~90–120 saved** (motion-gated, so most are distinct), then ~12 s
     **negatives** (step out of frame / point at a wall).
5. Stop the preview: `pkill -f camera_preview.py`.

**3 sessions per person**, different rooms / lighting / clothes (session 1 can be
one look, e.g. hair up; 2–3 the normal look).

---

## 4 · Curate the raw batch

```
python tools/curate_captures.py \
    ~/Desktop/g2_face_capture/alex/session_1 \
    ~/Desktop/g2_face_capture/alex/session_1/curated \
    --positives 100 --negatives 15 --class-id 0 --label-region face --rotate 0
```

- Scores every frame (brightness / contrast / sharpness), drops rejects,
  **removes near-duplicates** (two passes: a held pose → 1 frame but a slow
  head-turn keeps its arc; then a tight global pass drops a pose you captured
  twice), spread-samples across the timeline, rotates upright, writes a **YOLO
  `.txt` per positive** from the detection box (`--label-region face` tightens it
  toward the face; the *image* stays full-frame — never crop training images for
  a detector). The summary prints `dedup: dropped N near-duplicate positives`.
  Tune with `--hash-thresh` (held-pose pass, higher = thin harder, default 8) /
  `--dup-thresh` (global pass, default 4); `--no-dedup` keeps everything.
- Outputs `pos_NNNN.jpg` (+ `.txt`), `neg_NNNN.jpg`, `_contact_sheet.png`,
  `_summary.txt`.
- **Read the printout**: it reports **usable positives + negatives this
  session** and the **running total toward ~100** across all curated sessions
  for that person.
- Open `_contact_sheet.png`: images upright? (else change `--rotate`.) Poses
  varied? Faces exposed?
- Some "negatives" may actually be you (Person Detection missed you) — at
  upload, delete those or label them `alex`; don't use them as real negatives.

Re-run with tweaked flags freely — it's non-destructive (raw frames kept).
`--min-sharpness` lower if good frames are tossed as blurry.

---

## 5 · Promote to the library, then combine for upload

Keep two folders (see `vision/capture-progress.md`): **`g2_capture_raw/`**
(disposable — raw + curate output) and **`g2_vision_library/`** (KEEP — only
curated, labelled, upload-ready, one subfolder per class).

**Promote** each reviewed curated session into the library — it continues the
per-class numbering and updates `_MANIFEST.md`:

```
python tools/promote_to_library.py \
    ~/Desktop/g2_capture_raw/person/session_1/curated \
    --library ~/Desktop/g2_vision_library --class person
```
(Idempotent — a promoted session is skipped unless `--force`.)

**Combine** the library into one flat `upload/` folder when it's time to train.
It renames to avoid collisions and rewrites each label's class-id from the
`--classes` ORDER (so the library stays reorder-safe — the id lives in the class
list, not baked into the files):

```
python tools/combine_for_upload.py ~/Desktop/g2_vision_library \
    --classes person,dog,cat,ledge
# -> ~/Desktop/g2_vision_library/upload/   (import THIS folder in step 6)
```

`--classes` order = class-id order = your `VISION_LABELS`. It also runs on a raw
root (`<class>/session_*/curated/…`) if you skip the library.

---

## 6 · Train in SenseCraft

1. **Models → Training → Image Object Detection** tab → **Image Collection
   Training** (NOT "Quick Training" — that has no upload).
2. **Step 1** — object name: `alex`.
3. **Step 2** — skip the "Connect" (that's live capture; you have files).
4. **Step 3** — **Import Dataset** → your `upload/` folder. The `.txt` files are
   YOLO pre-labels; images land under **Labeled** with boxes **already drawn**.
   - **Do NOT run SenseCraft's auto-label** — it single-classes everything. The
     `.txt` files already carry the right class per image.
   - Review the boxes; assign each class-id to its name (`0`→`person`, …).
   - Unlabeled (no-box) frames: box them by hand, or delete.
   - Negatives: leave unlabeled. Delete any that actually show a class.
   - Need ≥10 labeled; aim for all.
5. **Step 4** — target device **Grove Vision AI V2** → **Start Training**
   (~10–30 min, cloud).

### Where the labels come from — you barely label anything

Object detection is **one flat dataset, all classes uploaded together**; the
class is set by the id in each `.txt`, not by folders. There is no "upload one
class at a time" and there never will be — the model trains on all classes
jointly. `combine_for_upload.py --classes a,b,c` builds that folder and writes
`classes.txt` / `data.yaml` alongside.

The boxes are made **at capture time**, not by you:

| class | box source | your effort |
|---|---|---|
| `person` | Person-Detection base model → `.json` sidecar → `curate` writes the `.txt` | **none** — already labelled in the library |
| `dog`, `cat` | capture with a **COCO-80** model loaded → sidecar has dog/cat boxes → `curate` writes `.txt` | none for frames it caught; hand-box the misses |
| `ledge` | nothing auto-detects it | **box it** — see below |

**Labelling `ledge`** (the only real work): it's one repeated object on a slow
pan, so —
- **Roboflow** is fastest: upload just the `ledge` images, use *Label Assist* /
  "repeat previous box", export **YOLO v8**, drop the `.txt` files next to the
  jpgs, `g2promote ledge`. ~20-30 min for ~200 frames.
- **Or** box ~1 frame in 10 in any labeller, then
  `python tools/interp_labels.py <curated_dir> --class-id 3` interpolates a box
  onto every frame between your keyframes; spot-check the ones it flags as far
  from a keyframe, then promote.

> **Architecture lock (2026-09-09):** whatever path you take, the model has to be
> **Swift-YOLO** — the GV2 firmware's box decoder understands nothing else. A
> standard Ultralytics YOLOv8 model (e.g. from an Ultralytics Colab) will flash,
> run on the NPU, and return `boxes:[]` forever. SenseCraft **web** training is
> Swift-YOLO but single-class; **multi-class needs the SSCMA Swift-YOLO Colab**
> (`vision/capture-progress.md` has the status + the `torch==2.0.0` blocker).

### Multi-class -- training ON TOP OF person detection

To get one model that does person detection AND recognises individuals
(`person` + `alex` + household + pets), instead of a single-class model that
replaces it:

1. **Try "Retrain" on the library person model first.** Model Library ->
   "Person Detection--Swift YOLO" -> look for **Retrain / Train your own /
   Clone to project / Edit dataset**. If present, it opens that model's dataset
   (thousands of person images) in Training -- add a class `alex`, import your
   `alex/upload/`, assign the boxes to `alex`, train. That's literally on top of
   it: keeps the big `person` class, adds yours.
2. **No retrain option -> a 2-class project.** Training -> a project / multi-class
   object-detection flow (NOT the single-object "Image Collection Training").
   Classes `person` + `alex`. Import `alex/upload/` as `alex`; add a few hundred
   varied generic-person images (Roboflow Universe "person detection" dataset, or
   the COCO `person` subset) as `person` so it still detects strangers. Train.
3. **Class ids:** curate writes class `0`. For `[person=0, alex=1]` re-run
   `curate_captures.py <session> --class-id 1 ...`, or just pick the class in
   SenseCraft's labeller (box already drawn).
4. **`.env`:** `VISION_LABELS=person,alex` (class-id order) +
   `G2_BONDS=alex:1.0:affectionate`.

This is the "interaction model" in `vision/detection-layer.md` -- add each
household member / pet as another class in the same project over time.

---

## 7 · Deploy + verify

1. Training done → **Deploy to device** → connect module → flash (~1–2 min).
   (SenseCraft's "please flash first" on the preview after a dropped tab is a UI
   glitch — the flash usually succeeded; verify below.)
2. **Close the SenseCraft tab** (frees the port).
3. Check what's on the module (the `AT+INFO?` snippet from step 1) — expect
   `"classes":["alex"]`, `"isCustom":true`.
4. Run it through the pipeline:
   ```
   VISION_LABELS=alex python -m pi_pipeline.vision serial /dev/cu.usbmodem58FA1045341
   ```
   Point it at yourself → `alex` boxes with a score; nothing on an empty room.
   0 detections = the dataset was too weak (dark / too few / one condition) —
   recapture better and retrain. It's cheap and repeatable.

---

## 8 · Wire into G2

`.env` (gitignored):
```
VISION_LABELS=person,alex            # in the model's class-id order
G2_BONDS=alex:1.0:affectionate       # name:closeness:disposition[:kind]
```
Now `Bonds` returns a real disposition for `alex`; before training, an
unrecognised person defaulted to `curious`.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Resource busy" opening the serial port | SenseCraft/Chrome tab still holds WebSerial — **close the tab** (or unplug/replug USB). |
| Few pre-labels (`raw pos` low in curate) | Feed is sideways → Person Detection misses you. **Rotate the camera 90°** (step 2). Also: far / backlit / heavy-occlusion poses just won't get a person box — hand-label those. |
| Curated images upside-down / sideways | Wrong `--rotate` — try 90 / 180 / 270; the contact sheet shows it. |
| Dark / grainy frames | `G2_CAM_RES=1` + the AE lift are on by default in `camera_preview.py`; graininess past that is **low light** — add lamps. Longer exposure (brighter) trades against motion blur — hold still on poses. |
| Only a handful of positives after curate | De-dup was collapsing distinct poses (fixed: consecutive-only). If still low, it's genuinely a capture-coverage problem — capture more easy (close/mid straight-on) frames. |
| Trained model detects nothing | Dataset below the floor — dark, too few (<~40 varied), one lighting/background. Recapture in daylight, 3 varied sessions, retrain. |
| Model flashes + runs (`inference: ~90ms` in Device Logger) but `boxes:[]` on every frame, any threshold | **Wrong architecture.** GV2 firmware only decodes the **Swift-YOLO** head. A standard Ultralytics YOLOv8 export runs but its detection tensor is unreadable → permanent empty boxes. Must train/export via SSCMA. See `vision/capture-progress.md` 2026-09-09 note. |
| Model confuses two people | Coarse at 192 px — more data per person, or move to face-embedding recognition (`vision/person-recognition.md` "upgrade path"). |

## What lives where

- Capture routine → `vision/capture-checklist.md`
- This end-to-end → here
- Why recognition + the "G2, meet X" enrollment concept → `vision/person-recognition.md`
- One-model-slot / multi-model architecture → `vision/detection-layer.md`
- Measured module numbers, the AE-lift finding → `vision/detector-bench.md`
- `tools/curate_captures.py --help` for all curate flags
