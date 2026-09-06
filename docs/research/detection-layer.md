# Vision detection layer — plan

How G2 gets useful perception out of the Grove Vision AI V2 given its hard
constraint, and how to build it up over time. Companion doc:
[`person-recognition.md`](person-recognition.md).

Status 2026-09-06: person-detection model deployed + validated end-to-end; the
`pi_pipeline/vision/` consumers (`SerialDetectionFeed`, `Avoider`, `scene`,
`terrain_feature`) are built and mock-tested; the multi-model management below is
**not built**.

---

## The hard constraint

**The module runs exactly one model at a time. No concurrent inference.**
Confirmed on hardware 2026-09-06: `AT+MODELS?` returns a single slot; switching
models is a **full reflash (~1–2 min)** on this firmware (`software 2025.01.02`).
`AT+MODEL=<id>` + restart-inference is ~0.5 s but that re-selects the *same*
model, not a different one. Whether a genuine multi-slot exists is untested —
re-check once a second model has ever been flashed; assume single-slot.

Everything below works around this: either **one combined model** whose class
list spans domains, or **multiple specialized models swapped by mode**.

Measured detector behaviour (feeds the sim noise model, and sets expectations):
[`vision-detector-bench.md`](vision-detector-bench.md) — ~15 fps, 48–50 ms fixed
inference, ~17 % whole-detection dropout while a target is present, confidence
sits near the threshold, box-size jitter ~8 % of frame (so distance-from-area is
noisy), 0 false positives on a clean scene, 240 px frame, centre-format boxes.

---

## Option A — one combined model

Classes from several domains in a single model: `person`, `dad`, `mom`, `dog`,
`mug`, `keyboard`, … all scored every frame.

- **Pro:** everything available simultaneously; no swap logic.
- **Con:** shared capacity — realistically **~10–20 classes** before per-class
  accuracy on a 192–240 px nano detector degrades badly. Adding any class means
  retraining the whole model. Mixing a safety class (`edge`) with recognition
  classes is architecturally wrong: different cadence, different
  false-positive bias, different retraining cycles.

## Option B — specialized models, swapped by mode

- **Pro:** each model tuned for its job; small and fast.
- **Con:** ~1–2 min swap → **mode-gated, not reactive**; needs a model-manager.

---

## Recommended architecture

Three models, selected by `ModeController`:

| Model | Loaded when | Classes | Notes |
|---|---|---|---|
| **safety** | G2 moving autonomously (EXPLORE, any commanded walk) | `edge` / `dropoff` / `obstacle` | small, fast, **biased hard to false-positives**; never diluted with other classes. This is B16 `CliffGuard` + obstacle. |
| **interaction** | CONVERSE, idle, stationary-with-person | `person` + household individuals + pets | this is B15. See `person-recognition.md`. |
| **objects/scene** | on demand — "what's on my desk / in this room" | COCO-80, or a curated subset | mostly free (pretrained COCO). Lowest priority. |

If swap latency proves annoying in practice, **fold a few key objects
(`mug`, `phone`, `ball`) into the interaction model** and keep only `safety`
separate. Safety must stay its own model regardless.

### Model-manager (not built)

A thin `pi_pipeline/vision/model_manager.py`:

- `ensure(model_name)` — no-op if already loaded; else reflash + wait for
  `AT+MODEL?` / first INVOKE, ~1–2 min. Emits a `diag` event.
- Called by the mode controller on mode transitions (EXPLORE → load `safety`;
  CONVERSE → load `interaction`; explicit "look around" → load `objects`).
- Guards: don't swap while `avoidance_act` is mid-manoeuvre; don't swap more
  than once per N seconds (thrash guard).
- Config: `VISION_MODELS` in `.env` mapping name → SenseCraft model id / local
  `.tflite`; wire behind the `features.py` flags (`vision_safety`,
  `vision_perception`).
- Startup: load the model for the initial mode; log which.

### Swap mechanics (from the bench)

- SenseCraft "Deploy to device" is the flash path today (WebSerial, hands-on).
  A headless flash from the Pi needs the SSCMA/`AT`-level model-write protocol
  (XModem-style) — **research task**: confirm the exact command sequence and
  whether the `.tflite` can be pushed over `/dev/ttyACM0` without SenseCraft.
- Until headless flashing works, model-swap-by-mode is blocked; interim = ship
  one model (the interaction model) and defer swapping.

---

## Do this first — dataset-quality threshold experiment

The 2026-09-06 practice run only proved "37 dark frames = far below the floor."
Before committing effort per person/class, find the floor:

1. Capture **one good, varied daylight set** (~120 images) of a single subject.
2. Train on the full set; then on random subsets of **20 / 40 / 80**.
3. Test each through `pi_pipeline.vision serial` — detection rate, confidence,
   flicker, at a few distances/angles.
4. Output: "~N well-lit varied images per class → reliable detection." That's
   the per-class cost estimate for the whole household / object list.

Capture tooling exists: `scratchpad/face_preview.py` (live preview + detection
overlay + a capture button, pulls JPEGs over serial via `AT+INVOKE=-1,0,0`).

---

## Build order

1. **Dataset-quality experiment** (above) — cheap, unblocks all estimates.
2. **Interaction model** (B15) — core to personality/bonds/memory; see
   `person-recognition.md`.
3. **Headless-flash research** — required before any model-swapping.
4. **Model-manager** — once headless flash works.
5. **Safety model** (B16) — gated on camera-mounted-on-frame (POV-specific
   training data); highest priority the moment the body exists.
6. **Objects model** — COCO-80 deploy, lowest effort; wire `scene.narrate`.

Priority if forced to choose: **safety > recognition > objects.**

---

## Consumers (mostly built)

| Consumer | Uses | State |
|---|---|---|
| `vision/feed.py` `SerialDetectionFeed` | parses INVOKE → `Detection` | built; auto-starts inference; `VISION_LABELS` names classes |
| `vision/avoidance.py` `Avoider` | box area → closeness, `center_x` → bearing | built; thresholds need real-detection + stopping-distance calibration |
| `vision/scene.py` | detections → text → Claude narration | built |
| `vision/terrain_feature.py` | box → (dist, bearing, tall_flag) for the gait obs | built; `fov_scale` / `s_near` / `s_far` / `h_tall` need mounted-camera calibration |
| `personality/bonds.py` | detection label → disposition / closeness | built (API only) |
| `memory` + B11 place memory | accumulate "kitchen has a table", "dog near couch" | memory built; place-graph not |

---

## Open questions

- Headless `.tflite` flash from the Pi over serial — command sequence?
- Real multi-slot on this firmware, or always single?
- `frame_px`: model runs 192 but reports in the 240 frame — confirm this holds
  for a custom multi-class model too (it held for the stock person + gesture).
- Model-swap time budget vs. mode-transition frequency — is 1–2 min acceptable,
  or does it force the "one combined companion model" route?
- Objects model: full COCO-80 vs. a curated ~15-class subset for accuracy.
