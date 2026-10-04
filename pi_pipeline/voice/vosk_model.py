"""One shared Vosk model for the whole process.

The wake-word detector and the speech-to-text recogniser both need the same acoustic model, and each used to load
its own copy. Loading is slow and the model is the biggest thing in memory on the Pi (~240 MB loaded), so load it once
per path and hand the same object to every recogniser (recognisers are separate objects; the model itself is read-only).
"""
from __future__ import annotations

import threading

_models: dict[str, object] = {}
_lock = threading.Lock()


def get_model(path: str):
    """The loaded `vosk.Model` for `path`, loading it the first time."""
    from vosk import Model

    key = str(path)
    with _lock:
        if key not in _models:
            _models[key] = Model(key)
        return _models[key]
