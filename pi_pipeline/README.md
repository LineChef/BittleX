# Pi Pipeline

Code that runs on the Raspberry Pi Zero 2 WH mounted on G2: the voice
conversation loop, persistent memory, and (later) vision. Independent of
`rl_training/` — separate venv, separate concerns.

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
  voice/               # Phase 7 — the conversation loop
    conversation.py    # Claude client + turn management (+ memory hook)
    skills.py          # OpenCat skill catalog + serial command mapping
    actuator.py        # Actuator interface: MockActuator / SerialActuator
    tts.py             # TTS interface: MacTTS / PiperTTS / PrintTTS
    stt.py             # STT interface: TextSTT / VoskSTT
    wake_word.py       # WakeWord interface: AlwaysAwake / VoskWakeWord
    cues.py            # listening / thinking / speaking state cues
    loop.py            # the orchestrator
    __main__.py        # entrypoint: python -m pi_pipeline.voice
  personality/         # traits that bias the prompt, behaviour params, and cues
    traits.py          # Trait base + BehaviorParams + the name→class REGISTRY
    curiosity.py       # first concrete trait
    personality.py     # Personality: system_prompt() / behavior_params() / cues()
  behavior/            # what G2 does on its own between conversations
    mode_controller.py # CONVERSE / IDLE / EXPLORE state machine
    explore.py         # wander + investigate-novelty intent (like vision/avoidance)
    novelty.py         # time-decayed memory of what's been seen
  memory/              # Phase 9 — persistent conversation memory (next)
  vision/              # Phase 8 — camera / obstacle detection (hardware-gated)
```

Personality is set via `G2_TRAITS` (e.g. `curiosity=0.85, playfulness=0.4`);
`python -m pi_pipeline.personality` prints the resolved prompt + behaviour knobs.

## Setup

```bash
python3.11 -m venv pi_pipeline/.venv
source pi_pipeline/.venv/bin/activate
pip install -r pi_pipeline/requirements.txt          # core (anthropic, dotenv)
pip install -r pi_pipeline/requirements-audio.txt    # optional: vosk / piper / sounddevice
pip install -r pi_pipeline/requirements-dev.txt      # optional: pytest
```

Copy `.env.example` to `.env` at the repo root and set `ANTHROPIC_API_KEY`.

## Tests

```bash
pi_pipeline/.venv/bin/pytest        # from the repo root; config in pyproject.toml
```

`pi_pipeline/tests/` — no network, audio, or API key. Covers the skill catalogue,
the conversation parse / tool-ack / retry paths (with a stub Anthropic client),
the memory store + recall + decay, and the vision detection model + avoidance
reflex. Run before committing pipeline changes.

## Run

```bash
# Text mode — type instead of speaking, G2 replies via macOS `say`. No audio deps.
python -m pi_pipeline.voice --mode text

# Voice mode — wake word + mic + Vosk STT + Piper TTS (needs the audio deps + models)
python -m pi_pipeline.voice --mode voice

# Either mode: --actuator mock (default) logs skill commands; --actuator serial sends them
```
