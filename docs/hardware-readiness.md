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

`pi_pipeline/tests/` — **31 pytest tests, all green**, no network / audio / API
key. Covers the skill catalogue, the conversation parse / tool-ack / retry
paths (stub Anthropic client), the memory store / recall / decay, the serial
command builders + safety, and the vision detection model + avoidance reflex.
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
- **PiSugar S is hardware-only — no battery-% readout.** Battery telemetry must
  come from the BiBoard firmware (see checklist item 8), not the PiSugar.

## Day-1-with-hardware checklist

**Assembly & Pi bring-up**

1. Assemble Bittle X V2; check servo calibration (ships calibrated — only
   fine-tune if movement looks off).
2. Flash the Pi with Raspberry Pi Imager — Wi-Fi + SSH pre-configured (headless).
   Confirm SSH.
3. `sudo raspi-config` → serial: disable the login shell over serial, enable the
   serial hardware. Disable 1-wire. Disable Wi-Fi power-save
   (`sudo iw wlan0 set power_save off`).
4. Wire Pi ↔ BiBoard **data-only** (RX/TX/GND); PiSugar S is the sole power
   source. Confirm the back cover fits.

**Serial link (Phase 5)**

5. `python -m pi_pipeline.link.check_serial ports` → identify the device, set
   `G2_SERIAL_PORT` in `.env` (likely `/dev/ttyS0`).
6. On the BiBoard, enable Serial-2 mode (`XS`, or edit `OpenCat.h` + reflash).
7. `check_serial ping` → expect a firmware banner. `check_serial send kbalance`
   → robot stands. `check_serial skills` → runs the whole conversational set.
8. Find the **battery-voltage query token** in the OpenCatEsp32 serial parser
   (not yet known); add it to `opencat.py`.

**Voice (Phase 7)**

9. Put a real key in `ANTHROPIC_API_KEY`. `python -m pi_pipeline.voice --mode text`
   → Claude + memory end-to-end.
10. `check_audio wake` / `stt` on the Pi's mic → tune `G2_WAKE_WORD` and
    `G2_STT_SILENCE_S`. `--mode voice --actuator serial` for the full loop.
11. **Perf on the Pi Zero 2 W:** are Vosk + Piper light enough on 512 MB / a weak
    A53? Measure the wake→spoken-reply round trip. If sluggish → shorter
    `CLAUDE_MAX_TOKENS`, streaming TTS, streaming Claude, a "thinking" cue.
12. Implement the buzzer / posture state cues (`voice/cues.py`) and a thread
    watchdog for the audio + serial threads.

**Vision (Phase 8)**

13. Mount the camera to the Grove socket; upload firmware.
14. `python -m pi_pipeline.vision serial <port>` → verify the SSCMA JSON shape
    live; confirm centre-vs-corner and the model input pixel size; set
    `VISION_FRAME_PX` / `VISION_LABELS`.
15. Train a SenseCraft detection model (cables, small objects, table edges);
    record its label list + input size and the deploy workflow.
16. Tune `AvoiderConfig` thresholds against real detections + the robot's actual
    stopping distance.

**RL sim-to-real (Phase 6)**

17. Benchmark `model.predict()` on the Pi — is real-time joint control feasible
    on a Pi Zero 2 W? (If not, the RL-deployment path needs rethinking.)
18. **Gait head-to-head on the real robot:** scripted `wkF` vs `walk-v8-r2` vs
    `gait-v7-stumble-catch`. Measure the sim-to-real gap. Decide whether to keep
    building on RL locomotion.

**Integration (Phase 10)**

19. Run voice + vision + memory alongside each other; resolve timing/resource
    conflicts. Budget real time — this is historically the messiest phase.
20. Once vision works, revisit locomotion with perception in the loop, toward the
    Phase 8 Target capability (confident walking over a cluttered floor, steps
    over small objects it sees, slows/stops at big obstacles and edges).
