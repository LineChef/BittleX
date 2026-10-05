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


def _parse_phrases(phrase: str | list[str]) -> list[str]:
    """Multiple wake phrases, comma-separated in one string (`G2_WAKE_WORD`) or
    already a list -- any one of them wakes G2. Lower-cased, stripped, empties
    dropped, de-duplicated (order-preserving)."""
    raw = phrase.split(",") if isinstance(phrase, str) else phrase
    seen: dict[str, None] = {}
    for p in raw:
        p = p.lower().strip()
        if p:
            seen[p] = None
    return list(seen)


class VoskWakeWord:
    def __init__(self, model_path: str, phrase: str | list[str], sample_rate: int = 16000):
        import sounddevice as sd
        from vosk import KaldiRecognizer

        from .vosk_model import get_model

        p = Path(model_path)
        if not p.exists():
            raise FileNotFoundError(f"Vosk model not found at {p}.")
        self._sd = sd
        self._rate = sample_rate
        self._phrases = _parse_phrases(phrase)
        if not self._phrases:
            raise ValueError("no wake phrase given (G2_WAKE_WORD is empty)")
        self._model = get_model(str(p))      # shared with the speech-to-text recogniser
        # restrict the recogniser to the wake phrases + [unk] -> very low CPU
        self._grammar = json.dumps([*self._phrases, "[unk]"])
        self._Recognizer = KaldiRecognizer
        self._live = None

    def _close_live(self) -> None:
        live, self._live = self._live, None
        if live is not None:
            try:
                live[0].stop()
                live[0].close()
            except Exception:  # noqa: BLE001
                log.debug("closing the wake-word stream failed", exc_info=True)

    def hand_over(self):
        """After a wake word the microphone stream is left open, with the audio heard since the wake word waiting in its queue, so the
        speech recogniser can carry on from the same stream (the card cannot be opened twice, and closing and re-opening it loses the first
        words of a command said straight after the wake word). Returns ``(queue, close)`` or None."""
        live = self._live
        if live is None:
            return None
        self._live = None
        stream, q = live

        def close():
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                log.debug("closing the handed-over stream failed", exc_info=True)

        return q, close

    def wait(self) -> None:
        self._close_live()                    # a stream nobody took over last time
        rec = self._Recognizer(self._model, self._rate, self._grammar)
        q: "queue.Queue[bytes]" = queue.Queue()

        def cb(indata, _frames, _t, status):
            if status:
                log.debug("audio status: %s", status)
            q.put(bytes(indata))

        stream = self._sd.RawInputStream(
            samplerate=self._rate, blocksize=4000, dtype="int16",
            channels=1, callback=cb,
        )
        stream.start()
        try:
            while True:
                data = q.get()
                if rec.AcceptWaveform(data):
                    heard = json.loads(rec.Result()).get("text", "")
                else:
                    heard = json.loads(rec.PartialResult()).get("partial", "")
                heard = heard.lower()
                hit = next((p for p in self._phrases if p in heard), None)
                if hit:
                    log.info("wake word heard (%r)", hit)
                    self._live = (stream, q)      # keep listening on this stream; the recogniser picks it up
                    return
        finally:
            if self._live is None:
                stream.stop()
                stream.close()


def make_wake_word(mode: str, *, vosk_model_path: str, phrase: str | list[str]) -> WakeWord:
    if mode == "vosk":
        return VoskWakeWord(vosk_model_path, phrase)
    return AlwaysAwake()
