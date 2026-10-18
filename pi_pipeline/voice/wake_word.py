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
import os
import queue
import threading
import time
from pathlib import Path
from typing import Protocol

from . import mic_gain
from .tts import SPEAKING

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


_SELF_HEARING_TAIL_S = 0.8                # the speaker's echo lingers a moment after the speech ends


def _log_trigger(hit, heard, data, conf, last_speaking, *, ignored) -> None:
    """One line in the wake-trigger log (voice/wake_log.py). Never raises."""
    try:
        import numpy as np
        level = float(np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2)))
    except Exception:  # noqa: BLE001
        level = None
    try:
        from . import wake_log
        wake_log.record_trigger(hit, heard, level=level, confidence=conf, since_own_sound_s=time.monotonic() - last_speaking if last_speaking else None, ignored=ignored, before=words_before(heard, hit))
    except Exception:  # noqa: BLE001
        log.debug("wake log failed", exc_info=True)


def min_confidence() -> float:
    """`G2_WAKE_MIN_CONF`: a wake phrase whose words Kaldi is less sure of than this is ignored (0 = off, the default until a day of logged
    triggers shows where real calls and background talk separate; 2026-10-18: 4 of 7 triggers were people talking nearby, and loudness did not
    separate them, a false one at level 313 and a real one at 314)."""
    import os
    try:
        return max(0.0, float(os.environ.get("G2_WAKE_MIN_CONF", "0") or 0))
    except ValueError:
        return 0.0


def max_words_before() -> int | None:
    """`G2_WAKE_MAX_BEFORE`: ignore a wake phrase with more than this many other words (Kaldi's `[unk]` tokens) in front of it in the same utterance.
    A call is the phrase said on its own; a phrase buried in someone else's sentence is people talking nearby. Unset = off. `wake_log` prints how
    many words preceded real and false triggers, so the value comes from data (the phrase must also be the last thing heard so far: a partial result
    fires as soon as the phrase appears, so only the words BEFORE it are known)."""
    import os
    v = os.environ.get("G2_WAKE_MAX_BEFORE", "").strip()
    try:
        return max(0, int(v)) if v else None
    except ValueError:
        return None


def words_before(heard: str, phrase: str) -> int:
    """How many words precede `phrase` in what Kaldi heard."""
    i = heard.find(phrase)
    return len(heard[:i].split()) if i > 0 else 0


def phrase_confidence(result_json: str, phrase: str) -> float | None:
    """The lowest word confidence of `phrase` in a Kaldi result with words (`SetWords(True)`), or None if the result does not hold it."""
    try:
        words = json.loads(result_json).get("result") or []
    except (ValueError, AttributeError):
        return None
    want = phrase.split()
    seq = [w.get("word", "") for w in words]
    for i in range(len(seq) - len(want) + 1):
        if seq[i:i + len(want)] == want:
            return min(float(words[i + k].get("conf", 0.0)) for k in range(len(want)))
    return None
