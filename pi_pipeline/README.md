# Pi pipeline code

The code that runs on the Raspberry Pi Zero 2 W mounted on G2: the voice conversation loop, persistent memory, vision, the 80 Hz gait loop, autonomous behavior, diagnostics and power management. It is independent of `rl_training/` (its own venv, no shared code). A map from the docs to each package: [`../docs/code-map.md`](../docs/code-map.md). How the pieces fit: [`../docs/architecture.md`](../docs/architecture.md). What works right now: [`../docs/STATUS.md`](../docs/STATUS.md).

## Design

Every hardware-specific dependency sits behind a small interface with a **mock or laptop implementation and a real one**, so the whole pipeline runs and is tested on a dev machine with no hardware, and moving to the Pi is a configuration change:

| Interface | Dev machine | On the robot |
|---|---|---|
| `Actuator` | `MockActuator` (logs the command) | `SerialActuator` (OpenCat serial: `kwkF`, …) |
| `TTS` | `MacTTS` (`say`) / `PiperTTS` | `PiperTTS` to the Pi speaker |
| `STT` | `TextSTT` (typed) / `VoskSTT` | `VoskSTT` on the Pi mic |
| `WakeWord` | `AlwaysAwake` / `VoskWakeWord` | `VoskWakeWord` |
| `Cue` | `LogCue` | `LogCue` (buzzer or posture cues later) |

`app/` is the only place with real I/O wiring. Every major subsystem is gated by a feature flag (`features.py`, set with `G2_FEATURES`): [`../docs/guides/feature-flags.md`](../docs/guides/feature-flags.md).

## Packages


### Conversation

| Package | What it does | README |
|---|---|---|
| [`voice/`](voice/README.md) | Wake word, speech to text, Claude, text to speech; `perform_skill` and `remember` tools; local spoken commands; sounds | yes |
| [`memory/`](memory/README.md) | SQLite exchange log (BM25 search) and facts G2 saves himself; consolidation; review UI | yes |
| [`personality/`](personality/README.md) | Composable traits that shape the Claude prompt, the behavior knobs and the cues | yes |
| [`reflection/`](reflection/README.md) | Session recaps and the idle-time reflection notes | yes |

### Autonomy

| Package | What it does | README |
|---|---|---|
| [`behavior/`](behavior/README.md) | `BehaviorDriver.tick()` returns ordered effects: modes, exploration, idle, sleep, wall avoidance, chirps, emergency stop | yes |
| [`vision/`](vision/README.md) | Camera feed, detections, pictures, wall distance, recognition by instance | yes |
| [`gait/`](gait/README.md) | The 80 Hz policy loop, steering trim, stand-up ramp, guards, IMU speed and stall, bench and logging tools | yes |
| [`link/`](link/README.md) | The shared serial link to the BiBoard, command tracing, `check_serial` | yes |

### Runtime

| Package | What it does | README |
|---|---|---|
| [`app/`](app/README.md) | The whole robot as one program: voice loop and behavior runtime over one link | yes |
| [`diag/`](diag/README.md) | Per-session event log with a black-box ring buffer, control-loop watchdog, crash reports | yes |
| [`power/`](power/README.md) | Pi power levers, battery watch, runtime estimate, sleep, power log | yes |
| [`telemetry/`](telemetry/README.md) | Automatic walk logs, floor labels, hardware epochs, data-type labels | yes |
| [`util/`](util/README.md) | Disk-space warning, old-log tidy, a worker supervisor | yes |
| [`head/`](head/README.md) | An MCP tool server for the Petoi AI Head (not part of the running build) | yes |

### Tests

| Package | What it does | README |
|---|---|---|
| `tests/` | The suite: no network, audio or API key; run it before committing | |

Top-level modules: `config.py` (settings, read once from the environment and `.env`), `features.py`, `sound_levels.py` (all sound levels as percent of the maximum), `doctor.py` (bring-up readiness checklist), `bringup.py` (guided, resumable bring-up), `benchmark_pi.py` (voice pipeline benchmark), `explore_session.py` and `explore_launch.py` (the supervised exploration session and its voice hand-over), and the Pi scripts `setup_pi.sh`, `fetch_models.sh` and `install_voice_service.sh`.

### Built and tested, but not wired in

