# Multi-class detection model — capture progress + library

First multi-class model: **5 classes — `<you>`, `<spouse>`, `dog`, `cat`,
`ledge`** (`ledge` last, after the camera is mounted on G2). The two
person-classes are **individual recognition** — box your pictures as one label,
your spouse's as another, so the model tells you apart. `dog`/`cat` are the
species. `ledge` is your specific desk edge(s).

> **Privacy:** the two person-class names are family identifiers → they live
> only in the gitignored `.env` (`VISION_LABELS`, `G2_BONDS`) and the
> Desktop library. This doc uses `<you>` / `<spouse>` as placeholders; the
> commands take the real names as arguments.

The point of the workflow below is a **persistent library**: every retrain just
re-uploads the library plus whatever's new. Companion docs:
`train-a-visual-model.md` (end-to-end), `detection-layer.md` (one-model
constraint), `capture-session-checklist.md` (per-session routine).

---

## Two folders on the Desktop

```
~/Desktop/g2_capture_raw/            DISPOSABLE — raw frames + curate output
  person/session_1/ *.jpg *.json                 (raw capture)
  person/session_1/curated/ pos_*.jpg pos_*.txt neg_*.jpg _contact_sheet.png
  dog/session_1/ ...
  ...

~/Desktop/g2_vision_library/         KEEP — only curated, labelled, upload-ready
  <you>/    <you>_0001.jpg <you>_0001.txt ...
  <spouse>/ ...
  dog/      dog_0001.jpg ...
  cat/      ...
  ledge/    ...
  _negatives/  neg_0001.jpg ...
  _manifest.json   _MANIFEST.md      (running per-class counts, updated on promote)
  upload_*/                          (rebuilt on demand by combine_for_upload.py)
```

`g2_capture_raw/` can be deleted any time once its sessions are promoted. The
library is the asset — back it up.

---

## Per-class targets

| id | class | target | difficulty | pre-label base | notes |
|---|---|---|---|---|---|
| 0 | `<you>` | ~100–150 | fine-grained (individual recognition) | Person Detection → auto boxes | close/mid/far, stand/crouch/walk; 2–3 rooms, varied light; different clothes/hair across sessions so it keys on *you*, not an outfit. The **calibration class**. |
| 1 | `<spouse>` | ~100–150 | fine-grained | Person Detection → auto boxes | same routine, separate sessions. |
| 2 | `dog` | ~120–150 | coarse, poor cooperation | COCO-80 model → boxes on frames it catches; hand-label rest | burst-capture during normal activity, many short sessions, low yield each. |
| 3 | `cat` | ~120–150 | coarse, poor cooperation | COCO-80 model → boxes; hand-label rest | same. |
| 4 | `ledge` | ~200–250 | fine-grained | none — hand-box every frame (Roboflow faster for bulk) | **your specific edges**, every approach angle, 15–40 cm out, lamp on/off, clear vs. cluttered. **Do this after the G2 mount** — most POV-sensitive class. |
| — | negatives | ~40–50 | — | — | empty floor, plain walls, non-target edges (rug borders, grout) so `ledge` doesn't fire on any line; other people / portraits / coat racks so `<you>`/`<spouse>` don't fire on strangers. |

**Individual recognition is coarse at 192 px** — two people who look similar
(size, hair) will get confused. If that happens, the fix is the face-embedding
path in `detection-layer.md` (detect `face`, match on the Pi), not more images.
Vary clothes/hair/lighting across capture sessions so the model doesn't latch
onto an outfit.

**`ledge` is ~2× the pet count:** recognising *this* edge (not "a line") is
fine-grained — the overfitting problem the first single-class face model hit
(~200+ images in practice). Pets lean on the pretrained backbone, so lower.

**Splitting `dog` + `cat`** doubles the hardest capture for the same behaviour
("a pet is nearby") — kept separate only for distinct per-pet reactions later.
Merge to one `animal` class if that stops mattering.

**Class-id order is append-only** and set by the `--classes` argument, not by
folders. `combine_for_upload.py` rewrites every label's id from that order, so
the library stays reorder-safe; add a class later and it just appends.

---

## POV rule (every class)

Capture from **G2's mounted-camera POV — ~8–10 cm off the floor, slight upward
tilt.** A shoe from standing height ≠ a shoe from shin height; the model won't
transfer. Camera not on the body yet → hand-hold at that height/angle for the
people + pets now; plan a top-up pass once mounted. `ledge` waits for the mount.

