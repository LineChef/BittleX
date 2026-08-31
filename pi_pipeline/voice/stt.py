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
from pathlib import Path
from typing import Protocol

log = logging.getLogger("g2.stt")


class STT(Protocol):
    def listen(self) -> str:
        """Block until the user has said something, return the transcript ('' if nothing)."""
        ...


class TextSTT:
    def listen(self) -> str:
        try:
            return input("  you> ").strip()
        except EOFError:
            return "/quit"


class VoskSTT:
    def __init__(self, model_path: str, sample_rate: int = 16000, silence_s: float = 1.2):
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

    def listen(self) -> str:
        rec = self._Recognizer(self._model, self._rate)
        q: "queue.Queue[bytes]" = queue.Queue()

        def cb(indata, _frames, _t, status):
            if status:
                log.debug("audio status: %s", status)
            q.put(bytes(indata))

        said_anything = False
        trailing_silence = 0
        with self._sd.RawInputStream(
            samplerate=self._rate, blocksize=4000, dtype="int16",
            channels=1, callback=cb,
        ):
            while True:
                data = q.get()
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "").strip()
                    if text:
                        return text
                partial = json.loads(rec.PartialResult()).get("partial", "").strip()
                if partial:
                    said_anything, trailing_silence = True, 0
                elif said_anything:
                    trailing_silence += 1
                    if trailing_silence >= self._silence_blocks:
                        return json.loads(rec.FinalResult()).get("text", "").strip()


def make_stt(mode: str, *, vosk_model_path: str, silence_s: float) -> STT:
    if mode == "vosk":
        return VoskSTT(vosk_model_path, silence_s=silence_s)
    return TextSTT()
