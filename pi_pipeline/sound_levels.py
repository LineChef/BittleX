"""The loudness of every speaker sound G2 makes, in one place, as a percent of MAX volume (user, 2026-10-11: "50%" always means 50% of max).

MAX_PEAK is the loudest clean sample, as a fraction of full scale. Each sound's peak is `MAX_PEAK * percent / 100`. Sounds not listed here (short tone, ack whistle, battery whistle)
keep their own fixed levels in `voice/ack_whistle.py` and `config.py`."""
from __future__ import annotations

MAX_PEAK = 0.95


def at(percent: float) -> float:
    return MAX_PEAK * percent / 100.0


LOSING_HORN = at(80)      # the refusal, the failed command and the fall alarm are the same horn at the same level
CAMERA = at(70)           # the picture-click (voice/shutter.py) and the camera chirps (shutter, recording on, recording off)
SIREN = at(80)            # the red alert siren
PROMPT_TONES = at(70)     # wake chime, beep, boop, close, double beep
API_TICK = at(50)
VOICE_SOUNDS = at(70)     # grunt, sigh, yawn
OOF = at(50)              # the wall-hit oof
TURN_AWAY = at(50)
TA_DA = at(70)
START_HORN = at(100)