---

## The loop (per class, per session)

```bash
source pi_pipeline/.venv/bin/activate
CLASS=<you>; K=1                           # <-- the class name + session number
RAW=~/Desktop/g2_capture_raw/$CLASS/session_$K
LIB=~/Desktop/g2_vision_library

# 1. capture
export G2_CAP_OUT=$RAW G2_CAP_LABEL=$CLASS G2_CAM_RES=1
mkdir -p "$RAW"; rm -f "$RAW"/*.jpg "$RAW"/*.json
python tools/camera_preview.py & open http://localhost:8080
#   ... pose set — see capture-session-checklist.md ...
pkill -f camera_preview.py

# 2. curate  (--class-id is a placeholder; combine rewrites it from --classes order)
python tools/curate_captures.py "$RAW" "$RAW/curated" \
    --positives 200 --negatives 15 --class-id 0 --rotate 0 --target 130

# 3. review $RAW/curated/_contact_sheet.png — upright? poses varied? boxes sane?
#    fix any bad rotation with a different --rotate and re-run step 2.

# 4. promote the good set into the library
python tools/promote_to_library.py "$RAW/curated" --library "$LIB" --class $CLASS
```

Repeat for every class / session. When ready to (re)train — **pass the class
list in a fixed order, that's your class-id order and your `VISION_LABELS`**:

```bash
python tools/combine_for_upload.py ~/Desktop/g2_vision_library \
    --classes <you>,<spouse>,dog,cat,ledge
#   -> ~/Desktop/g2_vision_library/upload/   — import THIS into a SenseCraft
#      multi-class Object Detection project (walkthrough §6)
```

`.env` on deploy (real names here — this file is gitignored):
```
VISION_LABELS=<you>,<spouse>,dog,cat,ledge      # same order as --classes
G2_BONDS=<you>:1.0:affectionate, <spouse>:1.0:affectionate, dog:0.7:playful, cat:0.6:curious
G2_FEATURES="+vision"
```

---

## Progress log

Read the counts off `~/Desktop/g2_vision_library/_MANIFEST.md` after each promote.

| date | class | session | promoted pos | promoted neg | library total (class) | notes |
|---|---|---|---|---|---|---|
| 2026-09-09 | `<you>` | 1–3 | 238 | 10 | 238 | re-curated from the earlier single-class face set |
| | | | | | | |

**Calibration checkpoint (`<you>`).** Runs as a **single-class** model (only one
person captured so far). Subsets pre-built (jpg only — `--images-only`, so
SenseCraft auto-label isn't cluttered):
`~/Desktop/g2_vision_library/upload_{40,80,120,160,all}` — N person images +
~N/4 background negatives (spread-sampled from `_negatives/`). Import each into
its own SenseCraft project, **auto-label**, deselect the `negative_*` images,
train, deploy, then measure — **in a room none of the training images came
from**:

```
g2visioneval <label> 30            # stand at close / mid / far, ~30 s
g2visioneval <label> 30 empty      # point at a clear scene -- false-fire check
```

`pi_pipeline.vision eval` forces score floor 0 (see every score) and prints
detection rate, confidence mean/median/**p10 (the floor)**, flicker, and a
VERDICT against the bar (det ≥ 80%, conf floor ≥ `VISION_MIN_SCORE` = 45).

**Stop rule:** the smallest subset that (a) clears the bar AND (b) the next size
up doesn't beat by ≥ 5 pts detection or ≥ 8 pts floor. If even `upload_all`
(238) fails the bar → it's a data-quality problem, not a count one.

| subset | det rate | conf mean | conf p10 (floor) | flicker /min | verdict |
|---|---|---|---|---|---|
| 40 | 0% | — | — | 0 | **FAIL** — 0/462 frames, incl. point-blank; camera_preview hit-rate 0% too. Same images trained a working single-class model earlier at ~161, so it's a convergence-floor thing: 40 is too few for the nano detector. (SenseCraft auto-label: 43 labelled / 9 unlabelled — 3 negatives got a spurious box for the class.) |
| 80 | | | | | |
| 120 | | | | | |
| 160 | | | | | |
| 238 (all) | | | | | |

| empty-scene run | false-fire rate | worst score | verdict |
|---|---|---|---|
| (best subset) | | | |
