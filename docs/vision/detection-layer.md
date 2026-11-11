# Vision detection layer — plan

How G2 gets useful perception out of the Grove Vision AI V2 given its hard
constraint, and how to build it up over time. Companion doc:
[`person-recognition.md`](person-recognition.md).

Status: person-detection model deployed + validated end-to-end; the
`pi_pipeline/vision/` consumers (`SerialDetectionFeed`, `Avoider`, `scene`,
`terrain_feature`) are built and mock-tested; the multi-model management below is
**not built**.

> **Vision navigation is held behind a flag.** The camera currently
> runs a **single-class face model** (one enrolled face), not an
> obstacle/edge/person detector. There is **no sensor that "just sees" things in
> G2's path** — a tiny
> camera + NPU only reports the classes its loaded model was trained on. Every
> vision-driven navigation behaviour built assumes a detector that does not
> exist on the hardware yet, so it is now gated off by the master flag
> **`features.vision`** (default `False`):
> - `resolve()` forces `vision_safety`, `vision_perception`, `avoidance_act` and
>   `explore` off whenever `vision` is off.
> - `BehaviorDriver(vision_available=False)` — no EXPLORE roaming, no recognition
>   hop, no CliffGuard reflex, "G2 meet X" enrollment refused with a spoken line.
> - `run_gait.py --skills` refuses to start without `features.vision` (unless
>   `--dry-run` / `--ignore-features`).
>
> Turn the whole stack back on in one move once a real detector ships:
> `G2_FEATURES="+vision"`. Nothing was deleted — the logic, evals and docs
> stand; they're just not reachable on the body until the sensor is real.

---

The hard constraint
-------------------

**The module runs exactly one model at a time. No concurrent inference.**
Confirmed on hardware: `AT+MODELS?` returns a single slot; switching
models is a **full reflash (~1–2 min)** on this firmware (`software 2025.01.02`).
`AT+MODEL=<id>` + restart-inference is ~0.5 s but that re-selects the *same*
model, not a different one. Whether a genuine multi-slot exists is untested —
re-check once a second model has ever been flashed; assume single-slot.

Everything below works around this: either **one combined model** whose class
list spans domains, or **multiple specialized models swapped by mode**.

Measured detector behaviour (feeds the sim noise model, and sets expectations):
the measured behaviour below — ~15 fps, 48–50 ms fixed
inference, ~17 % whole-detection dropout while a target is present, confidence
sits near the threshold, box-size jitter ~8 % of frame (so distance-from-area is
noisy), 0 false positives on a clean scene, 240 px frame, centre-format boxes.

---

Option A — one combined model
-----------------------------

Classes from several domains in a single model: `person`, `dad`, `mom`, `dog`,
`mug`, `keyboard`, … all scored every frame.

- Pro: everything available simultaneously; no swap logic.
- Con: shared capacity — realistically **~10–20 classes** before per-class
  accuracy on a 192–240 px nano detector degrades badly. Adding any class means
  retraining the whole model. Mixing a safety class (`edge`) with recognition
  classes is architecturally wrong: different cadence, different
  false-positive bias, different retraining cycles.

Option B — specialized models, swapped by mode
----------------------------------------------

- Pro: each model tuned for its job; small and fast.
- Con: ~1–2 min swap → **mode-gated, not reactive**; needs a model-manager.

---

Recommended architecture
------------------------

Three models, selected by `ModeController`:

- safety: Loaded when: G2 moving autonomously (EXPLORE, any commanded walk); Classes: `edge` / `dropoff` / `obstacle`; Notes: small, fast, **biased hard to false-positives**; never diluted with other classes. This is B16 `CliffGuard` + obstacle.
- interaction: Loaded when: CONVERSE, idle, stationary-with-person; Classes: `person` + household individuals + pets; Notes: this is B15. See `person-recognition.md`.
- objects/scene: Loaded when: on demand — "what's on my desk / in this room"; Classes: COCO-80, or a curated subset; Notes: mostly free (pretrained COCO). Lowest priority.

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

Do this first — dataset-quality threshold experiment
----------------------------------------------------

An early practice run only proved "37 dark frames = far below the floor."
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

