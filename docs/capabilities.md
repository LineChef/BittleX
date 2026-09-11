# What G2 can do

A running inventory of everything we have taught **G2** (a Petoi Bittle X
quadruped + Raspberry Pi companion) to do.

For *how* the pieces work, see [`how-it-works.md`](how-it-works.md). For the
roadmap and decision log, see [`project-plan.md`](project-plan.md). This file is
the *what*, kept current as capabilities land.

**Status key**

| | meaning |
|---|---|
| ✅ | **Working now** — runs today, on a dev machine, on the camera, or in sim |
| 🧩 | **Built, hardware-gated** — code complete and tested against mocks; needs the physical robot or camera to exercise and tune |
| 🔬 | **Researched / parked** — investigated, outcome recorded, not currently active |

The robot frame and camera are still inbound, so most on-robot behaviour is 🧩:
the logic exists and is unit-tested with the hardware mocked, waiting on bring-up.
`pi_pipeline/` carries **522 passing tests**.

---

## At a glance

| Domain | Headline | Status |
|---|---|---|
| Locomotion — learned | A from-scratch RL walk (`run20m_ppo`) that tracks speed/heading commands, walks a −24° descent, 0 % falls on the payload-on decathlon | ✅ sim / 🧩 robot |
| Locomotion — scripted | ~20 OpenCat keyframe skills wired with friendly names (walk, turn, back up, carpet gait, jump, get-up, sit, stretch, expressive moves) | 🧩 |
| Sim → real | `run20m_ppo` exported to ONNX, bit-for-bit validated against the on-robot control loop; Pi inference measured at 0.43 ms/call | ✅ built / 🧩 deploy |
| Autonomous behaviour | A `BehaviorDriver` that composes explore / idle / converse modes into abstract effects, plus novelty-seeking, gestures, enrollment choreography | 🧩 |
| Personality | Composable traits (curiosity, playfulness, "Gir" character mode), mood model, per-person bonds — all `.env`-driven | ✅ |
| Voice | Wake-word → local STT → Claude conversation → local TTS, with `perform_skill` / `remember` tool-calls and graceful degradation when the API is down | ✅ (mocked audio) / 🧩 mic+speaker |
| Memory | Persistent fact store with recall, a CLI, and a localhost web UI | ✅ |
| Vision | Custom 3-class detector (household member + dog + cat) running **on the camera**; obstacle-avoidance reflex + "what do you see" narration wired to the feed | ✅ model / 🧩 mounted camera |
| Safety reflexes | Jam reflex, servo thermal guard + governor, cliff/edge guard, watchdog, sleep mode, carpet detector | 🧩 |
| Diagnostics | Black-box structured logger with manifest + crash hook, SoC/throttle/battery sampler, gait watchdog that halts on stall | ✅ logic / 🧩 HW sensors |
| Power | Idle-REST staged descent, on-demand vision, sleep mode — three zero-risk levers built | ✅ logic / 🧩 tuning |
| Robot link | One shared serial link with auto-reconnect, command builders, a dangerous-command denylist, and a bring-up self-test | ✅ logic / 🧩 cable |

---

## Locomotion

### Learned gait (RL) — ✅ in sim, 🧩 on the robot
- **`run20m_ppo`** — the frozen deployment base. 20 M PPO steps from scratch in
  PyBullet; a learned *residual* on Bittle's scripted `wkF` trot, IMU-corrected
  every control step.
  - Tracks forward-speed commands to **0.007 m/s** and heading commands.
  - Walks a **−24° descent**.
  - **0 % falls** on the payload-on (Pi + camera mass) 27-cell decathlon.
  - Conditioned on the mounted-payload configuration, so the sim gait already
    "knows" it is carrying the companion stack.
  - `rl_training/opencat-gym/` — training, eval, and `watch_trained.py` replay.
- **Continuous balance** — the policy re-decides every control tick from body
  tilt + recent joint history + a rhythm clock, so it corrects small shoves and
  low obstacles by construction.

