"""Emotive chirp vocabulary (behaviour-ideas B5).

Short buzzer melodies over the OpenCat `b<note> <duration> ...` serial token, one per
mood. Cheap personality, and doubles as the Phase 7 voice state cue (listening /
thinking / speaking).

  chirp_for(ChirpMood.HAPPY)  -> "b24 6 27 6 31 8"   (a serial string via opencat.beep)
  Chirper(...).maybe(mood)    -> the string, or None if still in cooldown

Note/duration values are a FIRST CUT -- tune by ear on the real buzzer. A note is a
semitone number (C3 = 14, C4 = 26); the buzzer reproduces 1-35 and is loudest at the LOW
end (notes above ~30 are faint, above ~35 inaudible). A duration is a divisor of one
second (4 = a quarter second), so a longer note is a SMALLER number. These moods sit in
the upper range; the voice-loop cues live in `voice/cues.py` (`LOW_CUES`) instead.
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
    ACK = "ack"             # "heard you" -- fires on every recognised voice command
    FANFARE = "fanfare"      # starting to explore: "ba nun na NAAA!" (user, 2026-10-09)


# (tone_index, duration_units) sequences. Kept short (<= ~5 notes).
CHIRP: dict[ChirpMood, list[tuple[int, int]]] = {
    # LOWER REGISTER (user, 2026-10-08: heard on G2, "easier to hear"): the first-cut tones below, each note 10 semitones lower (the buzzer is loudest at the low end).
    ChirpMood.HAPPY:    [(10, 6), (14, 6), (18, 8)],       # bright rising
    ChirpMood.CONFUSED: [(8, 5), (4, 5), (7, 4), (3, 6)],  # wobble down-up-down
    ChirpMood.ALERT:    [(20, 4), (20, 4)],                 # two sharp equal beeps
    ChirpMood.SLEEPY:   [(6, 10), (2, 12), (1, 16)],        # slow descending, low
    ChirpMood.QUESTION: [(9, 5), (16, 8)],                  # rising two-note "?"
    ChirpMood.GREETING: [(14, 3), (18, 3), (14, 3), (20, 6)],  # quick trill
    ChirpMood.ACK:      [(16, 3), (20, 3)],                 # quick "got it" blip
    ChirpMood.FANFARE:  [(9, 10), (13, 8), (16, 10), (21, 2)],   # root, major third, fifth, then the octave held: short, short, short, LONG (a rising arpeggio, all notes under 23 like the other chirps)
}

# voice-loop cue stage -> a mood (or None to stay silent)
_CUE_MOOD = {
    "awake":     ChirpMood.ALERT,
    "listening": ChirpMood.ALERT,
    "heard":     ChirpMood.ACK,
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

    def ready(self, now: float | None = None) -> bool:
        """True if a chirp would fire now -- lets a caller decide to emit an
        abstract CHIRP effect without materialising the serial string."""
        now = self._clock() if now is None else now
        return now - self._last >= self._gap

    def fired(self, now: float | None = None) -> None:
        """Record that a chirp just went out (pairs with `ready()`)."""
        self._last = self._clock() if now is None else now

    def reset(self) -> None:
        self._last = -1e9