Build order
-----------

1. Dataset-quality experiment (above) — cheap, unblocks all estimates.
2. Interaction model (B15) — core to personality/bonds/memory; see
   `person-recognition.md`.
3. Headless-flash research: required before any model-swapping.
4. Model-manager: once headless flash works.
5. Safety model (B16) — gated on camera-mounted-on-frame (POV-specific
   training data); highest priority the moment the body exists.
6. Objects model: COCO-80 deploy, lowest effort; wire `scene.narrate`.

Priority if forced to choose: **safety > recognition > objects.**

---

Consumers (mostly built)
------------------------

- `vision/feed.py` `SerialDetectionFeed`: Uses: parses INVOKE → `Detection`; State: built; auto-starts inference; `VISION_LABELS` names classes
- `vision/avoidance.py` `Avoider`: Uses: box area → closeness, `center_x` → bearing; State: built; thresholds need real-detection + stopping-distance calibration
- `vision/scene.py`: Uses: detections → text → Claude narration; State: built
- `vision/terrain_feature.py`: Uses: box → (dist, bearing, tall_flag) for the gait obs; State: removed with vision-in-the-gait closed; recover it from git (it is in commit f6f133d)
- `personality/bonds.py`: Uses: detection label → disposition / closeness; State: built (API only)
- `memory` + B11 place memory: Uses: accumulate "kitchen has a table", "dog near couch"; State: memory built; place-graph not

---

Open questions
--------------

- Headless `.tflite` flash from the Pi over serial — command sequence?
- Real multi-slot on this firmware, or always single?
- `frame_px`: model runs 192 but reports in the 240 frame — confirm this holds
  for a custom multi-class model too (it held for the stock person + gesture).
- Model-swap time budget vs. mode-transition frequency — is 1–2 min acceptable,
  or does it force the "one combined companion model" route?
- Objects model: full COCO-80 vs. a curated ~15-class subset for accuracy.

Measured detector behaviour
---------------------------

Numbers measured with the **Grove Vision AI V2** on USB to the Mac,
running SenseCraft's `swift_yolo_nano_person_192_int8_vela` (model id 60086,
single `person` class). These are the **mount-independent** characteristics —
they feed the sim noise model for a future perception-in-the-loop gait retrain
(Phase 8 / hardware-gated H-list). The **mount-dependent** parts (visibility
cone, range-vs-confidence falloff, pixel→ground geometry) still need the camera
fixed to G2 and measured against known distances.

### Firmware / module facts

- Name / FW: "Grove Vision AI V2", software `2025.01.02`, `at_api v0`
- USB serial: CH343 bridge (VID `1a86` / PID `55d3`), `/dev/ttyACM0` / `/dev/cu.usbmodem*`, 921600
- Model slots: **one** — `AT+MODELS?` returns a single entry. Switching models = a full reflash (~1–2 min), *not* an instant `AT+MODEL=<id>` swap on this FW.
- Sensor resolutions: 240×240 (default), 480×480, 640×480 — but the model runs at its own input size (192 here) and **reports boxes in the 240 frame** (`resolution:[240,240]`). `frame_px=240` is correct.
- Box format: `[cx, cy, w, h, score, class_id]`, `(cx,cy)` = **centre**, pixels in the 240 frame, score 0–100. Only `type==1` INVOKE messages carry results.
- Start / stop: module does not self-stream — send `AT+INVOKE=-1,0,1` (loop, results-only, no JPEG) to start, `AT+BREAK` to stop. `feed.py` does this.
- Model-reselect + inference restart: ~0.5 s

### Detector behaviour

Empty bench, 22 s / 340 frames → **0 false positives**.
Clear target (person, ~3–5 ft, centred, holding still), 25 s / 384 frames:

- Output rate: Value: **~15 fps**; Note: serial-limited
- Inference time: Value: **48 ms, deterministic** (min=max); Note: ~20 Hz raw; NPU is fixed-cost
- Detection rate while present: Value: **~83 %** → **~17 % dropout**; Note: frames with 0 boxes despite the target being there
- Confidence: Value: mean **66**, range **50–87** (threshold 50); Note: sits close to threshold — winks in/out near range limits
- Centre jitter (static target): Value: cx σ ≈ **5 px**, cy σ ≈ **3 px**; Note: ~2 % of frame — bearing is fairly stable
- Box-size jitter (static target): Value: w σ ≈ **18 px**, h σ ≈ **16 px**; Note: **~7–8 % of frame — large.** area-as-distance will be noisy