_QUEUE_BLOCKS = 200                     # about 50 s of audio (4000-sample blocks at 16 kHz)


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
        # ONE microphone stream for the life of the process, never closed: closing a PortAudio stream segfaulted the whole voice service
        # (2026-10-08: sounddevice `close()` from the command window's timeout, a native crash with no Python traceback; the crash report in
        # diag/crashwatch.py pointed at it). The stream feeds a bounded queue; the wake-word detector and the speech recogniser take turns reading it.
        self._stream = None
        self._q: "queue.Queue[bytes]" = queue.Queue(maxsize=_QUEUE_BLOCKS)
        self._handover = False
        self._keeper_on = os.environ.get("G2_MIC_WATCHDOG", "1").strip().lower() not in ("0", "off", "false", "no")

    # -- the stream keeper (backlog B27) ------------------------------------------------------------------------------------------------------
    # The audio callback runs on PortAudio's thread, so a stream that stalls (a USB audio hiccup: still "active", no blocks) is invisible to the
    # wait loop, which only reopens a stream that reports inactive. A util/supervisor.py worker beats whenever a new block has arrived; with no
    # block for `_STALL_S` the supervisor restarts the worker, whose first act is to open a fresh stream (the old one is left alone, never closed).
    _blocks = 0                       # blocks delivered by the callback so far
    _keeper = None
    _keeper_runs = 0
    _STALL_S = 6.0

    @property
    def _lock(self):
        lk = self.__dict__.get("_lock_obj")
        if lk is None:
            lk = self.__dict__.setdefault("_lock_obj", threading.RLock())
        return lk

    def _start_keeper(self) -> None:
        if self._keeper is not None or not getattr(self, "_keeper_on", False):
            return
        from ..util.supervisor import Supervisor, WatchdogConfig
        cfg = WatchdogConfig(heartbeat_timeout_s=self._STALL_S, startup_grace_s=self._STALL_S, restart_window_s=300.0, max_restarts_in_window=8, backoff_base_s=1.0, backoff_max_s=30.0)
        self._keeper = Supervisor("microphone", self._keep, cfg=cfg)
        self._keeper.start()

    def _keep(self, ctx) -> None:
        self._keeper_runs += 1
        if self._keeper_runs > 1:
            with self._lock:
                self._open_stream()
            log.warning("the microphone stopped delivering audio; opened a new stream (restart %d)", self._keeper_runs - 1)
        seen = -1
        while not ctx.stopping.is_set():
            now = self._blocks
            if now != seen:
                seen = now
                ctx.beat()
            ctx.stopping.wait(0.5)

    @property
    def mic_failed(self) -> bool:
        """True once the keeper gave up (too many restarts): the microphone is dead until the service restarts."""
        return bool(self._keeper is not None and self._keeper.given_up)

    def _ensure_stream(self) -> None:
        with self._lock:
            if self._stream is not None and getattr(self._stream, "active", True):
                return
            if self._stream is not None:
                log.warning("the microphone stream stopped; opening a new one (the old one is left alone, not closed)")
            self._open_stream()
        self._start_keeper()

    def _open_stream(self) -> None:
        q: "queue.Queue[bytes]" = queue.Queue(maxsize=_QUEUE_BLOCKS)

        def cb(indata, _frames, _t, status):
            self._blocks += 1
            if status:
                log.debug("audio status: %s", status)
            data = mic_gain.boost(bytes(indata))      # the microphone is very quiet (voice/mic_gain.py)
            try:
                q.put_nowait(data)
            except queue.Full:                         # nobody is reading (G2 is talking or thinking): keep the newest audio
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                except (queue.Empty, queue.Full):
                    pass

        stream = self._sd.RawInputStream(samplerate=self._rate, blocksize=4000, dtype="int16", channels=1, callback=cb)
        stream.start()
        self._stream, self._q = stream, q

    def hand_over(self):
        """After a wake word the microphone stream keeps running, with the audio heard since the wake word waiting in its queue, so the
        speech recogniser can carry on from the same stream (the card cannot be opened twice, and re-opening it loses the first words of a
        command said straight after the wake word). Returns ``(queue, close)`` or None; `close` does nothing: the stream is never closed."""
        self._ensure_stream()
        if not self._handover:                          # a follow-up window (no wake word just now): what the stream heard while G2 talked is stale
            try:
                while True:
                    self._q.get_nowait()
            except queue.Empty:
                pass
        self._handover = False
        return self._q, (lambda: None)

    def _new_recognizer(self):
        rec = self._Recognizer(self._model, self._rate, self._grammar)
        try:
            rec.SetWords(True)                         # per-word confidence in the results (the wake gate)
        except Exception:  # noqa: BLE001
            pass
        return rec

    def wait(self) -> None:
        self._ensure_stream()
        self._handover = False
        q = self._q
        try:
            while True:                                # whatever was heard while G2 talked or thought is not a wake word
                q.get_nowait()
        except queue.Empty:
            pass
        rec = self._new_recognizer()
        last_speaking = 0.0
        while True:
            if SPEAKING.is_set():                      # G2's own voice must not wake him (2026-10-08: the spoken battery alarm triggered "hey buddy")
                last_speaking = time.monotonic()
            q = self._q                                # the keeper may have swapped in a fresh stream
            try:
                data = q.get(timeout=2.0)
            except queue.Empty:
                if not getattr(self._stream, "active", True):
                    self._ensure_stream()
                continue
            if time.monotonic() - last_speaking < _SELF_HEARING_TAIL_S:
                rec = self._new_recognizer()       # drop what was heard while (and just after) G2 spoke
                continue
            final = None
            if rec.AcceptWaveform(data):
                final = rec.Result()
                heard = json.loads(final).get("text", "")
            else:
                heard = json.loads(rec.PartialResult()).get("partial", "")
            heard = heard.lower()
            hit = next((p for p in self._phrases if p in heard), None)
            if hit:
                if final is None:
                    final = rec.FinalResult()          # the partial matched: finish the decode now to get each word's confidence (the words said after it stay queued for the recogniser)
                conf = phrase_confidence(final, hit)
                cap = max_words_before()
                if cap is not None and words_before(heard, hit) > cap:
                    log.info("wake word ignored (%r, %d words before it > %d) text=%r", hit, words_before(heard, hit), cap, heard)
                    _log_trigger(hit, heard, data, conf, last_speaking, ignored=True)
                    rec = self._new_recognizer()
                    continue
                floor = min_confidence()
                if floor and (conf is None or conf < floor):
                    log.info("wake word ignored (%r, confidence %s < %.2f) text=%r", hit, "?" if conf is None else f"{conf:.2f}", floor, heard)
                    _log_trigger(hit, heard, data, conf, last_speaking, ignored=True)
                    rec = self._new_recognizer()
                    continue
                try:                                    # for telling a real call from noise afterwards: how loud the block was, the whole text Kaldi heard, and how long since G2 last made a sound
                    import numpy as np
                    level = float(np.sqrt(np.mean(np.frombuffer(data, dtype=np.int16).astype(np.float32) ** 2)))
                except Exception:  # noqa: BLE001
                    level = -1.0
                log.info("wake word heard (%r) text=%r level=%.0f confidence=%s since_own_sound=%.1fs", hit, heard, level,
                         "?" if conf is None else f"{conf:.2f}", time.monotonic() - last_speaking if last_speaking else -1.0)
                _log_trigger(hit, heard, data, conf, last_speaking, ignored=False)
                self._handover = True                  # keep listening on this stream; the recogniser picks it up
                return


def make_wake_word(mode: str, *, vosk_model_path: str, phrase: str | list[str]) -> WakeWord:
    if mode == "vosk":
        return VoskWakeWord(vosk_model_path, phrase)
    return AlwaysAwake()
