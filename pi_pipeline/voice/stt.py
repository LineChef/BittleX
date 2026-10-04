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


class VoskSTT:
    def __init__(self, model_path: str, sample_rate: int = 16000, silence_s: float = 0.5):
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

    def listen(self, timeout_s: float | None = None) -> str:
        rec = self._Recognizer(self._model, self._rate)
        q: "queue.Queue[bytes]" = queue.Queue()

        def cb(indata, _frames, _t, status):
            if status:
                log.debug("audio status: %s", status)
            q.put(bytes(indata))

        said_anything = False
        quiet_blocks = 0          # blocks since the partial transcript last changed
        last_partial = ""
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
                    if rec.AcceptWaveform(data):          # Vosk's own endpointer fired
                        text = json.loads(rec.Result()).get("text", "").strip()
                        if text:
                            return text
                    partial = json.loads(rec.PartialResult()).get("partial", "").strip()
                    if partial and partial != last_partial:
                        said_anything, quiet_blocks, last_partial = True, 0, partial
                    elif said_anything:
                        # the partial stopped changing (or emptied): you have stopped talking. Vosk's
                        # endpointer would wait 0.75-1.1 s of silence; this ends the turn sooner.
                        quiet_blocks += 1
                        if quiet_blocks >= self._silence_blocks:
                            return json.loads(rec.FinalResult()).get("text", "").strip()
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
        return VoskSTT(vosk_model_path, silence_s=silence_s)
    return TextSTT()
