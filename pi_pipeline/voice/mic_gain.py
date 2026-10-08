"""Digital gain for the microphone.

The Pi's I2S microphone (Google voiceHAT card, no mixer controls) delivers very little signal: measured 2026-10-08, speech at about 10 cm
sits around 20-55 (offset-corrected RMS) where speech recognisers want a few hundred to a few thousand, and a constant offset of about -900
rides on top of it. `boost()` removes the offset per block and multiplies by `gain`, limited so a loud block (the speaker, a clap) is
scaled down to fit instead of clipping. `G2_MIC_GAIN` sets the gain (default 20; 1 = off).
"""
from __future__ import annotations

import os

DEFAULT_GAIN = 20.0
_FULL_SCALE = 30000.0          # leave headroom below int16's 32767


def gain_from_env() -> float:
    try:
        return max(1.0, float(os.environ.get("G2_MIC_GAIN", DEFAULT_GAIN)))
    except ValueError:
        return DEFAULT_GAIN


def boost(data: bytes, gain: float | None = None) -> bytes:
    """int16 mono PCM in, int16 mono PCM out: offset removed, amplified, never clipped."""
    g = gain_from_env() if gain is None else gain
    if g <= 1.0 or len(data) < 2:
        return data
    import numpy as np
    x = np.frombuffer(data[: len(data) // 2 * 2], dtype=np.int16).astype(np.float32)
    x -= x.mean()
    peak = float(np.abs(x).max())
    if peak > 0:
        g = min(g, _FULL_SCALE / peak)
    return (x * g).astype(np.int16).tobytes()
