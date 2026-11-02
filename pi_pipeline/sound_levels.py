"""G2's one volume (user, 2026-11-02): every sound he plays on the speaker -- his voice (any style, cached or not), the prompt tones, the chimes, the horns, the
grunts, the alarms, the camera sounds -- comes out at the same level, and the BiBoard buzzer is set to match. No sound has a level of its own, and no setting
changes one sound's level: the only knob is the global volume, `G2_VOLUME` (percent of max, default VOLUME_PERCENT).

Percent always means percent of MAX volume (user, 2026-10-11). MAX_PEAK is the loudest clean sample as a fraction of full scale, so the volume is a peak of
`MAX_PEAK * percent / 100`. Nothing is ever louder than MAX_PERCENT of max (user, 2026-11-01): a higher `G2_VOLUME` is held to it."""
from __future__ import annotations

import os

MAX_PEAK = 0.95
MAX_PERCENT = 75.0        # the cap (user, 2026-11-01)
VOLUME_PERCENT = 65.0     # the global volume (user, 2026-11-02)


def volume_percent() -> float:
    """The global volume, percent of max: `G2_VOLUME` if set (held to 0..MAX_PERCENT), else VOLUME_PERCENT. Read at every sound, so a change in the environment
    needs no restart of anything that only plays sounds."""
    raw = os.environ.get("G2_VOLUME", "").strip()
    try:
        v = float(raw) if raw else VOLUME_PERCENT
    except ValueError:
        v = VOLUME_PERCENT
    return max(0.0, min(v, MAX_PERCENT))


def peak() -> float:
    """The loudest sample of every sound, as a fraction of full scale."""
    return MAX_PEAK * volume_percent() / 100.0


def level(samples):
    """`samples` (any numeric array, int16 or float) scaled so its loudest sample is `peak()`, as int16 mono PCM. Silence stays silence. Every sound goes
    through here on its way to the speaker."""
    import numpy as np
    y = np.asarray(samples, dtype=np.float64)
    m = float(np.abs(y).max()) if y.size else 0.0
    if m == 0.0:
        return np.zeros(y.shape, dtype=np.int16)
    return np.clip(np.round(y / m * peak() * 32767), -32768, 32767).astype(np.int16)


def buzzer_level() -> int:
    """The BiBoard buzzer volume (1-10, `b1`..`b10`) for the global volume, rounded down so the buzzer is never louder than the speaker sounds (65% -> 6).
    Never 0: the board has no silent level short of its mute toggle."""
    return max(1, min(10, int(volume_percent() // 10)))
