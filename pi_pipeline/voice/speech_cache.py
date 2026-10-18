"""A disk cache of synthesised speech, so a line G2 has said before costs no CPU the next time (speech-lag fix, 2026-10-18).

Piper runs about 1.7x slower than real time on the Pi Zero 2 W, and during exploration the same cores also run the 80 Hz gait loop and the camera, so a
three-second narration line took many seconds to be heard after it was decided. Narration is a small set of fixed sentences (`behavior/narrator.py`), so the
synthesised audio (after the voice effect) is stored once and replayed from disk. Short lines only; the folder is pruned to the newest `MAX_FILES`.

    ~/.cache/g2/speech/<hash>.npy     (`G2_SPEECH_CACHE` = a folder, or `off`)

The key holds the text, the voice model file, the voice style and the sample rate, so changing any of them misses the cache instead of playing the old voice.
Every function is best-effort: a cache problem means a normal live synthesis, never a failure.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger("g2.speech_cache")

DEFAULT_DIR = "~/.cache/g2/speech"
MAX_CHARS = 140
MAX_FILES = 400


def cache_dir() -> Path | None:
    v = os.environ.get("G2_SPEECH_CACHE", DEFAULT_DIR).strip()
    if v.lower() in ("", "off", "0", "false", "no"):
        return None
    return Path(os.path.expanduser(v))


def _key(text: str, tag: str, rate: int) -> str:
    return hashlib.sha256(f"{tag}|{rate}|{text}".encode()).hexdigest()[:32]


def load(text: str, tag: str, rate: int):
    """The cached ``(audio, sample_rate)`` for `text`, or None."""
    d = cache_dir()
    if d is None or len(text) > MAX_CHARS:
        return None
    p = d / f"{_key(text, tag, rate)}.npy"
    try:
        import numpy as np
        arr = np.load(p, allow_pickle=False)           # never unpickle
        os.utime(p)                                    # recently used: kept by the prune
        return arr, rate
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001 -- a damaged file is a miss
        log.debug("speech cache read failed", exc_info=True)
        return None


def store(text: str, tag: str, rate: int, audio) -> None:
    d = cache_dir()
    if d is None or len(text) > MAX_CHARS:
        return
    try:
        import numpy as np
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{_key(text, tag, rate)}.npy"
        tmp = p.with_suffix(".tmp")
        with tmp.open("wb") as f:
            np.save(f, np.asarray(audio), allow_pickle=False)
        os.replace(tmp, p)                             # a half-written file is never read
        _prune(d)
    except Exception:  # noqa: BLE001
        log.debug("speech cache write failed", exc_info=True)


def _prune(d: Path) -> None:
    files = sorted(d.glob("*.npy"), key=lambda f: f.stat().st_mtime)
    for f in files[:-MAX_FILES] if len(files) > MAX_FILES else ():
        try:
            f.unlink()
        except OSError:
            pass


def prewarm(tts, texts, *, nice: int = 10, stop=None) -> int:
    """Synthesise (and so cache) every text not cached yet, at low priority. Returns how many were made. `tts` needs ``prepare(text)``."""
    made = 0
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), nice)       # Linux: the nice value applies to this thread only
    except (AttributeError, OSError):
        pass                                           # not Linux, or not allowed: run at normal priority
    for t in texts:
        if stop is not None and stop.is_set():
            break
        try:
            if getattr(tts, "is_cached", lambda _t: False)(t):
                continue
            tts.prepare(t)
            made += 1
        except Exception:  # noqa: BLE001
            log.debug("prewarm failed for %r", t, exc_info=True)
    return made
