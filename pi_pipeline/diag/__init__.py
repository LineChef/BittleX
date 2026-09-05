"""Structured session logging + black-box ring buffer for hardware debugging.
See docs/research/hardware-diagnostics.md and pi_pipeline/diag/core.py."""
from __future__ import annotations

from .core import Diag, DiagLogHandler, RingBuffer, bridge_stdlib_logging, diag

__all__ = ["diag", "Diag", "RingBuffer", "DiagLogHandler", "bridge_stdlib_logging", "event"]


def event(subsystem: str, level: str, name: str, **kv):
    """Shorthand for diag.event(...)."""
    diag.event(subsystem, level, name, **kv)
