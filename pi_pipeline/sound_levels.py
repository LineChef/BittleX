"""The loudness of every speaker sound G2 makes, in one place, as a percent of MAX volume (user, 2026-10-11: "50%" always means 50% of max).

MAX_PEAK is the loudest clean sample, as a fraction of full scale. Each sound's peak is `MAX_PEAK * percent / 100`. Sounds not listed here (short tone, ack whistle, battery whistle)
keep their own fixed levels in `voice/ack_whistle.py` and `config.py`."""
from __future__ import annotations

MAX_PEAK = 0.95
MAX_PERCENT = 75.0        # no sound G2 makes is louder than this (user, 2026-11-01); `at()` clamps to it, and so does `limit()` for a level set from the environment


def at(percent: float) -> float:
    return MAX_PEAK * min(percent, MAX_PERCENT) / 100.0


def limit(peak: float) -> float:
    """A peak (fraction of full scale) held to the cap: for a level a person can set from the environment."""
    return min(peak, at(MAX_PERCENT))


LOSING_HORN = at(75)      # the refusal, the failed command and the fall alarm are the same horn at the same level
CAMERA = at(70)           # the picture-click (voice/shutter.py) and the camera chirps (shutter, recording on, recording off)
SIREN = at(75)            # the red alert siren
PROMPT_TONES = at(70)     # wake chime, beep, boop, close, double beep
API_TICK = at(50)
VOICE_SOUNDS = at(70)     # grunt, sigh, yawn
OOF = at(50)              # the wall-hit oof
TURN_AWAY = at(50)
TA_DA = at(70)
START_HORN = at(75)       # the exploration start horn (user, 2026-11-01: 90%, then the 75% cap; it was 100%)
SPEECH = at(75)           # his speaking voice after the robot effect (user, 2026-11-01: 80%, then the 75% cap; it was 100%, then 90%); the plain voice (G2_VOICE_ROBOT_EFFECT=0) is not levelled
