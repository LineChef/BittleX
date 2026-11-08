"""Text-to-speech: the `TTS` interface and its implementations.

- `PrintTTS`  - just prints. Zero dependencies; useful in tests.
- `MacTTS`    - macOS built-in `say`. Zero dependencies; makes the dev machine
                actually talk.
- `PiperTTS`  - local neural TTS (Piper). Used on the robot; needs the audio
                deps and a downloaded voice model.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

log = logging.getLogger("g2.tts")


_G2_WORD = re.compile(r"\bG-?2\b")


def pronounce(text: str) -> str:
    """What the voice is given to say: the robot's name "G2" is spelled "gee two", the soft g that the wake word uses (user, 2026-10-10). A hard-g spelling ("ghee two", forced /g/) was tried first and the Pi's own recognizer heard it as "the to online" (it sounded like "V2");
    "gee two" is heard as "gee to online". The words printed and logged stay "G2"."""
    return _G2_WORD.sub("gee two", text)


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


def _mem_note(label: str) -> None:
    """A memory-log note with the reading beside it (never raises)."""
    try:
        from ..diag import memlog
        memlog.note(label)
    except Exception:  # noqa: BLE001
        pass


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
        import threading
        self._path = str(p)
        self._lock = threading.RLock()
        self._voice = None
        self._last_used = 0.0
        self._load()
        from ..util import mem_budget
        mem_budget.register("speech", self.release, self.idle_for)       # a big model loading elsewhere may release this one while it is idle (util/mem_budget.py)
        self._sd = sd
        self._rate = self._voice.config.sample_rate
        self._style = style or ("current" if robot_effect else "plain")   # a name from effects.VOICES
        self._cache_tag = f"{p.name}:{self._style}"                       # the speech cache is keyed by voice file + style (voice/speech_cache.py)

    def _load(self) -> None:
        """Load the voice if it is not in memory (about 10 s on the Pi Zero 2 W)."""
        from piper.voice import PiperVoice
        from ..util.ort_memory import lean_sessions
        if self._voice is None and self._last_used:                      # a reload (not the first load): make room first, outside our own lock (util/mem_budget.py)
            from ..util import mem_budget
            mem_budget.make_room(90.0, keep="speech")
        with self._lock:
            if self._voice is None:
                with lean_sessions():                           # (arena off: about 20 MB less once it has spoken, same speed; docs/plan-detail/voice-service-memory-2026-11-07.md)
                    self._voice = PiperVoice.load(self._path)
                _mem_note("speech engine loaded")

    @property
    def loaded(self) -> bool:
        return self._voice is not None

    def idle_for(self, seconds: float) -> bool:
        """True if nothing has been synthesised or played for `seconds`."""
        import time as _t
        return _t.monotonic() - self._last_used >= seconds

    def _touch(self) -> None:
        import time as _t
        self._last_used = _t.monotonic()

    def release(self) -> bool:
        """Free the voice's memory (about 155 MB on the Pi) while no uncached sentence is expected (a goal session, an exploration roam: user, 2026-11-07). Lines already in the speech cache
        still play; a line that needs synthesis loads the voice again first. Returns True if it released one."""
        import gc
        with self._lock:
            if self._voice is None:
                return False
            self._voice = None
        gc.collect()
        from ..util.ort_memory import trim_heap
        trim_heap()                                             # (without it the freed model stays in the process: probe on the Pi, 2026-11-07)
        _mem_note("speech engine released")
        return True

    def warm(self) -> None:
        """Load the voice again in the background (the end of a session), so the next conversation reply does not wait for it."""
        import threading
        if self._voice is None:
            threading.Thread(target=lambda: self._load(), name="piper-warm", daemon=True).start()

    def is_cached(self, text: str) -> bool:
        from . import speech_cache
        return speech_cache.load(text, self._cache_tag, self._rate) is not None

    def _synth(self, text: str):
        import numpy as np
        self._touch()
        self._load()                                                      # a released voice comes back first
        chunks = list(self._voice.synthesize(pronounce(text)))
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
        from . import speech_cache
        hit = speech_cache.load(text, self._cache_tag, self._rate)         # a line said before costs no synthesis
        if hit is not None:
            return (text, hit[0], hit[1])
        audio, rate = self._synth(text)
        if audio is None:
            return None
        if rate == self._rate:
            speech_cache.store(text, self._cache_tag, self._rate, audio)
        return (text, audio, rate)

    def play(self, item) -> None:
        if item is None:
            return
        text, audio, rate = item
        print(f"\n  G2: {text}\n")
        from .. import sound_levels
        audio = sound_levels.level(audio)              # his voice at the global volume, whatever level the line was made or cached at
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


def release_speech(tts) -> bool:
    """Free the speech engine's memory for a session that speaks little, if it can be freed (only Piper can). Never raises."""
    try:
        return bool(callable(getattr(tts, "release", None)) and tts.release())
    except Exception:  # noqa: BLE001
        return False


def warm_speech(tts) -> None:
    """Load the speech engine again in the background after `release_speech`. Never raises."""
    try:
        if callable(getattr(tts, "warm", None)):
            tts.warm()
    except Exception:  # noqa: BLE001
        pass
