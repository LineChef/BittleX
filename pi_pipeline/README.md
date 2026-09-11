# Pi Pipeline

Code that runs on the Raspberry Pi Zero 2 WH mounted on G2: the voice
conversation loop, persistent memory, on-device vision, the on-robot gait loop,
the autonomous behaviour layer, diagnostics, and Pi power management. Independent
of `rl_training/` — separate venv, separate concerns.

## Design

Everything hardware-specific sits behind a small interface with a **mock/laptop
implementation and a real implementation**, so the whole pipeline runs and is
testable on a development machine now, and moving to the Pi is a config change,
not a rewrite:

| Interface | Laptop / dev | On the robot |
|---|---|---|
| `Actuator` | `MockActuator` — logs the command | `SerialActuator` — OpenCat serial (`kwkF`, …) |
| `TTS` | `MacTTS` (`say`) / `PiperTTS` | `PiperTTS` → Pi speaker |
| `STT` | `TextSTT` (type it) / `VoskSTT` | `VoskSTT` → Pi mic |
| `WakeWord` | `AlwaysAwake` / `VoskWakeWord` | `VoskWakeWord` |
| `Cue` | `LogCue` | `LogCue` + buzzer/posture later |

## Layout

```
pi_pipeline/
  config.py            # Settings, loaded from environment (.env at repo root)
  features.py          # staged bring-up feature flags (G2_FEATURES)
  voice/               # Phase 7 — the conversation loop
    conversation.py    # Claude client + turn mgmt; perform_skill + remember tools
    skills.py          # OpenCat skill catalog + serial command mapping
    actuator.py tts.py stt.py wake_word.py cues.py   # swappable mock/real backends
    commands.py        # self-handled spoken commands (forget / sleep / character mode)
    loop.py            # the orchestrator
    livecheck.py       # real-API end-to-end check (needs a key)
    __main__.py        # python -m pi_pipeline.voice
  personality/         # traits that bias the prompt, behaviour params, and cues
    traits.py          # Trait base + BehaviorParams + the name→class REGISTRY
    curiosity.py gir.py            # concrete traits (gir = opt-in character mode)
    mood.py            # B6 mood-from-memory (neutral/content/playful/lonely/subdued)
    bonds.py           # B15 per-individual relationships (disposition + closeness)
    character_state.py # runtime persistence for the opt-in character toggle
    personality.py     # Personality: system_prompt() / behavior_params() / cues()
  behavior/            # what G2 does on its own between conversations
    driver.py          # BehaviorDriver.tick() -> ordered Effects (composes it all)
    bindings.py        # DriverBindings: Effect -> real sink; MockBindings for tests
    runtime.py         # BehaviorRuntime: ticks the driver, feeds it its inputs
    __main__.py        # python -m pi_pipeline.behavior (mock demo of the loop)
    mode_controller.py explore.py novelty.py idle_posture.py gestures.py
    enrollment.py      # "G2, meet <name>" capture FSM
    sleep_mode.py      # deep-idle FSM (curl + vision off + power-save), wired in the driver
    thermal_governor.py # servo-thermal Layer 2 (AMBER throttle / RED cooldown pose)
    chirps.py          # B5 emotive buzzer-melody vocabulary, wired in the driver
    diag_bridge.py     # driver DIAG effects -> diag events
  app/                 # Phase 10 integration: the ONLY place with real I/O wiring
    sinks.py           # serial + power backed DriverBindings sinks; build_bindings()
    sensors.py         # SensorHub: IMU stream + detection feed -> the sensors() dict
    __main__.py        # python -m pi_pipeline.app — voice loop + behaviour runtime
  doctor.py            # python -m pi_pipeline.doctor — bring-up readiness checklist
  bringup.py           # python -m pi_pipeline.bringup — guided, resumable bring-up checklist
  gait/                # Phase 6 — sim-to-real deployment of run20m_ppo
    residual_policy.py deploy_map.py run_gait.py   # the 80 Hz on-robot loop
    thermal_guard.py   # I2t heat estimate + 3-tier indicator
    carpet.py speed_estimate.py   # carpet-slip detect + IMU-ZUPT speed estimate
    jam_guard.py       # B9a vision-free servo-strain jam reflex
    skill_layer.py skill_switch.py gait_selector.py   # Phase E scripted skill switching
  vision/              # Phase 8 — camera / detection feed / avoidance / cliff guard
  memory/              # Phase 9 — SQLite conversation memory; webui.py (browse/prune)
  link/                # Phase 5 — resilient BiBoard serial link + recovery FSM
    check_serial.py    # port/ping/skill checks + `firstmove` (guided first movement)
    trace.py           # TracingLink (log every command sent) + replay
  diag/                # black-box logger + ring buffer + watchdog + sysmon stubs
  power/               # CPU governor / Wi-Fi power-save / disable peripherals
  util/                # supervisor.py — restart-on-death/hang for worker threads
```