### Scripted skills — 🧩
Friendly-named wrappers over OpenCat keyframe tokens
(`pi_pipeline/link/opencat.py`), so the rest of the stack never hard-codes raw
serial:
- **Move:** stand, rest/relax, walk L/R (curved / pivot), walk backward, jump.
- **Carpet gait** — `carpetF` (higher foot clearance); the carpet detector
  switches to it on sustained slip.
- **Get-up / recovery:** `rc` self-right, `rl` roll-from-supine, `dropRec`
  last-ditch flail, `balance` settle. (Bittle has no roll-axis joint — recovery
  is scripted, not learned; replayed in sim, 0/2 recover from a full flip, which
  matches the hardware limit.)
- **Expressive / social:** stretch, sit, sleep-curl, play-bow, sniff, scratch,
  nod, shake-paw, high-five, wave.

### Sim → real deployment — ✅ built, 🧩 final on-robot validation
- ONNX export of `run20m_ppo`, **bit-for-bit validated**: 0 joint-degree cells
  differ between `model.predict` and the on-robot control loop.
- Pi bring-up completed when the Pi arrived: provisioning script ran, policy
  inference **0.43 ms/call**, no thermal throttle.
- `docs/guides/gait-deployment.md` — the full sim→real path.

### Ruled out — 🔬
- **Vision inside the gait policy** — four training campaigns (Phases A–F). A
  policy that can see forward learned to plow through obstacles, not brace. Now a
  reflex layer *above* the frozen walk instead. `docs/rl/vision-in-gait.md`.
- **Learned big-stumble recovery** — can't be reward-tuned; ~18–25 %
  conditional-survival ceiling. `docs/rl/phase4-decision-log.md`.
- **Learned turn-in-place** — sim-physics limit; turning routed to firmware gaits.

---

## Autonomous behaviour

`pi_pipeline/behavior/` — a `BehaviorDriver` that turns sensor + mode state into
abstract **effects** (`SKILL / STOP / WALK / TURN / HEAD / SPEAK / CAPTURE / CUE /
CHIRP / POWER / DIAG`), which `DriverBindings` routes to whatever sinks are
injected. `BehaviorRuntime` (`runtime.py`) is the loop that ticks the driver at
a fixed rate, feeds it inputs from injected sources (event queue, detection
feed, sensors, mood recency, bonded roster), and dispatches the effects.
**`pi_pipeline/app/`** is the real-I/O wiring: serial + power backed sinks
(`app/sinks.py`), a `SensorHub` that turns the IMU stream + detection feed into
the driver's continuous inputs (`app/sensors.py`), and `python -m pi_pipeline.app`
— the voice loop and the behaviour runtime running side by side over one shared
link, **mock by default, `--serial` on the robot**. All 🧩.

- **Modes** — `converse` / `idle` / `explore`, with a controller that switches
  between them.