### Implications for the sim noise model

When the perception-in-the-loop retrain happens, the fake detector in the env
should reproduce, at minimum:

- ~15 Hz update, not the 80 Hz control rate. Hold the perception signal
  stale between updates (≈5 control ticks per detection).
- ~50 ms latency: shift the signal back ~1 control step.
- ~17 % random whole-detection dropout: even when the feature is in view.
- Bearing noise small (σ ≈ 2 % of frame), **distance/size noise large**
  (σ ≈ 8 % of frame → distance-from-area ≈ ±20–30 %).
- Confidence near threshold: → detections flicker at range; model a
  probability-of-detection that falls off with distance (needs mounted-camera
  measurement to set the curve).
- No false positives on a clean scene but this was a plain bench; a
  cluttered room may differ. Re-check once mounted.

### Still needs the camera mounted on G2

- Visibility cone: camera height, pitch, FOV → which ground distances are even
  in frame, and the blind wedge in front of the feet.
- Probability-of-detection vs. distance / vs. box position in frame.
- Pixel-box → (distance ahead, lateral bearing, height) mapping — the
  `terrain_feature.py` `fov_scale` / `s_near` / `s_far` / `h_tall` constants.
- Motion blur / vibration effect while walking.
- Low-light and backlit behaviour in the real room.

### Low-light: auto-exposure lift (bench)

Stock Himax tuning aims the OV5647 auto-exposure **dim** -- WPT/BPT target
regs `0x3A0F`/`0x3A10`/`0x3A1B`/`0x3A1E` default `~0x32`/`0x24`. In a dim
room that gave dark, low-signal frames and a poor detection hit-rate.
Adding **+0x20..0x30** to those four regs via `AT+SETREG` lifted mean
frame brightness ~108 -> ~166 and **markedly raised the person-detection
hit-rate** (user-confirmed on the live feed). Runtime-only -- lost on
power-cycle, so re-applied on every open.

Wired: `SerialDetectionFeed(sensor_opt=, ae_bump=)`, config
`VISION_SENSOR_OPT` (default 1 = 480 capture, cleaner downscale, boxes
come in that frame -- feed reads the per-message `resolution`) and
`VISION_AE_BUMP` (default 32).

**TUNE on the mounted camera** under real on-robot lighting: a fixed lift
over-exposes a bright scene, and it trades against motion blur (longer
exposure). Options if a fixed value isn't good enough: adaptive (read
frame brightness, adjust), or gain instead of exposure (brighter without
blur, noisier). Hardware-gated.

### Camera orientation vs. detection

The OV5647's native readout is fixed; **physically rotating the module
rotates the scene within the frame.** With the module in one orientation
the person came out sideways and the *library* Person-Detection model
(trained on upright people) hit only **~13%** of frames -> few pre-labels.
Rotating the module so the raw feed is **upright** took the hit-rate to
**100%** (score ~87). Lesson: mount the camera so its *raw* output is
upright, and use that as G2's mount orientation. A custom model trained on
either orientation works (train == infer), but upright lets you use
pretrained upright models and get clean pre-labels. Curate then needs
`--rotate 0`.

#### Why the preview looked tilted when detection worked

The mount is right: with the module's **USB port up**, the raw frame (checked with a real snapshot) is upright, which is what the
detector needs. The tilt was the preview page itself: `tools/camera_preview.py` hard-coded a 90 degree CSS rotation of the video from
the days when the module was mounted differently (the old note said "rotated so you look upright"). That default is now 0 degrees.
The module's printed text does not match because the OV5647 sensor's native readout is rotated relative to the board's silkscreen:
the orientation that matters is the one the frame comes out in, not the one the text reads. A web search found no one else reporting
this, so it is a feature of this module and mount; the bench result above (upright frames: 100% hits; sideways: 13%) is
the evidence.