Personality is set via `G2_TRAITS` (e.g. `curiosity=0.85, playfulness=0.4`);
the opt-in character mode is `G2_CHARACTER=gir` (`G2_CHARACTER_LEVEL`, default
0.4), toggleable at runtime by saying "enable/disable gir mode".
`python -m pi_pipeline.personality` prints the resolved prompt + behaviour knobs.

## Setup

```bash
python3.11 -m venv pi_pipeline/.venv
source pi_pipeline/.venv/bin/activate
pip install -r pi_pipeline/requirements.txt          # core (anthropic, dotenv)
pip install -r pi_pipeline/requirements-audio.txt    # optional: vosk / piper / sounddevice
pip install -r pi_pipeline/requirements-dev.txt      # optional: pytest
```

Copy `.env.example` to `.env` at the repo root and set `ANTHROPIC_API_KEY`. Set a
spend limit on the key before first use — see
[`docs/guides/api-setup.md`](../docs/guides/api-setup.md).

## Tests

```bash
pi_pipeline/.venv/bin/pytest        # from the repo root; config in pyproject.toml
```

`pi_pipeline/tests/` — no network, audio, or API key required (**570 pass, 1
skips** without a key — the live-API check). Covers the skill catalogue, the
conversation parse / tool-ack / retry / mood-hint paths (stub Anthropic client),
memory store + recall + decay + recency + web UI, the vision feed + avoidance +
cliff guard, the behaviour driver + bindings + runtime + all its state machines
(mode / explore / idle / sleep / mood / chirps / enrollment), the app sinks +
SensorHub, the gait guards (thermal / jam / carpet / speed estimate), diagnostics
+ watchdog, the worker supervisor, the personality traits + character toggle, and
the `doctor` preflight. Run before committing. With a key:
`pytest pi_pipeline/tests/test_livecheck.py -s` hits the real API.

## Run

```bash
# Text mode — type instead of speaking, G2 replies via macOS `say`. No audio deps.
python -m pi_pipeline.voice --mode text

# Voice mode — wake word + mic + Vosk STT + Piper TTS (needs the audio deps + models)
python -m pi_pipeline.voice --mode voice

# Either mode: --actuator mock (default) logs skill commands; --actuator serial sends them

# The whole robot as one program — voice loop + behaviour runtime, side by side.
python -m pi_pipeline.app                 # mock: no serial, dry-run power
python -m pi_pipeline.app --serial        # talk to the BiBoard
python -m pi_pipeline.app --bench         # on the calibration stand: no autonomous movement

# EMERGENCY STOP a running app (freezes + holds until released)
python -m pi_pipeline.app --halt          # or:  kill -USR1 <pid>
python -m pi_pipeline.app --release       # clear it  (or: kill -USR2 <pid>)

# The behaviour runtime alone, against mocks (idle -> sit -> rest -> sleep -> wake)
python -m pi_pipeline.behavior

# Bring-up readiness checklist (run the moment the Pi + body are wired)
python -m pi_pipeline.doctor              # add --serial to also handshake the BiBoard

# The guided, resumable 14-step hardware bring-up sequence
python -m pi_pipeline.bringup             # --list / --restart / --from <id>

# Guided first movement: one joint at a time, confirmed, then kbalance + a wkF burst
python -m pi_pipeline.link.check_serial firstmove

# Log every serial command sent, then replay the same sequence later
python -m pi_pipeline.app --serial --trace ~/g2_trace.jsonl
python -m pi_pipeline.link.trace replay ~/g2_trace.jsonl --dry-run
```

Every recognised command (and every conversational turn) fires an instant
"heard you" chirp + cue *before* the spoken reply, and G2 never acts silently —
so a misheard command is obvious and you can cancel it ("resume" / "never mind").

**Spoken commands** (handled locally, no Claude call):
- "emergency stop" / "freeze" / "halt" / "stop moving" → latch the freeze;
  "resume" / "as you were" → clear it.
- "shut down" / "power down" / "go dormant" → lie flat, then go dormant.
  "go to sleep" → the lighter curl-up variant.
- "go ahead and look around" / "exploration mode" → arm Tier 1 roam;
  "that's enough" / "come back" → disarm. (Tier 0 stationary attentiveness is
  always on.)
- "forget that" → drop this session's exchanges + facts.
- "enable / disable gir mode" → toggle the opt-in character.
