"""Speech-to-text: the `STT` interface and its implementations.

- `TextSTT` - reads a line from stdin. Zero dependencies; the dev-mode input.
- `VoskSTT` - offline recognition from the microphone (Vosk). Records until the
              speaker pauses, then returns the transcript. Used on the robot;
              needs the audio deps and a downloaded model.
"""
from __future__ import annotations

import json
import logging
import queue
import time
from pathlib import Path
from typing import Protocol

log = logging.getLogger("g2.stt")


class STT(Protocol):
    def listen(self, timeout_s: float | None = None) -> str:
        """Block until the user has said something, return the transcript ('' if
        nothing). If `timeout_s` is set and no speech has *started* within that
        many seconds, give up and return '' (used for the follow-up window)."""
        ...


class TextSTT:
    def listen(self, timeout_s: float | None = None) -> str:
        try:
            return input("  you> ").strip()
        except EOFError:
            return "/quit"


def pick_control_phrase(text: str, grammar_text: str, phrases) -> str:
    """Prefer the grammar-restricted result when it is one of the control phrases.

    The open-vocabulary pass mishears short control phrases ("command mode off" ->
    "man load off"); a second pass limited to a handful of phrases is far more accurate
    for those, and falls back to `[unk]`/empty for anything else."""
    g = (grammar_text or "").strip()
    return g if g in set(phrases) else text


class VoskSTT:
    def __init__(self, model_path: str, sample_rate: int = 16000, silence_s: float = 1.2,
                 control_phrases=()):
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model

        p = Path(model_path)
        if not p.exists():
            raise FileNotFoundError(
                f"Vosk model not found at {p}. See pi_pipeline/voice/README.md."
            )
        self._sd = sd
        self._rate = sample_rate
        self._silence_blocks = max(1, int(silence_s * sample_rate / 4000))
        self._model = Model(str(p))
        self._Recognizer = KaldiRecognizer
        self._control = tuple(control_phrases)
        self._grammar = json.dumps(list(self._control) + ["[unk]"]) if self._control else None

    def _refine(self, text: str, audio: bytearray) -> str:
        """Second, grammar-restricted pass over the same audio for the control phrases."""
        if not self._grammar or not audio:
            return text
        rec = self._Recognizer(self._model, self._rate, self._grammar)
        rec.AcceptWaveform(bytes(audio))
        g = json.loads(rec.FinalResult()).get("text", "")
        picked = pick_control_phrase(text, g, self._control)
        if picked != text:
            log.info("control phrase %r (open vocabulary heard %r)", picked, text)
        return picked

    def listen(self, timeout_s: float | None = None) -> str:
        rec = self._Recognizer(self._model, self._rate)
        q: "queue.Queue[bytes]" = queue.Queue()

        def cb(indata, _frames, _t, status):
            if status:
                log.debug("audio status: %s", status)
            q.put(bytes(indata))

        said_anything = False
        trailing_silence = 0
        audio = bytearray()
        t_start = time.monotonic()
        with self._sd.RawInputStream(
            samplerate=self._rate, blocksize=4000, dtype="int16",
            channels=1, callback=cb,
        ):
            while True:
                try:
                    data = q.get(timeout=0.5)
                except queue.Empty:
                    data = None
                if data is not None:
                    audio.extend(data)
                    if rec.AcceptWaveform(data):
                        text = json.loads(rec.Result()).get("text", "").strip()
                        if text:
                            return self._refine(text, audio)
                    partial = json.loads(rec.PartialResult()).get("partial", "").strip()
                    if partial:
                        said_anything, trailing_silence = True, 0
                    elif said_anything:
                        trailing_silence += 1
                        if trailing_silence >= self._silence_blocks:
                            return self._refine(json.loads(rec.FinalResult()).get("text", "").strip(), audio)
                if (not said_anything and timeout_s is not None
                        and time.monotonic() - t_start > timeout_s):
                    return ""


    @staticmethod
    def transcribe_wav(model_path: str, wav_path: str) -> str:
        """Recognise a mono 16-bit PCM WAV file -- no microphone / sounddevice.
        For offline validation and batch transcription."""
        import wave

        from vosk import KaldiRecognizer, Model

        m = Model(str(model_path))
        with wave.open(str(wav_path), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError("transcribe_wav wants mono 16-bit PCM")
            rec = KaldiRecognizer(m, w.getframerate())
            while True:
                data = w.readframes(4000)
                if not data:
                    break
                rec.AcceptWaveform(data)
            return json.loads(rec.FinalResult()).get("text", "").strip()


def make_stt(mode: str, *, vosk_model_path: str, silence_s: float) -> STT:
    if mode == "vosk":
        from .commands import CONTROL_PHRASES
        return VoskSTT(vosk_model_path, silence_s=silence_s, control_phrases=CONTROL_PHRASES)
    return TextSTT()
