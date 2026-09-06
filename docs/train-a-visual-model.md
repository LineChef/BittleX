# Train a visual model for G2 — full walkthrough

Every step and command to go from "nothing" to "a custom detection model running
on the Grove Vision AI V2", so you can do it solo. Written for a face/person
recognition model (`alex`), but the same flow trains any object model.

Related: `research/capture-session-checklist.md` (the capture routine),
`research/person-recognition.md` (design + the enrollment concept),
`research/detection-layer.md` (multi-model architecture),
`research/vision-detector-bench.md` (measured module behaviour).

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

Full detail incl. the **standard pose set** (run it every session): `research/capture-session-checklist.md`. Short form:

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
4. Pose sequence — Start/Stop between changes, hold ~6–8 s each:
   - **distance:** close (~1.5 ft) → mid (~3 ft) → far (~5–6 ft), straight on
   - **head:** slow full turn L↔R; chin up; chin down; look away L/R/up
   - **expression:** talking, smile, neutral, surprised
   - **occlusion:** hand near face, push hair back
   - **second spot / light:** repeat close + mid
   - Aim for **~90–120 saved**, then ~12 s **negatives** (step out of frame).
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
  de-dups only *consecutive* near-identical frames, spread-samples across the
  timeline, rotates upright, writes a **YOLO `.txt` per positive** from the
  detection box (`--label-region face` tightens it toward the face; the *image*
  stays full-frame — never crop training images for a detector).
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

## 5 · Combine sessions

When all 3 `session_*/curated/` exist, gather them:
```
mkdir -p ~/Desktop/g2_face_capture/alex/upload
cp ~/Desktop/g2_face_capture/alex/session_*/curated/pos_*.jpg \
   ~/Desktop/g2_face_capture/alex/session_*/curated/pos_*.txt \
   ~/Desktop/g2_face_capture/alex/session_*/curated/neg_*.jpg \
   ~/Desktop/g2_face_capture/alex/upload/
```
(Filenames collide across sessions — rename per session first, or copy into
per-session subdirs the importer can walk.)

---

## 6 · Train in SenseCraft

1. **Models → Training → Image Object Detection** tab → **Image Collection
   Training** (NOT "Quick Training" — that has no upload).
2. **Step 1** — object name: `alex`.
3. **Step 2** — skip the "Connect" (that's live capture; you have files).
4. **Step 3** — **Import Dataset** → your `upload/` folder. The `.txt` files are
   YOLO pre-labels; images land under **Labeled** with boxes drawn.
   - Review each box; tighten to the face if needed. Assign class `alex`.
   - Unlabeled (no-box) frames: box them by hand, or delete.
   - Negatives: leave unlabeled. Delete any that actually show you.
   - Need ≥10 labeled; aim for all ~100+.
5. **Step 4** — target device **Grove Vision AI V2** → **Start Training**
   (~10–30 min, cloud).

**Multi-class model** (`person` + `alex` + household + pets): add each person as
its own class in the same project, and include a batch of generic-person images
for the `person` class — see `research/person-recognition.md`.

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
| Model confuses two people | Coarse at 192 px — more data per person, or move to face-embedding recognition (`research/person-recognition.md` "upgrade path"). |

## What lives where

- Capture routine → `research/capture-session-checklist.md`
- This end-to-end → here
- Why recognition + the "G2, meet X" enrollment concept → `research/person-recognition.md`
- One-model-slot / multi-model architecture → `research/detection-layer.md`
- Measured module numbers, the AE-lift finding → `research/vision-detector-bench.md`
- `tools/curate_captures.py --help` for all curate flags
