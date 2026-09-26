"""Audio post-processing effects for synthesized speech.

Currently just the robot-voice ring-modulation effect (opt-in via
G2_VOICE_ROBOT_EFFECT / settings.voice_robot_effect) -- multiplies the
synthesized waveform by a low-frequency carrier tone and mixes it back with
the dry signal, giving a metallic/robotic timbre (the classic Cylon/Dalek
technique). Applied after synthesis, so it works with any Piper voice model
without needing a different one.
"""
from __future__ import annotations

import numpy as np

# 45 Hz carrier, 60% wet mix -- picked by ear from a few options (2026-09-24).
ROBOT_CARRIER_HZ = 45.0
ROBOT_MIX = 0.6


def robot_voice(audio: np.ndarray, rate: int, carrier_hz: float = ROBOT_CARRIER_HZ,
                mix: float = ROBOT_MIX) -> np.ndarray:
    """Ring-modulate `audio` (int16 mono PCM) with a `carrier_hz` sine tone,
    mixed `mix` wet / (1-mix) dry. Returns int16 mono PCM at the same rate."""
    if len(audio) == 0:
        return audio
    t = np.arange(len(audio)) / rate
    carrier = np.sin(2 * np.pi * carrier_hz * t)
    dry = audio.astype(np.float64)
    wet = dry * carrier
    peak = np.abs(wet).max()
    if peak > 0:
        wet = wet / peak * np.abs(dry).max()
    out = (1 - mix) * dry + mix * wet
    return np.clip(out, -32768, 32767).astype(np.int16)
