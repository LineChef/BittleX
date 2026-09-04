# Hardware Readiness

State of the software before the Bittle X and Raspberry Pi arrive, and the
sequence of tasks that need hardware. Snapshot as of `development` @ the commit
adding this file; see `docs/project-plan.md` for the living detail.

---

## RL locomotion (Phase 3) — concluded, paused for hardware

- **Training pipeline** — PyBullet + Stable-Baselines3 in `rl_training/opencat-gym/`,
  converges reliably. The recurring v1–v4 reward collapse was root-caused
  (penalty-ramp timing equal to run length + a non-decaying learning rate) and
  fixed from v5 on. Domain randomization and a `wkF` keyframe-imitation reward
  are wired in.
- **Gaits banked** (all on `development`, checkpoints gitignored):

  | Tag | What it is |
  |---|---|
  | `phase3-gait` (`auto_gait_final`) | Straight level-ground walk, never falls. The baseline. |
  | `gait-v7-stumble-catch` (`auto_rec_r5_ppo`) | Crispest diagonal trot of the project (`diagonal_trot_corr` −0.58), always-on balance-catch term, no obstacle-course falls. |
  | `walk-v8-r2` (`walk_r2_ppo`) | Run 7 best: 0% falls on flat and a 30 mm obstacle course, best heading of the project (4–5° max yaw drift). Walks slow (~0.07 m/s vs a 0.11 target). Config on `development`; not a "reference" gait. |

- **Two hard limits, proven and documented:**
  - A Bittle **cannot self-right** from a full tip-over (> 1.3 rad) — no roll-axis
    joint, a missing degree of freedom. Run 6, 0% recovered across an escalating
    reward.
  - **Big-stumble recovery cannot be reward-tuned further** on this control setup
    (reactive, IMU-only, weak sagittal-plane servos). Run 7, three rounds, 0%
    every time.
- **Decision:** stop sim iteration. Settle "a learned gait vs. OpenCat's scripted
  `wkF`" with a **real-robot head-to-head**. RL locomotion resumes for
  perception-in-the-loop — the Phase 8 "Target capability" in the plan.

---

## Companion software (`pi_pipeline/`) — four pillars, laptop-runnable

Every hardware-specific stage sits behind an interface with a mock and a real
implementation, so the pipeline runs end-to-end on a dev machine now and moving
to the Pi is a config change. Own venv (`pi_pipeline/.venv`); requirements split
core / audio / dev. Fully `.env`-driven (`.env.example` documents every setting).

### `voice/` — Phase 7

- Loop: **wake word → speech-to-text → Claude → text-to-speech → optional skill.**
- Claude client: rolling history, retry-on-timeout, config-driven model/tokens/
  timeout. `perform_skill` and `remember` tools. Replies parsed into
  `AssistantTurn(speech, actions, facts)`.
- Backends: `MockActuator`/`SerialActuator`, `MacTTS`/`PiperTTS`/`PrintTTS`,
  `TextSTT`/`VoskSTT`, `AlwaysAwake`/`VoskWakeWord`.
- Audio deps installed and **verified without a mic**: Piper synthesises + plays;
  Vosk transcribes a Piper phrase back verbatim. Voice: `en_GB-alan-medium`
  (swap via `PIPER_MODEL_PATH`).
- `python -m pi_pipeline.voice.check_audio {devices,wake,stt,tts}` for tuning.

### `memory/` — Phase 9

- SQLite (`pi_pipeline/memory/data/g2_memory.db`, gitignored) + FTS5.
- An `exchanges` log (every turn, full-text indexed) and `facts` (short durable
  notes; `last_recalled` gives a light recency-decay).
- `recall(user_text)` → the fact set plus BM25-matched older exchanges, injected
  before each Claude call. `record()` logs the turn and saves `remember`-tool
  facts.
- `python -m pi_pipeline.memory {facts,log,search,recall,remember,forget,wipe}`.

### `vision/` — Phase 8

- `DetectionFeed`: `MockDetectionFeed` (scripted frames + `approaching()` builder)
  / `SerialDetectionFeed` — parses the **confirmed** Grove Vision AI V2 / SenseCraft
  (SSCMA) format: JSON `INVOKE` lines at 921600 baud, `boxes` = `[x, y, w, h,
  score, target_id]` (centre + size in model-input pixels, score 0–100, numeric
  class id; labels set out-of-band via `VISION_LABELS`).
