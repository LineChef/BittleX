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

## Still to do in Phase 7

- Buzzer / posture cue implementations (`cues.py`) — hardware.
- `SerialActuator` end-to-end test + `XS` "Serial-2" mode on the BiBoard — hardware.
- Confirm the loop coexists with OpenCat's 35+ built-in voice commands (they're a
  separate firmware path; our commands go over serial).
- Thread health-monitoring / auto-restart once mic + serial threads are real.
