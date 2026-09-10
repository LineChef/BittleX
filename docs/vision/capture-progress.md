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
`guides/train-vision-model.md` (end-to-end), `detection-layer.md` (one-model
constraint), `capture-session-checklist.md` (per-session routine).

---

## ✅ 2026-09-09 — SOLVED: `ultralytics==8.2.8`, exported locally on Apple Silicon

A 3-class (`<you>`/`dog`/`cat`) YOLOv8n now decodes on the device — clean single
boxes, quiet on an empty scene, mAP@50 0.907. The fix was the frozen-firmware
toolchain match below **plus** running `yolo export format=tflite int8` on
**arm64 Python 3.9** (Colab's py3.13 can train 8.2.8 but can't export it —
onnx2tf `flatbuffer_direct` bug). Full recipe + the 3 mandatory workarounds:
**`grove-vision-v2-custom-model.md` → "The working recipe"**, and its
**"Cleanup"** step (delete the Colab runtime so the uploaded photos are wiped)
is now a permanent last step of every build.

**Known limitation of this first model:** detects only up close, and the box is
frozen near the training-average position — under-calibrated INT8 (100 calib
images; recipe wants 300+) and a thin/close-framed `<you>` set. Fix = a `<you>`
capture pass for distance + position variety, then re-export.

### How we got here (the diagnosis)

The device firmware (`SSCMA-Micro`, latest release `20250102`) does the
post-processing (anchor decode / objectness gate / NMS) around the flashed
`.tflite`, so the model's output **head must match its decoder**. That decoder
is frozen at Jan 2025; every training toolchain drifted forward since.

- `boxes:[]` forever → head unrecognised (we hit this with `ultralytics==8.4.146`
  — its LiteRT export ≠ the 8.2.8 graph the firmware knows).
