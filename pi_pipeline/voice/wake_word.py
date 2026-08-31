"""Wake-word gate: the `WakeWord` interface and its implementations.

Full speech-to-text and Claude calls only happen after the wake word, so the
board isn't constantly streaming audio or hitting the network.

- `AlwaysAwake`   - returns immediately. Dev mode / push-to-talk.
- `VoskWakeWord`  - listens continuously with a tiny Vosk grammar restricted to
                    the wake phrase, so it's cheap on CPU.
"""
from __future__ import annotations

import json
import logging
import queue
from pathlib import Path
from typing import Protocol

log = logging.getLogger("g2.wake")


class WakeWord(Protocol):
    def wait(self) -> None:
        """Block until the wake word is heard."""
        ...


class AlwaysAwake:
    def wait(self) -> None:
        return


class VoskWakeWord:
    def __init__(self, model_path: str, phrase: str, sample_rate: int = 16000):
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model

        p = Path(model_path)
        if not p.exists():
            raise FileNotFoundError(f"Vosk model not found at {p}.")
        self._sd = sd
        self._rate = sample_rate
        self._phrase = phrase.lower().strip()
        self._model = Model(str(p))
        # restrict the recogniser to the wake phrase + [unk] -> very low CPU
        self._grammar = json.dumps([self._phrase, "[unk]"])
        self._Recognizer = KaldiRecognizer

    def wait(self) -> None:
        rec = self._Recognizer(self._model, self._rate, self._grammar)
        q: "queue.Queue[bytes]" = queue.Queue()

        def cb(indata, _frames, _t, status):
            if status:
                log.debug("audio status: %s", status)
            q.put(bytes(indata))

        with self._sd.RawInputStream(
            samplerate=self._rate, blocksize=4000, dtype="int16",
            channels=1, callback=cb,
        ):
            while True:
                data = q.get()
                heard = ""
                if rec.AcceptWaveform(data):
                    heard = json.loads(rec.Result()).get("text", "")
                else:
                    heard = json.loads(rec.PartialResult()).get("partial", "")
                if self._phrase in heard.lower():
                    log.info("wake word heard")
                    return


def make_wake_word(mode: str, *, vosk_model_path: str, phrase: str) -> WakeWord:
    if mode == "vosk":
        return VoskWakeWord(vosk_model_path, phrase)
    return AlwaysAwake()
