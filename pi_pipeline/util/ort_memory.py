"""onnxruntime memory settings for the Pi (user, 2026-11-07: reduce what the voice service uses).

Measured on the Pi Zero 2 W (docs/plan-detail/voice-service-memory-2026-11-07.md): Piper's session grew from 88 MB at load to about 175 MB after the first sentence because
onnxruntime's CPU memory arena keeps what it grabbed; with the arena and the memory-pattern planner off it stops at about 155 MB with the same speed (2.6 s against 2.7 s for a sentence).
`G2_ORT_ARENA=1` puts the old behaviour back.
"""
from __future__ import annotations

import contextlib
import os


def arena_off() -> bool:
    return os.environ.get("G2_ORT_ARENA", "").strip().lower() not in ("1", "on", "true", "yes")


def apply(session_options):
    """Switch the arena and the memory-pattern planner off on a SessionOptions (unless G2_ORT_ARENA=1). Returns it."""
    if arena_off():
        session_options.enable_cpu_mem_arena = False
        session_options.enable_mem_pattern = False
    return session_options


@contextlib.contextmanager
def lean_sessions():
    """While open, every `onnxruntime.InferenceSession(...)` that does not bring its own options gets the lean ones (for libraries that build their own session, such as Piper)."""
    import onnxruntime as ort
    orig = ort.InferenceSession
    if not arena_off():
        yield
        return

    def lean(path, sess_options=None, *a, **kw):
        return orig(path, apply(sess_options or ort.SessionOptions()), *a, **kw)
    ort.InferenceSession = lean
    try:
        yield
    finally:
        ort.InferenceSession = orig
