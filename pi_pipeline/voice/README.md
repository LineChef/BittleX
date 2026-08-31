# Voice — Phase 7

The conversation loop: **wake word → speech-to-text → Claude → text-to-speech →
optional physical skill**, repeat.

Every stage is an interface with a dev implementation and a robot implementation
(see [`../README.md`](../README.md)), so the whole thing runs on a laptop today.

## Modules

| File | Role |
|---|---|
| `conversation.py` | Anthropic client, rolling history, `perform_skill` tool. Turns a reply into `AssistantTurn(speech, actions)`. Has the seam for Phase 9 memory (`send(..., memory_context=)`). |
| `skills.py` | Curated OpenCat skill catalogue + serial command mapping (`walk_forward` → `kwkF`). |
| `actuator.py` | `MockActuator` (logs) / `SerialActuator` (BiBoard over serial). |
| `tts.py` | `MacTTS` (`say`) / `PiperTTS` / `PrintTTS`. |
| `stt.py` | `TextSTT` (stdin) / `VoskSTT` (mic). |
| `wake_word.py` | `AlwaysAwake` / `VoskWakeWord`. |
| `cues.py` | listening / thinking / speaking indicator (log now; buzzer/posture later). |
| `loop.py` | the orchestrator. |
| `__main__.py` | CLI entrypoint. |

## Run it

```bash
source pi_pipeline/.venv/bin/activate

# Text mode — type, G2 talks back via macOS `say`. Needs only the core deps + an API key.
python -m pi_pipeline.voice --mode text

# Voice mode — wake word + mic + Piper. Needs requirements-audio.txt + the models below.
python -m pi_pipeline.voice --mode voice
```

`--actuator mock` (default) logs skill commands; `--actuator serial` sends them
(hardware only). Say "goodbye g2" or Ctrl+C to stop.

## Audio diagnostics (no API key)

```bash
python -m pi_pipeline.voice.check_audio devices     # list mic / speaker devices
python -m pi_pipeline.voice.check_audio wake        # loop: prints each time the wake word fires
python -m pi_pipeline.voice.check_audio stt         # transcribe one spoken utterance + timing
python -m pi_pipeline.voice.check_audio tts "text"  # speak with the current voice
python -m pi_pipeline.voice.check_audio tts "text" --model models/piper/en_US-amy-medium.onnx
```

Use `wake` to tune the wake phrase: if "hey gee two" mis-triggers or won't catch,
set `G2_WAKE_WORD` in `.env` to something more distinct. Use `stt` to tune
`G2_STT_SILENCE_S` (the pause that ends a phrase).

## Voices

Piper voices (`en`) live at
[`rhasspy/piper-voices`](https://huggingface.co/rhasspy/piper-voices/tree/main/en).
Tiers: `low` (16 kHz, small, buzzy), `medium` (22 kHz, the sweet spot for the
Pi), `high` (bigger + slower, likely too heavy for a Pi Zero 2 W). Downloaded
candidates in `models/piper/`:

| Model | Character |
|---|---|
| `en_US-ryan-low` | current default; warm male but low-tier, noticeably synthetic |
| `en_US-ryan-medium` | same voice, clean; warm, casual, relaxed — good companion fit |
| `en_US-amy-medium` | female, bright and friendly, upbeat |
| `en_US-hfc_male-medium` | male, very natural / "real person", personality-neutral |
| `en_GB-alan-medium` | British male, composed, a bit of gravitas — fun for a small robot |

Current default: **`en_GB-alan-medium`**. Change it by setting `PIPER_MODEL_PATH` in `.env`, e.g.
`PIPER_MODEL_PATH=models/piper/en_US-ryan-medium.onnx`. To try others, download
`<name>.onnx` + `<name>.onnx.json` from the repo above into `models/piper/`.

## Models for voice mode

Not committed (large). Download into `models/` at the repo root:

**Vosk** (STT + wake word), ~40 MB:
```bash
mkdir -p models && cd models
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip && mv vosk-model-small-en-us-0.15 vosk
```

**Piper** (TTS), ~60 MB for a low-quality voice:
```bash
mkdir -p models/piper && cd models/piper
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/low/en_US-ryan-low.onnx
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/low/en_US-ryan-low.onnx.json
```

`sounddevice` needs PortAudio — macOS `brew install portaudio`, Pi
`sudo apt install libportaudio2`.

### Verified on the dev machine (macOS, 2026-08-31)

`vosk 0.3.44`, `piper-tts 1.7.0`, `sounddevice 0.5.6`, `onnxruntime 1.23.2`.
Checked without a live mic: Piper synthesises + plays through the default output;
Vosk transcribes a Piper-synthesised phrase back verbatim; `VoskSTT` /
`VoskWakeWord` construct against `models/vosk`. Still needs a human at the mic to
exercise live capture, the wake-word trigger, and the silence-detection timing —
and an `ANTHROPIC_API_KEY` for the Claude leg.

## Still to do in Phase 7

- Buzzer / posture cue implementations (`cues.py`) — hardware.
- `SerialActuator` end-to-end test + `XS` "Serial-2" mode on the BiBoard — hardware.
- Confirm the loop coexists with OpenCat's 35+ built-in voice commands (they're a
  separate firmware path; our commands go over serial).
- Thread health-monitoring / auto-restart once mic + serial threads are real.