- `Avoider.decide(frame) -> AvoidanceAction` — local, no network. Box `area` as
  the closeness proxy, `center_x` as bearing. Consecutive-frame debounce +
  cooldown; `STOP`/`BACK_UP` preempt. Escalates `none → turn → stop → back up`.
  `ACTION_SKILL` maps actions to robot skills.
- `scene.summarize(frame)` (deterministic) and `scene.narrate(frame, ask)`
  (spoken-style via an injected `str -> str`; `vision` never imports `voice`).
- `python -m pi_pipeline.vision demo` walks the escalation against a mock
  obstacle.

### `link/` — Phase 5

- `SerialLink` — lazy open, auto-reconnect on drop, `send()` logs and returns
  `""` instead of raising (a yanked cable won't crash the loop). `list_ports()`.
- `opencat.py` — command-string builders (`skill`, `move_joints`, `beep`),
  constants (`REST="d"`, `ENTER_SERIAL2_MODE="XS"`), `is_safe()` blocks
  calibration.
- `python -m pi_pipeline.link.check_serial {ports,ping,send,skills,rest}` +
  a bring-up checklist in `pi_pipeline/link/README.md`.

### Tests

`pi_pipeline/tests/` — **88 pytest tests, all green**, no network / audio / API
key. Covers the skill catalogue, the conversation parse / tool-ack / retry
paths (stub Anthropic client), the memory store / recall / decay / temporal
filter, the serial command builders + safety, the vision detection model +
avoidance reflex + terrain feature, and the personality + behavior layers.
Run: `pi_pipeline/.venv/bin/pytest`.

---

## Repo housekeeping done this session

- Docs rewritten to neutral project-documentation voice (`project-plan.md`,
  `automated-testing-loop.md`, `README.md`); a Phase 8 "Target capability" added.
- `.claude/` removed from the repo; `/train` slash command moved to user-level
  `~/.claude/`.
- `origin/development` in sync.

---

## Hardware spec notes (from vendor docs)

Full sheet + rationale: [`research/hardware-specs.md`](research/hardware-specs.md).
The ones that change plans:

- **BiBoard V1 IMU is 6-axis (MPU6050/ICM42670) — no magnetometer.** No absolute
  yaw on hardware; real heading drifts. Bias the RL reward toward yaw *rate*.
- **BiBoard V1 flash is 4 MB / SRAM 520 KB** (not the "16 MB" some Petoi pages
  show — that's V0). Tight for an on-MCU gait policy.
- **BiBoard V1 has an onboard offline voice-recognition module + speaker** — a
  possible wake trigger / offline-command path that offloads the Pi.
- **Vision module: detections OR a raw frame, never both at once**; 192×192,
  ~10–30 FPS; model swap takes 1–2 min. Camera toggle over serial: `XC` / `Xc`.
- **PiSugar S is hardware-only — no battery-% readout, no query token to add.**
  If battery telemetry is ever wanted, it needs an external ADC on a Grove
  analog pin, or time-boxed sessions (see `docs/behavior-ideas.md` B12).

## Day-1-with-the-camera checklist

The Grove Vision AI V2 module (+ the calibration stand) arrive **before** the
Bittle body. Everything below only needs the module + a USB-C cable + the Pi (or
even just a computer for the model workflow) — none of it waits on the body.

**Power-on & the stock demo (no Pi needed)**

1. USB-C to a computer. Seeed ships a pretrained demo model (typically person
   detection) — confirm it boots and the SenseCraft AI web tool
   (Seeed's browser-based flasher/monitor) shows live detections. This alone
   validates the module works before wiring anything.
2. Familiarise with **SenseCraft AI**: the model-deploy workflow, and the "DIY"
   COCO-subset picker vs. a fully custom model (Colab → YOLOv8n → quantise →
   Vela-optimise → deploy) — `docs/project-plan.md` Phase 8 has the reference
   notes on this pipeline.

**Wire it to the Pi — first real test of `pi_pipeline/vision/`**

3. Connect the module's UART to the Pi (Grove 4-pin → jumper wires to Pi UART —
   confirm the exact pinout against the current Seeed wiki page; not yet
   verified against our hardware). 921600 baud.
4. `python -m pi_pipeline.vision serial <port>` — this is the moment
   `SerialDetectionFeed` sees a real detection stream for the first time
   (it's only ever run against `MockDetectionFeed`). Confirm the JSON `INVOKE`
   shape matches: `{"name":"INVOKE","data":{"boxes":[[x,y,w,h,score,id]]}}`.
5. **Resolve the two open format questions** (noted since the research phase,
   never checked against real hardware): is the box `(x,y)` centre or top-left,
   and what's the actual model input pixel size? Set `VISION_FRAME_PX` /
   `VISION_LABELS` in `.env` once confirmed. Fix `Detection.from_center_px()` if
   it's corner, not centre.
6. **Calibrate the two hardware-first-guess configs** against measured
   distances/heights (put a known object at a known distance, read the box):
   - `AvoiderConfig` thresholds (`pi_pipeline/vision/avoidance.py`) vs. the
     module's real detection range and reliable box-area-to-distance behaviour.
   - `TerrainFeatureConfig` (`pi_pipeline/vision/terrain_feature.py`) —
     `s_near`/`s_far` (area→distance), `h_tall` (box height→tall_flag),
     `fov_scale`. Currently first-guess numbers with an explicit "calibrate on
     hardware" note.

**Start the custom model (B15) — can run in parallel with the above**

7. Photograph household members + pets for the custom detection classes — save
   under a gitignored dir (`training_data/`, already in `.gitignore`; see
   `docs/behavior-ideas.md` B15). A few dozen photos per class, varied angles/
   lighting.
8. Label + train in SenseCraft (or the Colab/YOLOv8n path), deploy to the
   module, and re-run step 4 to confirm it detects the new classes.

None of this needs the Bittle body, the BiBoard, or the calibration stand — it's
all camera + USB/UART + the Pi (or a laptop). It fully unblocks the "queued /
camera-gated" list below except the items that also need a moving robot.

---

## Camera-gated backlog — queued up for tomorrow

Everything across the docs that was blocked on "needs the camera," in the order
it becomes reachable:

**Reachable with just the camera (start tomorrow, per the checklist above)**
- Verify the live detection format + fix `Detection.from_center_px()` if needed
  (`pi_pipeline/vision/feed.py`, `vision/README.md` "Still to do")
- Calibrate `AvoiderConfig` (`vision/avoidance.py`) against real detections
- Calibrate `TerrainFeatureConfig` (`vision/terrain_feature.py`) — the walk
  policy's forward-terrain-signal constants
- Train + deploy the first custom SenseCraft model
- **B16 — `CliffGuard` desk-edge classifier — HIGHEST PRIORITY.** Photograph the
  real desk + its edges (multiple lighting conditions, tricky cases: an object
  near the edge, glare, shadows) and train the floor-vs-edge classifier before
  anything else. A miss here is a fall; do this ahead of B15.
- **B15 — recognize household members**: start photographing + labelling now;
  the bond/disposition layer in `pi_pipeline/personality/` is already built and
  waiting for real detections

**Needs the camera mounted ON G2 (body required too)**
- Wire `Avoider` decisions to the actuator (currently logic-only, tested against
  mocks) — `vision/README.md`
- **B16 — `CliffGuard` reflex itself**: build + test the zero-debounce,
  everything-preempting stop-and-back-away behavior against the trained
  classifier, on the real robot, before ever trusting autonomous desk
  exploration unsupervised.
- **B7 — Patrol mode**: walks a loop, stops + narrates on motion/person detection
- **B8 — Go-to-object**: approach controller inverting the `Avoider` math
- **B9 / B13 tier 3 — vision-gated obstacle traversal / climb-as-a-skill**:
  vision spots a step too tall to walk over → invoke a separate climb policy
- **B11 — place memory**: scene descriptions → a graph of recognized places
- `scene.narrate` wired into the voice loop (Phase 10)

**Needs the camera + a working detector + hardware validation before it's worth
training** (the RL side)
- **Perception-in-the-loop gait retrain** (Phase 8, `docs/project-plan.md`
  "DECIDED ARCHITECTURE") — flip `TERRAIN_FEATURE = True`, tune the sim
  generator's noise to the real detector's measured stats, retrain
- **R-NOSTALL** ("don't stall" reward work, `robustness-backlog.md`) —
  explicitly deferred to here; a blind policy can't be intentional about an
  obstacle it can't see
- (Stretch) more robust self-righting, once vision + IMU are both feeding the
  policy

**Needs everything (Phase 10 integration)**
- Voice + vision + memory running concurrently, resource/timing conflicts
  resolved

## Day-1-with-hardware checklist

**Assembly & Pi bring-up**

1. Assemble Bittle X V2; check servo calibration (ships calibrated — only
   fine-tune if movement looks off).
2. **Weigh the final build** — on a kitchen scale, once the Pi + PiSugar S +
   camera + mount are actually on the robot. Don't just weigh two big lumps —
   weigh the **camera module and the PiSugar S battery separately** (from
   everything else and from each other), each with its own position/CoM. The
   battery alone is more than half the current spine-stack estimate, and if it
   ends up mounted somewhere distinct from the Pi board, lumping it in
   mislocates the CoM. Then decide the sim body split from what you actually
   measured — the current model is two bodies (spine = Pi/PiSugar/wiring/cover,
   head = camera cluster), but if the battery's position is meaningfully
   different from the rest of the spine stack, give it a **third body** rather
   than force-averaging it in. Balance each piece on an edge for height +
   fore/aft offset. Then **update the training sim to match**: set
   `PAYLOAD_MASS_NOM`/`_RAND` and `HEAD_MASS_NOM`/`_RAND` +
   `PAYLOAD_POS`/`HEAD_MASS_POS` (and a new battery body/knob if warranted) in
   `opencat_gym_env.py`, and retrain (or a `--finetune-lr` continuation) if the
   delta from the current ~76 g estimate is real. Full detail + trigger:
   `docs/rl-runs/hardware-gated-training-backlog.md` **H2**.
3. **On the calibration stand, before it ever touches the ground:** full
   range-of-motion pass (each joint by hand / `check_serial`, watch for binding
   or leg-on-leg collision), firmware `c16` auto joint calibration. This is the
   safe place for first power-on — confirm wiring/polarity, nothing grinds,
   before the robot has to support its own weight. (Detailed steps once the RL
   gait is involved: `docs/gait-deployment.md` step 6.)
4. Flash the Pi with Raspberry Pi Imager — Wi-Fi + SSH pre-configured (headless).
   Confirm SSH.
5. `sudo raspi-config` → serial: disable the login shell over serial, enable the
   serial hardware. Disable 1-wire. Disable Wi-Fi power-save
   (`sudo iw wlan0 set power_save off`).
6. Wire Pi ↔ BiBoard **data-only** (RX/TX/GND); PiSugar S is the sole power
   source. Confirm the back cover fits.

**Serial link (Phase 5)**

7. `python -m pi_pipeline.link.check_serial ports` → identify the device, set
   `G2_SERIAL_PORT` in `.env` (likely `/dev/ttyS0`).
8. On the BiBoard, enable Serial-2 mode (`XS`, or edit `OpenCat.h` + reflash).
9. `check_serial ping` → expect a firmware banner. `check_serial send kbalance`
   → robot stands. `check_serial skills` → runs the whole conversational set.

**Voice (Phase 7)**

10. Put a real key in `ANTHROPIC_API_KEY`. `python -m pi_pipeline.voice --mode text`
    → Claude + memory end-to-end.
11. `check_audio wake` / `stt` on the Pi's mic → tune `G2_WAKE_WORD` and
    `G2_STT_SILENCE_S`. `--mode voice --actuator serial` for the full loop.
12. **Perf on the Pi Zero 2 W:** are Vosk + Piper light enough on 512 MB / a weak
    A53? Measure the wake→spoken-reply round trip. If sluggish → shorter
    `CLAUDE_MAX_TOKENS`, streaming TTS, streaming Claude, a "thinking" cue.
13. Implement the buzzer / posture state cues (`voice/cues.py`) and a thread
    watchdog for the audio + serial threads.

**Vision (Phase 8)** — camera bring-up itself doesn't wait for the body; see the
**Day-1-with-the-camera checklist** below. What's left once the body + BiBoard
exist too: mount the camera on G2 (vs. bench-testing loose on the Pi) and wire
`Avoider` decisions to the actuator.

**RL sim-to-real (Phase 6) — DONE**, before hardware even arrived: ONNX export +
parity, the on-robot control loop, sim-validated bit-for-bit
(`docs/gait-deployment.md`). Remaining is hardware-only:

14. `pi_pipeline/gait/bench_real.py` — confirm real-time joint control on the
    actual Pi Zero 2 W (sim bench: 0.43 ms/step, well inside budget).
15. **The H1 head-to-head** on the real robot — full methodology + course +
    decision rule: `docs/rl-runs/h1-head-to-head-rubric.md`. Measures the
    sim-to-real gap and produces a keep/fall-back/middle verdict on RL
    locomotion; `h1_score.py` turns the numbers into it.

**Integration (Phase 10)**

16. Run voice + vision + memory alongside each other; resolve timing/resource
    conflicts. Budget real time — this is historically the messiest phase.
17. Once vision works, revisit locomotion with perception in the loop
    (`TERRAIN_FEATURE`, already plumbed in sim — `docs/project-plan.md` Phase 8),
    toward the Target capability: confident walking over a cluttered floor,
    steps over small objects it sees, slows/stops at big obstacles and edges.
