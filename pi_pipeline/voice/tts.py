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


# set while a spoken sentence is playing, so the short signal sounds (api_tone) wait instead of cutting the speech off
import threading as _threading
SPEAKING = _threading.Event()


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

    def __init__(self, model_path: str, robot_effect: bool = False, style: str | None = None):
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
        self._style = style or ("current" if robot_effect else "plain")   # a name from effects.VOICES

    def _synth(self, text: str):
        import numpy as np
        chunks = list(self._voice.synthesize(text))
        if not chunks:
            return None, self._rate
        audio = np.concatenate([c.audio_int16_array for c in chunks])
        rate = chunks[0].sample_rate
        if self._style != "plain":
            from .effects import apply_style
            audio = apply_style(self._style, audio, rate)
        return audio, rate

    def prepare(self, text: str):
        """Synthesise `text` without playing it: returns an item for `play()`, or None. Lets the loop synthesise the
        next sentence while the previous one is still playing."""
        if not text:
            return None
        audio, rate = self._synth(text)
        return None if audio is None else (text, audio, rate)

    def play(self, item) -> None:
        if item is None:
            return
        text, audio, rate = item
        print(f"\n  G2: {text}\n")
        SPEAKING.set()
        try:
            self._sd.play(audio, rate)
            self._sd.wait()
        finally:
            SPEAKING.clear()

    def speak(self, text: str) -> None:
        self.play(self.prepare(text))

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


def make_tts(mode: str, *, piper_model_path: str, robot_effect: bool = False, style: str | None = None) -> TTS:
    if mode == "piper":
        return PiperTTS(piper_model_path, robot_effect=robot_effect, style=style)
    if mode == "print":
        return PrintTTS()
    try:
        return MacTTS()
    except RuntimeError:
        log.info("MacTTS unavailable, falling back to PrintTTS")
        return PrintTTS()
