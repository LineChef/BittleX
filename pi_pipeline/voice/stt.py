"""Speech-to-text: the `STT` interface and its implementations.

- `TextSTT` - reads a line from stdin. Zero dependencies; the dev-mode input.
- `VoskSTT` - offline recognition from the microphone (Vosk). Records until the
              speaker pauses, then returns the transcript. Used on the robot;
              needs the audio deps and a downloaded model.
"""
from __future__ import annotations

import array
import contextlib
import json
import logging
import os
import queue
import time
import types
from pathlib import Path
from typing import Protocol

from .tts import SPEAKING

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
        from vosk import KaldiRecognizer

        from .vosk_model import get_model

        p = Path(model_path)
        if not p.exists():
            raise FileNotFoundError(
                f"Vosk model not found at {p}. See pi_pipeline/voice/README.md."
            )
        self._sd = sd
        self._rate = sample_rate
        self._silence_blocks = max(1, int(silence_s * sample_rate / 4000))
        self.last_speech_t: float | None = None   # monotonic time the partial transcript last changed (~ end of speech)
        self._model = get_model(str(p))      # shared with the wake-word detector
        self._Recognizer = KaldiRecognizer
        # a second recognizer limited to the stop / shut-down phrases hears the same audio; see pick_command_hypothesis
        self._grammar: str | None = None
        if os.environ.get("G2_STT_COMMAND_GRAMMAR", "1") != "0":
            from .commands import grammar_phrases
            self._grammar = json.dumps([*grammar_phrases(), "[unk]"])

    def listen(self, timeout_s: float | None = None) -> str:
        rec = self._Recognizer(self._model, self._rate)
        grammar = getattr(self, "_grammar", None)
        grec = self._Recognizer(self._model, self._rate, grammar) if grammar else None
        q: "queue.Queue[bytes]" = queue.Queue()

        def finish(full: str) -> str:
            if grec is None:
                return full
            from .commands import pick_command_hypothesis
            heard = json.loads(grec.FinalResult()).get("text", "").strip()
            chosen = pick_command_hypothesis(full, heard)
            if chosen != full:
                log.info("command grammar overrode %r with %r", full, chosen)
            return chosen

        def cb(indata, _frames, _t, status):
            if status:
                log.debug("audio status: %s", status)
            q.put(bytes(indata))

        self.last_speech_t = None
        self.last_info = {}
        peak, blocks, partials, warned = 0, 0, [], False
        last_speaking = -1e9
        said_anything = False
        quiet_blocks = 0          # blocks since the partial transcript last changed
        last_partial = ""
        t_start = time.monotonic()
        source = getattr(self, "audio_source", None)         # the wake-word detector's still-open stream, if any
        handover = source() if callable(source) else None
        if handover is not None:
            q, close = handover                                # audio since the wake word is already queued: no gap
            stream_cm = contextlib.closing(types.SimpleNamespace(close=close))
        else:
            stream_cm = self._sd.RawInputStream(
                samplerate=self._rate, blocksize=4000, dtype="int16",
                channels=1, callback=cb,
            )
        with stream_cm:
            while True:
                try:
                    data = q.get(timeout=0.5)
                except queue.Empty:
                    data = None
                if SPEAKING.is_set():
                    last_speaking = time.monotonic()
                if data is not None and time.monotonic() - last_speaking < 0.8:
                    continue                      # G2's own voice (a spoken alarm) is not the person's command (2026-10-08: "hi battery is low")
                if data is not None:
                    blocks += 1
                    peak = max(peak, max(map(abs, array.array("h", data[: len(data) // 2 * 2])), default=0))
                    self.last_info = {"mic_peak": peak, "blocks": blocks, "partials": partials[-3:]}
                    if grec is not None:
                        grec.AcceptWaveform(data)
                    if rec.AcceptWaveform(data):          # Vosk's own endpointer fired
                        text = json.loads(rec.Result()).get("text", "").strip()
                        if text:
                            return finish(text)
                    partial = json.loads(rec.PartialResult()).get("partial", "").strip()
                    if partial and partial != last_partial:
                        said_anything, quiet_blocks, last_partial = True, 0, partial
                        partials.append(partial)
                        self.last_speech_t = time.monotonic()
                    elif said_anything:
                        # the partial stopped changing (or emptied): you have stopped talking. Vosk's
                        # endpointer would wait 0.75-1.1 s of silence; this ends the turn sooner.
                        quiet_blocks += 1
                        if quiet_blocks >= self._silence_blocks:
                            return finish(json.loads(rec.FinalResult()).get("text", "").strip())
                if not said_anything and not warned and time.monotonic() - t_start > 15.0:
                    warned = True
                    log.warning("still listening after 15 s with no speech heard: %s", self.last_info or "no audio blocks received")
                if (not said_anything and timeout_s is not None
                        and time.monotonic() - t_start > timeout_s):
                    return ""


    @staticmethod
    def transcribe_wav(model_path: str, wav_path: str) -> str:
        """Recognise a mono 16-bit PCM WAV file -- no microphone / sounddevice.
        For offline validation and batch transcription."""
        import wave

        from vosk import KaldiRecognizer

        from .vosk_model import get_model

        m = get_model(str(model_path))
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
