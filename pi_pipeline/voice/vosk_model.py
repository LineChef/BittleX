"""One shared Vosk model for the whole process.

The wake-word detector and the speech-to-text recogniser both need the same acoustic model, and each used to load
its own copy. Loading is slow and the model is the biggest thing in memory on the Pi (~240 MB loaded), so load it once
per path and hand the same object to every recogniser (recognisers are separate objects; the model itself is read-only).

The Pi Zero 2 W has 463 MB in all and the voice service runs at about 200 MB, so a load can fail for want of memory; on the Pi that
surfaced only as `'Model' object has no attribute '_handle'` (vosk's destructor after a failed constructor). A failed load is logged with
the free memory and retried once after a garbage-collection pass; every load logs how long it took and what memory was left.
"""
from __future__ import annotations

import gc
import logging
import threading
import time

log = logging.getLogger("g2.vosk")

_models: dict[str, object] = {}
_lock = threading.Lock()
RETRY_WAIT_S = 2.0


def mem_available_mb() -> float | None:
    """MemAvailable from /proc/meminfo in MB, or None off Linux."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / 1024.0, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _load(key: str, model_cls, sleep):
    for attempt in (1, 2):
        before, t0 = mem_available_mb(), time.monotonic()
        try:
            m = model_cls(key)
        except Exception as e:  # noqa: BLE001 -- vosk raises a bare Exception on a failed load
            log.error("speech model load failed (attempt %d): %s; memory available before: %s MB", attempt, e, before)
            if attempt == 2:
                raise
            gc.collect()
            sleep(RETRY_WAIT_S)
            continue
        log.info("speech model loaded in %.1f s; memory available %s MB -> %s MB", time.monotonic() - t0, before, mem_available_mb())
        return m


def get_model(path: str, *, _model_cls=None, _sleep=time.sleep):
    """The loaded `vosk.Model` for `path`, loading it the first time."""
    if _model_cls is None:
        from vosk import Model as _model_cls

    key = str(path)
    with _lock:
        if key not in _models:
            _models[key] = _load(key, _model_cls, _sleep)
        return _models[key]
