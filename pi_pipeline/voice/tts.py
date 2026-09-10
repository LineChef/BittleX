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
    """Local neural TTS via Piper (piper-tts >= 1.7), played through the default
    output device."""

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

    def _synth(self, text: str):
        import numpy as np
        chunks = list(self._voice.synthesize(text))
        if not chunks:
            return None, self._rate
        return np.concatenate([c.audio_int16_array for c in chunks]), chunks[0].sample_rate

    def speak(self, text: str) -> None:
        if not text:
            return
        print(f"\n  G2: {text}\n")
        audio, rate = self._synth(text)
        if audio is None:
            return
        self._sd.play(audio, rate)
        self._sd.wait()

    def synth_to_wav(self, text: str, out_path) -> tuple[int, int]:
        """Synthesise `text` to a mono 16-bit WAV file -- no playback, no
        sounddevice. For offline validation / pre-rendered stock phrases.
        Returns (sample_rate, n_samples)."""
        import wave
        audio, rate = self._synth(text)
        n = 0 if audio is None else len(audio)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            if audio is not None:
                w.writeframes(audio.tobytes())
        return rate, n


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
