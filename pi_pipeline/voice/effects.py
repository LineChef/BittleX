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


# ---------------------------------------------------------------------------------------------------------------------
# More robot-voice building blocks, used to audition voices (2026-10-04). All take and return int16 mono PCM.


def _to_int16(x: np.ndarray) -> np.ndarray:
    return np.clip(x, -32768, 32767).astype(np.int16)


def normalize(audio: np.ndarray, peak: float = 0.9) -> np.ndarray:
    """Scale so the loudest sample is `peak` of full scale (keeps different voices at a comparable loudness)."""
    if len(audio) == 0:
        return audio
    a = audio.astype(np.float64)
    m = np.abs(a).max()
    return audio if m == 0 else _to_int16(a / m * peak * 32767)


def monotone(audio: np.ndarray, rate: int, pitch_hz: float = 110.0, frame: int = 512) -> np.ndarray:
    """Flatten the pitch to a constant `pitch_hz` ("robotisation"): cut the speech into overlapping frames, throw away each
    frame's phase (keeping its spectral shape, which carries the words), and lay the resulting pulses down at a fixed period.
    The timing and vowels are kept but the melody is replaced by a buzz. Lower values sound heavier, higher ones lighter."""
    if len(audio) == 0:
        return audio
    x = audio.astype(np.float64)
    n = len(x)
    hop = max(8, int(round(rate / pitch_hz)))
    win = np.hanning(frame)
    half = frame // 2
    out = np.zeros(n + 2 * frame)
    for centre in range(0, n, hop):
        lo = centre - half
        seg = np.zeros(frame)
        a0, a1 = max(lo, 0), min(lo + frame, n)
        seg[a0 - lo:a1 - lo] = x[a0:a1]
        mag = np.abs(np.fft.rfft(seg * win))
        pulse = np.fft.fftshift(np.fft.irfft(mag, frame)) * win
        o = centre - half + frame               # offset by `frame` so early frames fit in the padded buffer
        out[o:o + frame] += pulse
    out = out[frame:frame + n]
    m = np.abs(out).max()
    if m > 0:
        out = out / m * np.abs(x).max()
    return _to_int16(out)


def comb(audio: np.ndarray, rate: int, delay_ms: float = 5.0, feedback: float = 0.5, mix: float = 0.6) -> np.ndarray:
    """A short feedback delay: a metallic, tube-like ring around every sound. y[n] = x[n] + feedback * y[n - d], computed
    one delay-length block at a time so it stays fast on the Pi."""
    if len(audio) == 0:
        return audio
    x = audio.astype(np.float64)
    d = max(1, int(rate * delay_ms / 1000.0))
    y = x.copy()
    for start in range(d, len(x), d):
        end = min(start + d, len(x))
        y[start:end] = x[start:end] + feedback * y[start - d:end - d]
    return _to_int16((1 - mix) * x + mix * y)


def bitcrush(audio: np.ndarray, bits: int = 6, hold: int = 2) -> np.ndarray:
    """Retro-console grit: keep every `hold`-th sample and round to `bits` bits."""
    if len(audio) == 0:
        return audio
    x = audio.astype(np.float64)
    step = 2.0 ** (16 - bits)
    x = np.round(x / step) * step
    if hold > 1:
        x = np.repeat(x[::hold], hold)[:len(audio)]
    return _to_int16(x)


def pitch_shift(audio: np.ndarray, semitones: float) -> np.ndarray:
    """Speed-change pitch shift (changes length too): negative = lower and slower, a bigger robot."""
    if len(audio) == 0 or semitones == 0:
        return audio
    ratio = 2.0 ** (semitones / 12.0)
    idx = np.arange(0, len(audio) - 1, ratio)
    return _to_int16(np.interp(idx, np.arange(len(audio)), audio.astype(np.float64)))


# Named voices for auditioning. Each is (audio, rate) -> audio.
VOICES = {
    "plain": lambda a, r: a,
    "current": lambda a, r: robot_voice(a, r),                                               # 45 Hz ring mod, 60% wet
    "dalek": lambda a, r: comb(robot_voice(a, r, carrier_hz=35.0, mix=0.85), r, 4.0, 0.35, 0.4),
    "monotone": lambda a, r: monotone(a, r, 110.0),
    "metal": lambda a, r: comb(monotone(a, r, 125.0), r, 5.0, 0.55, 0.55),
    "retro": lambda a, r: robot_voice(bitcrush(a, 6, 2), r, carrier_hz=45.0, mix=0.3),
    "deep": lambda a, r: comb(monotone(pitch_shift(a, -3.0), r, 85.0), r, 7.0, 0.5, 0.5),
}


STYLE_PEAK = 0.95    # loudest sample after styling, as a fraction of full scale


def apply_style(name: str, audio: np.ndarray, rate: int) -> np.ndarray:
    """Apply the named voice from VOICES (unknown names fall back to plain) and level it for playback."""
    fn = VOICES.get(name)
    if fn is None or name == "plain":
        return audio
    return normalize(fn(audio, rate), STYLE_PEAK)
