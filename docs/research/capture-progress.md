# Multi-class detection model — capture progress + library

First multi-class model: **4 classes — `person`, `dog`, `cat`, `ledge`**
(`ledge` last, after the camera is mounted on G2). No individual recognition —
`person` is generic; `dog`/`cat` are the species, not named pets.

The point of the workflow below is a **persistent library**: every retrain just
re-uploads the library plus whatever's new. Companion docs:
`train-a-visual-model.md` (end-to-end), `detection-layer.md` (one-model
constraint), `capture-session-checklist.md` (per-session routine).

> Class names are generic on purpose — nothing identifying goes in tracked
> files. Real tags / bonds live only in the gitignored `.env`
> (`VISION_LABELS=person,dog,cat,ledge`, `G2_BONDS=…`).

---

## Two folders on the Desktop

```
~/Desktop/g2_capture_raw/            DISPOSABLE — raw frames + curate output
  person/session_1/ *.jpg *.json                 (raw capture)
  person/session_1/curated/ pos_*.jpg pos_*.txt neg_*.jpg _contact_sheet.png
  dog/session_1/ ...
  ...

~/Desktop/g2_vision_library/         KEEP — only curated, labelled, upload-ready
  person/  person_0001.jpg person_0001.txt ...
  dog/     dog_0001.jpg ...
  cat/     ...
  ledge/   ...
  _negatives/  neg_0001.jpg ...
  _manifest.json   _MANIFEST.md      (running per-class counts, updated on promote)
  upload/                            (rebuilt on demand by combine_for_upload.py)
```

`g2_capture_raw/` can be deleted any time once its sessions are promoted. The
library is the asset — back it up.

---

## Per-class targets

| id | class | target | difficulty | pre-label base | notes |
|---|---|---|---|---|---|
| 0 | `person` | ~100–120 | coarse | Person Detection → auto boxes | you + spouse; close/mid/far, stand/crouch/walk; 2–3 rooms, varied light. Also the **calibration class**. |
| 1 | `dog` | ~120–150 | coarse, poor cooperation | COCO-80 model → boxes on frames it catches; hand-label rest | burst-capture during normal activity, many short sessions, low yield each. |
| 2 | `cat` | ~120–150 | coarse, poor cooperation | COCO-80 model → boxes; hand-label rest | same. |
| 3 | `ledge` | ~200–250 | fine-grained (like the first face model) | none — hand-box every frame (Roboflow faster for bulk) | **your specific edges**, every approach angle, 15–40 cm out, lamp on/off, clear vs. cluttered. **Do this after the G2 mount** — most POV-sensitive class. |
| — | negatives | ~40–50 | — | — | empty floor, plain walls, non-target edges (rug borders, grout) so `ledge` doesn't fire on any line. |

**Why `ledge` is ~2× the others:** recognising *this* edge (not "a line") is
fine-grained — the overfitting problem the first single-class face model hit
(~200+ images in practice). `person` / `dog` / `cat` lean on pretrained
backbones and can be seeded with public images, so they plateau lower.

**Splitting `dog` + `cat`** doubles the hardest capture for the same behaviour
("a pet is nearby") — kept separate here only because the plan wants distinct
per-pet reactions later. If that stops mattering, merge to one `animal` class.

**Class-id order is append-only.** `person,dog,cat,ledge` = ids 0–3. Add a class
later → it's id 4, existing ids don't move. `combine_for_upload.py` rewrites each
label's id from the `--classes` order, so the library itself stays reorder-safe.

---

## POV rule (every class)

Capture from **G2's mounted-camera POV — ~8–10 cm off the floor, slight upward
tilt.** A shoe from standing height ≠ a shoe from shin height; the model won't
transfer. Camera not on the body yet → hand-hold at that height/angle for
`person` / `dog` / `cat` now; plan a top-up pass once mounted. `ledge` waits for
the mount.

---

## The loop (per class, per session)

```bash
source pi_pipeline/.venv/bin/activate
CLASS=person; K=1                          # <-- set these
RAW=~/Desktop/g2_capture_raw/$CLASS/session_$K
LIB=~/Desktop/g2_vision_library

# 1. capture
export G2_CAP_OUT=$RAW G2_CAP_LABEL=$CLASS G2_CAM_RES=1
mkdir -p "$RAW"; rm -f "$RAW"/*.jpg "$RAW"/*.json
python tools/camera_preview.py & open http://localhost:8080
#   ... pose set — see capture-session-checklist.md ...
pkill -f camera_preview.py

# 2. curate  (--target per the table; --class-id matches the id column)
python tools/curate_captures.py "$RAW" "$RAW/curated" \
    --positives 150 --negatives 15 --class-id 0 --rotate 0 --target 120

# 3. review $RAW/curated/_contact_sheet.png — upright? poses varied? boxes sane?
#    fix any bad rotation with a different --rotate and re-run step 2.

# 4. promote the good set into the library
python tools/promote_to_library.py "$RAW/curated" --library "$LIB" --class $CLASS
#    -> updates _MANIFEST.md with the new running counts
```

Repeat for every class / session. When ready to (re)train:

```bash
python tools/combine_for_upload.py ~/Desktop/g2_vision_library \
    --classes person,dog,cat,ledge
#   -> ~/Desktop/g2_vision_library/upload/   — import THIS into a SenseCraft
#      multi-class Object Detection project (walkthrough §6)
```

`.env` on deploy (and flip the nav stack on at the same time):
```
VISION_LABELS=person,dog,cat,ledge
G2_BONDS=person:0.5:curious, dog:0.7:playful, cat:0.6:curious
G2_FEATURES="+vision"
```

---

## Progress log

Read the counts off `~/Desktop/g2_vision_library/_MANIFEST.md` after each promote.

| date | class | session | promoted pos | promoted neg | library total (class) | notes |
|---|---|---|---|---|---|---|
| _pending_ | person | 1 | — | — | — | first session + calibration set |
| | | | | | | |

**Calibration checkpoint (`person`, after ~120 in the library):** train
SenseCraft quick models on 40 / 80 / 120 subsets, run each through
`python -m pi_pipeline.vision serial <port>`, record detection rate / confidence
/ flicker. Plateau = the real per-coarse-class budget → adjust the `dog`/`cat`
targets, and confirm capture quality is good enough this round.

| subset | detection rate | mean conf | flicker | verdict |
|---|---|---|---|---|
| 40 | | | | |
| 80 | | | | |
| 120 | | | | |