- **Explore, two tiers:**
  - **Tier 0 "attentive"** (`behavior/attentive.py`) — *stationary*, always
    active as a life-signs layer on IDLE: gaze-follows a person with head/body,
    reacts to something new in view (look → peer bow → curious chirp), does a
    periodic head pan-scan, greets known people. **No walking, ever** — safe on
    desk or floor.
  - **Tier 1 "roam"** — walking exploration (wander stalest heading, investigate
    novelty). **Voice-armed only** ("G2, go ahead and look around" / "exploration
    mode"); no time-based entry. Ends on any activity, a bout cap, a leg-budget
    leash, or "that's enough" — and disarms, so each bout needs re-arming.
    Gated by `features.vision`; the desk-edge classifier (B16) upgrades it for
    near-edge use.
- **Idle-posture staged descent** — what pose G2 holds with nothing to do:
  peek → sit → rest → sleep, backing off gradually rather than freezing.
- **Graceful shutdown** — "shut down" / "go dormant" → G2 lies flat (`d`) first,
  holds ~2 s, then goes dormant (power-save + camera off, stays flat). Distinct
  from the emergency freeze and from "go to sleep" (which curls).
- **Deep-idle sleep** — below RESTING: after a long quiet stretch (or on
  command) the driver curls up (`kzz`), drops the Pi to the power-save profile,
  and turns the camera off, then wakes on the wake word / a tap / a loud sound /
  being spoken to — emitting the rouse choreography and restoring full power.
- **Mood-scaled idle timing** — the slow mood (below) shortens the descent
  delays when LONELY (settle sooner, seek attention) and lengthens them when
  SUBDUED.
- **Gestures** — the behaviour layer decides *when* to fire expressive skills
  (bow, wave, nod…) from context.
- **Person enrollment choreography** — speak / orient / capture-on / capture-off
  steps to walk a new face through a capture session.
- **Emotive chirps** — the driver emits a `beep`-melody mood (happy / alert /
  sleepy / greeting …) on recognition, a startle, a greeting, an edge reflex,
  or sleep entry, rate-limited to at most one per tick.

---

## Personality

`pi_pipeline/personality/` — composable, all `.env`-driven, all ✅.

- **Traits** (`G2_TRAITS`, levels 0–1) — each contributes a prompt fragment,
  behaviour-param biases, and event cues:
  - **curiosity** — investigate longer, approach novelty.
  - **playfulness** — more vocal / fidgety / wandering; deliberately pulls
    *against* curiosity's patience.
  - **"Gir" character mode** (`gir`) — an opt-in manner overlay, default level
    0.4, **off unless you turn it on** (env or by asking G2 "enable Gir mode").
    Task-guarded at every level so it never derails a real instruction.
- **Mood model** — NEUTRAL / CONTENT / PLAYFUL / LONELY / SUBDUED from recent
  interaction history; notices being rebuffed. Wired: the voice loop feeds it
  interaction recency each turn and folds its one-line hint into the system
  prompt; the behaviour driver applies its idle-timing bias.
- **Bonds** (`G2_BONDS`) — per-person familiarity + disposition
  (affectionate / playful / fearful …) that colours how G2 greets and reacts.
  Personal identifiers live only in the gitignored `.env`.
- **Runtime character state** — turning a character on by voice persists across
  restarts (`character.json`), outranking the env default.

---

## Voice

`pi_pipeline/voice/` — ✅ end-to-end against mocked audio and the **live Claude
API** (`livecheck.py`, last run all-pass); 🧩 on a real mic + speaker.

- **Full loop** — wake word → Vosk local speech-to-text → Claude conversation
  turn → Piper local text-to-speech, with follow-up windows and silence timeouts.
- **Tool-calls Claude can make mid-turn:**
  - `perform_skill` — G2 acts out a skill while it talks.
  - `remember` — commit a fact to persistent memory.
- **Local commands** (no API) — emergency stop / resume, shut down, explore
  arm / disarm, go to sleep, forget, character on/off — parsed on-device,
  checked before Claude (emergency stop wins over everything).
- **Command acknowledgement** — *every* recognised voice command (and every
  conversational turn) fires an instant "heard you" chirp + a `heard` cue before
  the slower spoken reply, and G2 never moves silently (a bare skill still gets
  a spoken "Okay"). Makes a misheard command obvious so you can cancel it.
- **Memory seam** — every turn pulls memory context before the API call and
  writes back after.
- **Graceful degradation** — auth / rate-limit / billing failures each map to a
  spoken line instead of a crash; rate-limits retry with backoff.
- **API-key expiry warning** — startup warns when `ANTHROPIC_API_KEY_EXPIRES` is
  within the warning window.
- **Offline helpers** — `synth_to_wav`, `transcribe_wav` (no audio device
  needed), used by the Pi voice benchmark (`benchmark_pi.py`, ~94 % word recall).

---

## Memory

`pi_pipeline/memory/` — ✅.

- **Persistent fact store** with tagged recall, backing the voice `remember` tool.
- **CLI** — `python -m pi_pipeline.memory` to add / recall / forget / list.
- **Web UI** — `python -m pi_pipeline.memory.webui`, a localhost-only page to
  browse, add, forget, and (confirmed) wipe.

---

## Vision

`pi_pipeline/vision/` + `tools/gv2/` — ✅ model on the camera; 🧩 the reflexes
that need the camera mounted on the frame for a real point of view.

- **Custom on-camera detector** — a 3-class YOLOv8n model (a household member +
  `dog` + `cat`) runs **on the Grove Vision AI V2 itself**, 100 % on the NPU.
  All three classes detect; verified on the real dog and cat.
- **Reproducible build recipe** — the camera firmware is frozen at Jan 2025 and
  broke every modern export toolchain; the working path (`ultralytics==8.2.8` +
  local arm64 export + `vela`) is fully written up in
  [`vision/custom-model-recipe.md`](vision/custom-model-recipe.md), with repo
  tooling: `export_yolov8_gv2.sh`, `split_yolo_dataset.py`, `vela_config_we2.ini`,
  `autobox_coco.py`.
- **Capture pipeline** — motion-gated capture → curate → contact sheet → promote
  to a keep-library → combine for upload, with a per-session checklist and a
  dataset tracker (`vision/capture-progress.md`, `vision/capture-checklist.md`).
- **Obstacle-avoidance reflex** — watches detection boxes; a large centred box →
  stop / back up / steer. No API, no network; debounced, with an urgent-hazard
  override.
- **"What do you see"** — detections summarised to a sentence and handed to Claude
  through the voice layer's callable.
- **Cliff / edge guard** — a reflex whose input is a table-edge detector (the
  detector itself is the main remaining vision work).

---

## Safety reflexes & guards

All 🧩 — logic complete and unit-tested; thresholds need the real robot.

- **Emergency stop** (`behavior/emergency.py`) — the manual override: latches
  `BehaviorDriver` above *everything* (enrollment / sleep / safety / mode), emits
  stop + an alert chirp + one hold command (`kbalance` by default, configurable),
  and holds until explicitly released. Triggered by a voice phrase ("emergency
  stop" / "freeze" / "halt" / "stop moving"), `python -m pi_pipeline.app --halt`,
  or `kill -USR1 <pid>`; cleared by "resume" / `--release` / `SIGUSR2`.
- **Jam reflex** (`gait/jam_guard.py`, B9a) — vision-free: from commanded-vs-actual
  front-leg joint angle, detect a stuck push and run a fixed bump-and-turn.
- **Servo thermal guard** (`gait/thermal_guard.py`) — per-joint temperature
  tiers GREEN / AMBER / RED, with a spoken "getting warm" warning.
- **Thermal governor** (`behavior/thermal_governor.py`) — NORMAL → THROTTLED →
  COOLDOWN: scales speed, softens the gait, avoids uphill, and can hold a
  cooldown pose; escalates immediately, de-escalates only after a hold.
- **Sleep mode** (`behavior/sleep_mode.py`) — AWAKE → DOZING → ASLEEP → ROUSING;
  enters after a rest period (blocked while a person is present), wakes on loud
  sound / tap / wake word / command. **Wired into `BehaviorDriver`**: emits
  `SKILL kzz` + `POWER headless` + `CAPTURE off` on sleep, `POWER interactive` +
  `CAPTURE on` + the rouse choreography on wake.
- **Carpet detector** (`gait/carpet.py`) — sustained forward-slip → switch to the
  `carpetF` gait. (Runtime wiring + a speed-estimate source still to finish.)
- **Speed estimator** (`gait/speed_estimate.py`) — per-gait-cycle ZUPT
  bias-corrected leaky integrator; inert until a real accelerometer feed exists.
- **Watchdog** (`diag/watchdog.py`) — no heartbeat within the stall window →
  latch STALL and send `d` (lie down, relax).
- **Supervisor** (`util/supervisor.py`) — restart-with-backoff policy + a
  threading wrapper for long-running workers.

---

## Diagnostics & ops

`pi_pipeline/diag/` — ✅ the logging logic; 🧩 the Pi-specific sensor reads.

- **Black-box structured logger** — a full event taxonomy, a run manifest
  (start/end, duration, event + incident counts, clean-exit flag), and an
  `install_excepthook()` that logs unhandled crashes and finalises the manifest.
- **System monitor** (`diag/sysmon.py`) — SoC temperature (any Linux),
  `vcgencmd` throttle flags, battery voltage sag — emits rate-limited
  `battery.sag` / `pi.thermal_throttle` events; no-ops where a reader returns
  nothing.
- **Feature flags** (`G2_FEATURES`, `docs/guides/feature-flags.md`) — staged
  bring-up: perception / vision-nav stack gated **off** until a real detector
  exists.
- **`doctor` preflight** (`python -m pi_pipeline.doctor`) — one-command bring-up
  readiness check: `.env` completeness, API key validity + expiry, model files
  (Vosk / Piper / gait ONNX), Python deps, serial port + optional board ping,
  audio devices, free disk. Non-zero exit on any hard failure.
- **Bench mode** (`python -m pi_pipeline.app --bench`) — for when G2 is on the
  calibration stand: no autonomous movement, voice actuator forced to mock, a
  clear banner — so `check_serial` / `run_gait --probe-imu` / joint calibration
  own the serial link without the behaviour loop fighting them.

---

## Power

`pi_pipeline/power/` — ✅ logic; 🧩 tuning + the behaviour-aware design session.

- **Idle-REST staged descent** — drop to progressively lower-power postures the
  longer G2 is idle.
- **On-demand vision** — camera powered only when perception is needed.
- **Sleep mode hook** — deepest tier, shared with the behaviour sleep FSM.

---

## Robot link

`pi_pipeline/link/` — ✅ logic; 🧩 the physical serial cable.

- **One shared serial link** — voice, vision, and RL deployment all send through
  it; opens and **reconnects on cable pull** without crashing its caller.
- **Command builders** — friendly names → OpenCat serial strings; joint-move
  string builder for streamed policy output.
- **Dangerous-command denylist** — calibration / factory-reset prefixes are
  refused.
- **Fall-recovery state machine** (`link/recovery.py`) — detect a flip → run the
  scripted get-up → settle.
- **Bring-up self-test** (`link/check_serial.py`) — list ports, ping the board,
  send one command, or cycle every skill as a hardware smoke test.

---

## What comes with the repo (for a fork)

- **RL training pipeline** — `rl_training/opencat-gym/`: PyBullet + SB3, the
  residual-on-`wkF` gait design, curriculum + domain randomisation, eval
  decathlon, `watch_trained.py` with a vision ray-fan overlay, and `run20m_ppo`
  itself.
- **Companion pipeline** — `pi_pipeline/`: every module above, every
  hardware-specific stage behind a mock/real seam, `.env`-driven config, 522
  tests, `setup_pi.sh` + `fetch_models.sh` for a headless Pi Zero 2 W.
- **The vision recipe** — a reproducible path to a custom on-camera detector for
  the frozen-firmware Grove Vision AI V2, with tooling in `tools/gv2/`.
- **Deployment stack** — ONNX export + on-robot control loop, sim-validated.
- **Documentation** — `docs/`: the living [`project-plan.md`](project-plan.md),
  [`how-it-works.md`](how-it-works.md), a behaviour-ideas backlog, and
  subject-organised guides / vision / hardware / RL folders.

---

*Keeping this current:* when a capability lands (a trait, a skill, a guard, a
model), add or flip its line here in the same change — same as
`project-plan.md` and `README.md`. This file is the showcase; the plan is the
rationale.
