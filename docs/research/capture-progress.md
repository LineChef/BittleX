# Multi-class detection model — capture progress

The first multi-class model: **3 classes — `person`, `animal`, `ledge`.**
A general-awareness model (living things + one hazard), **no individual
recognition** (`animal` not dog/cat by name, `person` not by name — coarser
classes are easier on a 192 px nano detector). Companion docs:
`train-a-visual-model.md` (the end-to-end flow), `detection-layer.md` (why one
model, the swap constraint), `capture-session-checklist.md` (the per-session
routine).

> Class names are generic on purpose — nothing identifying goes in tracked files.
> Real tags / bonds live only in the gitignored `.env`
> (`VISION_LABELS=person,animal,ledge`, `G2_BONDS=…`).

---

## Per-class targets

| id | class | target positives | difficulty | pre-label base | notes |
|---|---|---|---|---|---|
| 0 | `person` | **~100–120** | coarse | Person Detection → auto boxes | you + spouse; close/mid/far, stand/crouch/walk; 2–3 rooms, varied light. Also the **calibration class** (train 40/80/120 subsets, find the plateau). |
| 1 | `animal` | **~120–150** | coarse, 2 sub-types | COCO-80 model → boxes for frames it catches; hand-label the rest | dog + cat; burst-capture during normal activity, many short sessions, low yield each. |
| 2 | `ledge` | **~200–250** | fine-grained (like the first face model) | none — hand-box every frame (Roboflow is faster for bulk) | **specific edges** (desk edge, etc.), every approach angle, 15–40 cm out, lamp on/off, clear vs. cluttered. **Capture after the camera is mounted on G2** — most POV-sensitive class. |
| — | negatives | ~30–40 | — | — | empty floor, plain walls, non-target edges (rug borders, grout) so `ledge` doesn't fire on any line. |

**Why `ledge` is 2× the others:** recognising *this* edge (not "a line") is
fine-grained, the same overfitting problem the first single-class face model
hit (~200+ images in practice). `person` / `animal` lean on pretrained backbones and can
be seeded with public images, so they plateau lower.

**Multi-class balance:** the trainer weights by class frequency. If `ledge` ends
up at 250 and `person` at 100, the model tilts toward `ledge`. Either roughly
balance the final counts, oversample the smaller class at import, or accept the
tilt (defensible for a hazard class).

---

## POV rule (applies to every class)

Capture from **G2's mounted-camera POV — ~8–10 cm off the floor, slight upward
tilt.** A shoe from standing height ≠ a shoe from shin height; the model won't
transfer. If the camera isn't on the body yet: hand-hold at that height/angle for
`person` / `animal` now, and plan a top-up pass once mounted. Do `ledge` only
after the mount.

---

## Progress log

Update after each `curate_captures.py` run (it prints the running total; use
`--target` per the table above so the tally reports against the right goal).

| date | class | session | usable pos | usable neg | class total | notes |
|---|---|---|---|---|---|---|
| _pending_ | person | 1 | — | — | — | first session + calibration set |
| | | | | | | |

**Calibration checkpoint (`person`):** after ~120 usable, train SenseCraft quick
models on 40 / 80 / 120 subsets, run each through
`python -m pi_pipeline.vision serial <port>`, record detection rate / confidence
/ flicker. Plateau point = the real per-coarse-class budget → adjust `animal`
target, and gauge whether capture quality is good enough this round.

| subset | detection rate | mean conf | flicker | verdict |
|---|---|---|---|---|
| 40 | | | | |
| 80 | | | | |
| 120 | | | | |

---

## Workflow (per class, per session)

```bash
source pi_pipeline/.venv/bin/activate
export G2_CAP_OUT=~/Desktop/g2_capture/<class>/session_<k>
export G2_CAP_LABEL=<class> G2_CAM_RES=1
mkdir -p "$G2_CAP_OUT"; rm -f "$G2_CAP_OUT"/*.jpg "$G2_CAP_OUT"/*.json
python tools/camera_preview.py & open http://localhost:8080
#   ... capture (see capture-session-checklist.md) ...
pkill -f camera_preview.py

python tools/curate_captures.py "$G2_CAP_OUT" "$G2_CAP_OUT/curated" \
    --positives <target> --negatives 15 --class-id <id> --rotate 0 --target <goal>
```

When all classes/sessions are curated:

```bash
python tools/combine_for_upload.py ~/Desktop/g2_capture --classes person,animal,ledge
#   -> ~/Desktop/g2_capture/upload/   (import into a SenseCraft multi-class
#      Object Detection project — walkthrough §6)
```

`.env` on deploy:
```
VISION_LABELS=person,animal,ledge
G2_BONDS=person:0.5:curious, animal:0.7:playful
```
Re-enable the vision-navigation stack at the same time: `G2_FEATURES="+vision"`
(it's held off by default until a real detector exists — see
`detection-layer.md`).