These modules have unit tests and a design, but no runtime module imports them yet. Each says what would wire it.

| Module | What it is | Would be wired by |
|---|---|---|
| `gait/jam_guard.py` | Vision-free jam reflex: front-leg strain as a bump sensor | the feedback-only jam reflex, [B9a](../docs/planned/behavior-ideas.md); needs real strain traces |
| `behavior/thermal_governor.py` | Servo-thermal Layer 2: throttle on AMBER, cooldown pose on RED, from the gait-side `ThermalGuard` | [B26](../docs/planned/behavior-ideas.md) |
| `util/supervisor.py` | Restarts a worker thread that crashes, returns or stops heart-beating, with backoff | [B27](../docs/planned/behavior-ideas.md) |
| `link/recovery.py` | `RecoveryFSM`: choose between the learned catch, `rc` and `rl` after a fall | the recovery items in [`../docs/project-plan.md`](../docs/project-plan.md); retest with the Pi in the loop first |
| `behavior/diag_bridge.py` | Turns driver `DIAG` effects into diagnostic events | wiring into `app/` |
| `vision/terrain_feature.py` | A terrain signal for the walking policy's own observation | closed with vision-in-the-gait: [`../docs/archive/rl/vision-in-gait.md`](../docs/archive/rl/vision-in-gait.md) |

## Setup

```bash
python3.11 -m venv pi_pipeline/.venv
source pi_pipeline/.venv/bin/activate
pip install -r pi_pipeline/requirements.txt          # core (anthropic, dotenv, pyserial)
pip install -r pi_pipeline/requirements-audio.txt    # optional: vosk / piper / sounddevice
pip install -r pi_pipeline/requirements-dev.txt      # pytest
pip install -r pi_pipeline/requirements-vision.txt   # optional: Pillow, for tools/camera_preview.py
```

Copy `.env.example` to `.env` at the repo root and set `ANTHROPIC_API_KEY`. Set a spend limit on the key first: [`../docs/guides/api-setup.md`](../docs/guides/api-setup.md). The Pi's OS setup: [`../docs/guides/pi-bring-up.md`](../docs/guides/pi-bring-up.md). Voice models: [`../docs/guides/models.md`](../docs/guides/models.md).

## Tests

```bash
pi_pipeline/.venv/bin/pytest        # from the repo root; config in pyproject.toml
```

The suite needs no network, audio or key. One live-API check is skipped unless `G2_LIVECHECK=1` (billed). Package-style imports mean it must run from the repo root, not from inside `pi_pipeline/`.

## Run

```bash
python -m pi_pipeline.voice --mode text     # type instead of speaking; G2 replies via `say`; no audio deps
python -m pi_pipeline.voice --mode voice    # wake word + mic + Vosk + Piper (needs the audio deps and models)
python -m pi_pipeline.app                   # the whole robot: voice loop + behavior runtime, mocked I/O
python -m pi_pipeline.app --serial          # talk to the real BiBoard
python -m pi_pipeline.app --bench           # on the calibration stand: no autonomous movement
python -m pi_pipeline.app --halt            # emergency stop a running app (or kill -USR1 <pid>)
python -m pi_pipeline.app --release         # clear it (or kill -USR2 <pid>)
python -m pi_pipeline.behavior              # the behavior runtime alone, against mocks
python -m pi_pipeline.doctor [--serial]     # bring-up readiness checklist
python -m pi_pipeline.bringup               # guided, resumable hardware bring-up (--list, --restart, --from <id>)
python -m pi_pipeline.link.check_serial firstmove    # guided first movement, one joint at a time
python -m pi_pipeline.link.check_serial allmoves     # full movement sweep, logging voltage and latency
python -m pi_pipeline.app --serial --trace ~/g2_trace.jsonl    # log every serial command, replay later with link.trace
python -m pi_pipeline.personality           # print the resolved prompt and behavior knobs
```

Every recognised command and every conversational turn fires an instant "heard you" cue before the spoken reply, and G2 never acts silently, so a misheard command is obvious and can be cancelled ("resume", "never mind"). The spoken commands that never call Claude, and the conversational skill catalogue: [`../docs/guides/voice-commands.md`](../docs/guides/voice-commands.md). Personality is set with `G2_TRAITS` and the opt-in character mode with `G2_CHARACTER`.
