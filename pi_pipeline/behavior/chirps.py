"""Emotive chirp vocabulary (behaviour-ideas B5).

Short buzzer melodies over the OpenCat `b<tone> <ms> ...` serial token, one per
mood. Cheap personality, and doubles as the Phase 7 voice state cue (listening /
thinking / speaking).

  chirp_for(ChirpMood.HAPPY)  -> "b24 6 27 6 31 8"   (a serial string via opencat.beep)
  Chirper(...).maybe(mood)    -> the string, or None if still in cooldown

Tone/duration values are a FIRST CUT -- tune by ear on the real buzzer. Tone is
an index into the firmware's note table; duration is in the firmware's ~10 ms
units.
"""
from __future__ import annotations

import time
from enum import Enum

from ..link import opencat


class ChirpMood(Enum):
    HAPPY = "happy"          # greeting a person, a task done, recognition
    CONFUSED = "confused"    # didn't parse / can't classify / lost the subject
    ALERT = "alert"          # startled, edge reflex, someone appeared
    SLEEPY = "sleepy"        # entering rest / sleep mode
    QUESTION = "question"    # asking something / enrollment prompt
    GREETING = "greeting"    # "G2 meet X" / say-hi trill


# (tone_index, duration_units) sequences. Kept short (<= ~5 notes).
CHIRP: dict[ChirpMood, list[tuple[int, int]]] = {
    ChirpMood.HAPPY:    [(20, 6), (24, 6), (28, 8)],       # bright rising
    ChirpMood.CONFUSED: [(18, 5), (14, 5), (17, 4), (13, 6)],  # wobble down-up-down
    ChirpMood.ALERT:    [(30, 4), (30, 4)],                 # two sharp equal beeps
    ChirpMood.SLEEPY:   [(16, 10), (12, 12), (9, 16)],      # slow descending, low
    ChirpMood.QUESTION: [(19, 5), (26, 8)],                 # rising two-note "?"
    ChirpMood.GREETING: [(24, 3), (28, 3), (24, 3), (30, 6)],  # quick trill
}

# voice-loop cue stage -> a mood (or None to stay silent)
_CUE_MOOD = {
    "listening": ChirpMood.ALERT,
    "thinking":  ChirpMood.QUESTION,
    "speaking":  None,
    "idle":      None,
}


def chirp_for(mood: ChirpMood) -> str:
    """The serial `b...` string for this mood."""
    return opencat.beep(CHIRP[mood])


def cue_chirp(stage: str) -> str | None:
    """Map a voice cue stage to a chirp string, or None."""
    mood = _CUE_MOOD.get(stage)
    return chirp_for(mood) if mood is not None else None


class Chirper:
    """Rate-limits chirps so G2 doesn't buzz on every tick. `maybe(mood)` returns
    the serial string to send, or None if a chirp fired too recently."""

    def __init__(self, *, min_gap_s: float = 1.5, clock=time.monotonic):
        self._gap = min_gap_s
        self._clock = clock
        self._last = -1e9

    def maybe(self, mood: ChirpMood, now: float | None = None) -> str | None:
        now = self._clock() if now is None else now
        if now - self._last < self._gap:
            return None
        self._last = now
        return chirp_for(mood)

    def reset(self) -> None:
        self._last = -1e9