- **box flood**, 10-30/frame on an anchor grid, `postprocess:0ms`, sliders inert
  → firmware dumping raw anchors, no NMS (we hit this with SSCMA `main`-branch
  Swift-YOLO — both a junk-box model AND a real-box mAP@50 0.87 model flooded
  *identically*, proving it's the export head not the data).

**Decodes on `20250102`:** SSCMA `2.0.0`-branch Swift-YOLO, Ultralytics YOLOv8
via **`ultralytics==8.2.8`** (Seeed's official `ma_deploy_yolov8` recipe),
YOLO11. **Does not:** YOLO26, RTMDet, SSCMA `main` re-implemented Swift-YOLO.

**Path that worked:** Ultralytics YOLOv8 pinned **`ultralytics==8.2.8`** — no
mmcv, multi-class native, plain YOLO-format dataset (no COCO conversion),
exported locally on arm64 py3.9. SSCMA path dropped. Edge Impulse FOMO stays on
the shelf as a fallback (compiles its own firmware `.uf2`, immune to this class
of problem; gives centroids not boxes) — not needed.

**Still correct regardless of toolchain:** `*_int8_vela.tflite` format, WE2 vela
config (`ethos-u55-64`, `const_mem_area=Axi1`, `arena/cache=Axi0`), 192×192
square input ≤240, model ≤2 MB. SenseCraft "Object" list = class-id order
`0:<you> 1:dog 2:cat`; each chip needs **Add Object → type → Add Object again**.
SenseCraft "Send" needs a live token — if the console logs
`[FleetEvents WS] global skip connect: no token`, hard-reload after sign-in.
Or skip SenseCraft: local serial flash with `python-sscma`
(`sscma.cli flasher m.tflite 0x400000` + `AT+INFO="<b64 json>"`).

**Data was re-labelled** (`tools/autobox_coco.py` — dog/cat had no boxes,
training used whole-frame fallback → position-prior overfit): `<you>` 230,
`cat` 218, `dog` 127 (dog session motion-blurred, wants a recapture).
`tools/vision_diag.py <port>` judges a flashed model headless (flags "PLANTED"
box locations = overfit/garbage).

**Device state:** holds the working 3-class model (`g2_3class_yolov8_828_vela.tflite`).
SenseCraft **web** training is single-class only — no multi-class web path.

---

## Diagnostic logging pass — do this BEFORE the next capture round

The working model detects all 3 classes but: `<you>` up close only, box frozen
near the training-average position; `cat` lost to `dog` once at a rear/ambiguous
angle. Rather than just capturing *more*, log structured sessions against known
ground truth first, so the next capture pass targets the actual gaps.

**How:** `python tools/vision_diag.py <port> --secs 60` per session (it parses
the Device Logger stream headless: score-floor + NMS + top-K, flags "PLANTED"
box locations). Narrate or script the ground truth; fill the table after.

| session | what to do | reading to record |
|---|---|---|
| `<you>` distance sweep | walk 3ft → 6ft → 10ft → back, slowly, centre of frame | score at each distance; the distance where it drops below ~50 or stops firing |
| `<you>` position sweep | stand left / centre / right / half-out-of-frame at ~5ft | does the box track, or stay frozen? score per position |
| `cat` pose sweep | facing toward / away / curled / low light, mid-distance | score; every frame the class flips to `dog` (note the pose) |
| `dog` pose sweep | same poses | score; flips to `cat`; false-negatives (no box on a clearly-visible dog) |
| empty room | 60s, nobody/no pet in frame | any box at all = a false positive → that scene becomes a negative |
| post-retrain re-run | repeat the above on the new model | box coords tracking (not frozen) = localization fixed; score deltas per cell |

**Shot list (fill from the readings above):**

| class | weak condition found | capture target |
|---|---|---|
| `<you>` | _(e.g. "no detect past 6ft")_ | _(e.g. "40 frames at 6–12ft, walking")_ |
| `cat` | _(e.g. "rear-view flips to dog")_ | |
| `dog` | | |

**Independent of the logging:** rebuild the INT8 calibration set to **300+
varied images** (was 100) — highest-probability fix for "up close only", no
diagnosis needed. `tools/gv2/export_yolov8_gv2.sh <best.pt> <calib_dir>` takes
any flat folder of jpgs as `<calib_dir>`.

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
| 2026-09-09 | `dog` | 1 | 120 | — | 120 | daylight session, subject-prominence `--limit 120` |
| 2026-09-09 | `cat` | 1 | 120 | — | 120 | same |
| 2026-09-09 | — | — | — | — | — | Built `custom_data.zip` (`<you>`/dog/cat, YOLO fmt) → trained YOLOv8n in `g2_yolov8_3class.ipynb` (mAP@50 **0.995**) → vela → flashed. **Dead on device** (thought Swift-YOLO required — wrong; see below). |
| 2026-09-09 | — | — | — | — | — | Re-labelled dog/cat with `autobox_coco.py` (`<you>` 230, cat 218, dog 127), rebuilt `custom_data_yolo_v3.zip` (nc:3, 224px), retrained YOLOv8n (mAP@50 **0.907**). **Exported locally on arm64 py3.9** (`ultralytics==8.2.8` + onnx2tf 1.17.5, 3 workarounds) → vela 100% NPU → `g2_3class_yolov8_828_vela.tflite` (2.31 MB). **WORKS on device** — clean single boxes. Detects up close only (100-image INT8 calib; box frozen near training-avg position). |

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
| 80 (eff. ~75) | 0% (1/384) | 79 | 79 | 2.4 | **FAIL** — fired once at conf 79, then nothing. High precision, ~zero recall — underfit. |
| 120 (eff. ~118) | **100%** (461/461) | 91 | 84 | 0 | **PASS** — maxed out: 100% detection, floor 84 (≈2× the bar), zero flicker. Tested in a non-training room. |
| 160 | _not run_ | | | | can't beat 100% detection; floor 84 leaves no meaningful headroom |
| 238 (all) | _not run_ | | | | ceiling already known; 120 settles it |

### Result: **~120 images per class**

40 → 0/462, 80 → 1/384, **120 → 461/461**. The curve is a cliff, not a ramp —
near-nothing until ~100, then it snaps to reliable. Budget **~120 (round to
120–130 for margin)** per class for `<you>`, `<spouse>`, and as the starting
target for `dog` / `cat`. `ledge` still gets more (~200–250) — it's the
hardest-to-generalise class.
Auto-label attrition ran ~10–15% (120 uploaded → ~118 trained), so capture
~140 raw per class to land ~120 trained.

> The original single-class face model (~161 of these same images, old weaker
> dedup) worked well — empty room quiet, walk-ins acquired instantly, score
> ~60–80. So the ceiling is known; the experiment is only about **how far down**
> the count can go. Testing the full 238 re-proves the ceiling and wastes a
> cycle unless 120 fails and we need to rule out a pipeline regression.

| empty-scene run | false-fire rate | worst score | verdict |
|---|---|---|---|
| (best subset) | | | |
