"""Text-to-speech: the `TTS` interface and its implementations.

- `PrintTTS`  - just prints. Zero dependencies; useful in tests.
- `MacTTS`    - macOS built-in `say`. Zero dependencies; makes the dev machine
                actually talk.
- `PiperTTS`  - local neural TTS (Piper). Used on the robot; needs the audio
                deps and a downloaded voice model.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

log = logging.getLogger("g2.tts")


class TTS(Protocol):
    def speak(self, text: str) -> None: ...


class PrintTTS:
    def speak(self, text: str) -> None:
        print(f"\n  G2: {text}\n")


class MacTTS:
    """macOS `say`. `voice` is any installed system voice (see `say -v ?`)."""

    def __init__(self, voice: str = "Daniel", rate_wpm: int = 180):
        if not shutil.which("say"):
            raise RuntimeError("`say` not found -- MacTTS is macOS only")
        self._voice = voice
        self._rate = rate_wpm

    def speak(self, text: str) -> None:
        if not text:
            return
        print(f"\n  G2: {text}\n")
        subprocess.run(["say", "-v", self._voice, "-r", str(self._rate), text], check=False)


class PiperTTS:
    """Local neural TTS via Piper, played through the default output device."""

    def __init__(self, model_path: str):
        from piper.voice import PiperVoice  # piper-tts
        import sounddevice as sd

        p = Path(model_path)
        if not p.exists():
            raise FileNotFoundError(
                f"Piper model not found at {p}. See pi_pipeline/voice/README.md "
                "for how to download a voice."
            )
        self._voice = PiperVoice.load(str(p))
        self._sd = sd
        self._rate = self._voice.config.sample_rate

    def speak(self, text: str) -> None:
        if not text:
            return
        print(f"\n  G2: {text}\n")
        import numpy as np

        chunks = [
            np.frombuffer(b, dtype=np.int16)
            for b in self._voice.synthesize_stream_raw(text)
        ]
        if chunks:
            self._sd.play(np.concatenate(chunks), self._rate)
            self._sd.wait()


def make_tts(mode: str, *, piper_model_path: str) -> TTS:
    if mode == "piper":
        return PiperTTS(piper_model_path)
    if mode == "print":
        return PrintTTS()
    try:
        return MacTTS()
    except RuntimeError:
        log.info("MacTTS unavailable, falling back to PrintTTS")
        return PrintTTS()
