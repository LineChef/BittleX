# Pi pipeline code

The code that runs on the Raspberry Pi Zero 2 W mounted on G2: the voice conversation loop, persistent memory, vision, the 80 Hz gait loop, autonomous behavior, diagnostics and power management. It is independent of `rl_training/` (its own venv, no shared code). A map from the docs to each package: [`../docs/code-map.md`](../docs/code-map.md). How the pieces fit: [`../docs/architecture.md`](../docs/architecture.md). What works right now: [`../docs/STATUS.md`](../docs/STATUS.md).

## Design

Every hardware-specific dependency sits behind a small interface with a **mock or laptop implementation and a real one**, so the whole pipeline runs and is tested on a dev machine with no hardware, and moving to the Pi is a configuration change:

- `Actuator`: Dev machine: `MockActuator` (logs the command); On the robot: `SerialActuator` (OpenCat serial: `kwkF`, …)
- `TTS`: Dev machine: `MacTTS` (`say`) / `PiperTTS`; On the robot: `PiperTTS` to the Pi speaker
- `STT`: Dev machine: `TextSTT` (typed) / `VoskSTT`; On the robot: `VoskSTT` on the Pi mic
- `WakeWord`: Dev machine: `AlwaysAwake` / `VoskWakeWord`; On the robot: `VoskWakeWord`
- `Cue`: Dev machine: `LogCue`; On the robot: `LogCue` (buzzer or posture cues later)

`app/` is the only place with real I/O wiring. Every major subsystem is gated by a feature flag (`features.py`, set with `G2_FEATURES`): [`../docs/guides/feature-flags.md`](../docs/guides/feature-flags.md).

## Packages


### Conversation

- [`voice/`](voice/README.md): What it does: Wake word, speech to text, Claude, text to speech; `perform_skill` and `remember` tools; local spoken commands; sounds; README: yes
- [`memory/`](memory/README.md): What it does: SQLite exchange log (BM25 search) and facts G2 saves himself; consolidation; review UI; README: yes
- [`personality/`](personality/README.md): What it does: Composable traits that shape the Claude prompt, the behavior knobs and the cues; README: yes
- [`reflection/`](reflection/README.md): What it does: Session recaps and the idle-time reflection notes; README: yes

### Autonomy

- [`behavior/`](behavior/README.md): What it does: `BehaviorDriver.tick()` returns ordered effects: modes, exploration, idle, sleep, wall avoidance, chirps, emergency stop; README: yes
- [`goals/`](goals/README.md): What it does: Goals the user sets: sessions of attempts, each scored and judged on the Pi to change the next (no API call), the journal, spoken suggestions, the report; README: yes
- [`vision/`](vision/README.md): What it does: Camera feed, detections, pictures, wall distance, recognition by instance; README: yes
- [`gait/`](gait/README.md): What it does: The 80 Hz policy loop, steering trim, stand-up ramp, guards, IMU speed and stall, bench and logging tools; README: yes
- [`link/`](link/README.md): What it does: The shared serial link to the BiBoard, command tracing, `check_serial`; README: yes

### Runtime

- [`app/`](app/README.md): What it does: The whole robot as one program: voice loop and behavior runtime over one link; README: yes
- [`diag/`](diag/README.md): What it does: Per-session event log with a black-box ring buffer, control-loop watchdog, crash reports; README: yes
- [`power/`](power/README.md): What it does: Pi power levers, battery watch, runtime estimate, sleep, power log; README: yes
- [`telemetry/`](telemetry/README.md): What it does: Automatic walk logs, floor labels, hardware epochs, data-type labels; README: yes
- [`util/`](util/README.md): What it does: Disk-space warning, old-log tidy, a worker supervisor; README: yes
- [`head/`](head/README.md): What it does: An MCP tool server for the Petoi AI Head (not part of the running build); README: yes
- [`attachments/`](attachments/__init__.py): What it does: Which attachment is on the neck (`G2_ATTACHMENT` / `g2attach`), the gait policy saved for each, the firmware check; `none` keeps the legacy path ([guide](../docs/guides/attachments.md)); README: yes

### Tests

- `tests/`: What it does: The suite: no network, audio or API key; run it before committing

Top-level modules: `config.py` (settings, read once from the environment and `.env`), `features.py`, `sound_levels.py` (all sound levels as percent of the maximum), `doctor.py` (bring-up readiness checklist), `bringup.py` (guided, resumable bring-up), `benchmark_pi.py` (voice pipeline benchmark), `explore_session.py` and `explore_launch.py` (the supervised exploration session and its voice hand-over), `punt_launch.py` and `goal_launch.py` (the voice hand-overs for one punt and a goal session), and the Pi scripts `setup_pi.sh`, `fetch_models.sh` and `install_voice_service.sh`.

### Built and tested, but not wired in

These modules have unit tests and a design, but no runtime module imports them yet. Each says what would wire it.

- `gait/jam_guard.py`: What it is: Vision-free jam reflex: front-leg strain as a bump sensor; Would be wired by: the feedback-only jam reflex; needs real strain traces
- `behavior/thermal_governor.py`: What it is: Servo-thermal Layer 2: throttle on AMBER, cooldown pose on RED, from the gait-side `ThermalGuard`; Would be wired by: planned
- `behavior/ball_chase.py` (with `vision/ball_finder.py`): What it is: Chase the green treat ball and PUNCH it (the lunge of Petoi's pick with the claw held shut; `--use-pick` for the pick (see below); Would be wired by: its own entry point: `python -m pi_pipeline.behavior.ball_chase [--dry-run]` on the Pi with the voice service stopped; not driven by the behavior layer yet
- `link/recovery.py`: What it is: `RecoveryFSM`: choose between the learned catch, `rc` and `rl` after a fall; Would be wired by: the recovery items in [`../docs/project-plan.md`](../docs/project-plan.md); retest with the Pi in the loop first

- behavior/ball_chase.py (with vision/ball_finder.py): Chase the green treat ball and PUNCH it (the lunge of Petoi's pick with the claw held shut; `--use-pick` for the pick skill) until stopped or after one punch (`--punts 1`): stop, look, step; colour finder, search moves (claw looks with the arm, turns, back-ups; no blind walking unless `--search-walk`), small turns to line the claw up, walks always the default gait policy timed from his own measured pace (`behavior/chase_pace.py`), the claw look check (`behavior/claw_look.py`), voice cues (searching / target acquired / punting), saves pictures with the ball found for the future ball class; punt distance and nudges are settings (`--punt-max`, `--nudge-max`, `--nudges`); tested on synthetic pictures and a fake robot, live attempts on G2, including one punch through the chase on a desk.

  `behavior/punt_test.py`: one punch at each ball distance with the results in a CSV, for dialing the distance in by hand


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

Lint: `pi_pipeline/.venv/bin/ruff check` (from the repo root; installed by `requirements-dev.txt`). Correctness rules only (undefined names, mutable defaults, syntax errors; config in `pyproject.toml`); the pre-commit hook runs it on the staged `.py` files.

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
