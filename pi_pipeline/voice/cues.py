"""State cues for the voice loop: listening / thinking / speaking.

Claude round-trips have noticeable latency on this hardware, so a cue tells the
user which stage they're in. `LogCue` is enough on a dev machine; on the robot
this grows a buzzer-pattern and/or posture implementation (a Phase 7 task).
"""
from __future__ import annotations

import logging
from typing import Literal, Protocol

Stage = Literal["idle", "listening", "heard", "thinking", "speaking"]

log = logging.getLogger("g2.cue")


class Cue(Protocol):
    def set(self, stage: Stage) -> None: ...


class LogCue:
    def set(self, stage: Stage) -> None:
        log.info("[%s]", stage)


# Cue melodies as (note, duration divisor); notes are C3 = 14 semitone numbers, and the buzzer reproduces 1-35 (low is loudest).
# On 2026-10-04 notes 26/30 were faint, +7 and +14 semitones were not heard at all, and the pair 4 and 8 was the loudest of a sweep.
# "thinking" is the acknowledgement for a command that goes to Claude: a low rising two-note blip. (A bosun's-call style whistle was
# drafted and dropped for now; see docs/research/buzzer-sounds.md.)
LOW_CUES: dict[str, list[tuple[int, int]]] = {
    "listening": [(8, 3), (8, 3)],     # two equal beeps: ready, say your command
    "thinking": [(4, 4), (9, 2)],      # a low rising pair: got your words, asking Claude
    "heard": [(4, 3), (8, 3)],         # quick "got it" for a recognised local command
}

DEFAULT_STAGES = ("thinking",)       # only commands that go to Claude get a sound


def chunk_notes(notes: list[tuple[int, int]], max_chars: int = 60) -> list[list[tuple[int, int]]]:
    """Split a melody so each serial token stays short (a long token risks overflowing the board's command buffer)."""
    chunks, cur, size = [], [], 1
    for tone, dur in notes:
        n = len(f" {tone} {dur}")
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur, size = [], 1
        cur.append((tone, dur))
        size += n
    if cur:
        chunks.append(cur)
    return chunks


class BuzzerCue:
    """Logs each stage and also beeps it on G2's buzzer, so you can hear that G2 heard the wake
    word, got your command, or recognised a local command. Melodies are the ones in
    `behavior.chirps` (listening = two sharp beeps, thinking = rising "?", heard = quick blip).
    A beep failing never breaks the loop."""

    def __init__(self, actuator, inner: Cue | None = None, *, shift: float = 0.0, length: float = 1.0,
                 stages=DEFAULT_STAGES, volume: int = 0):
        self._act = actuator
        self._inner = inner or LogCue()
        self._shift = int(round(shift))
        self._length = length
        self._stages = set(stages)
        self._volume = volume

    def prime(self) -> None:
        """Set the buzzer volume once (call at startup). 0 leaves the board's volume alone."""
        if not self._volume:
            return
        from ..link import opencat

        send = getattr(self._act, "send_token", None)
        if send is not None:
            try:
                send(opencat.buzzer_volume(self._volume))
            except Exception:  # noqa: BLE001
                log.debug("setting the buzzer volume failed", exc_info=True)

    def set(self, stage: Stage) -> None:
        self._inner.set(stage)
        if stage not in self._stages:
            return
        send = getattr(self._act, "send_token", None)
        if send is None:
            return
        try:
            for token in self._tokens(stage):
                send(token)
        except Exception:  # noqa: BLE001 -- a cue must never take the loop down
            log.debug("buzzer cue %r failed", stage, exc_info=True)

    def _tokens(self, stage: Stage) -> list[str]:
        """The `b...` tokens for a stage: its melody from LOW_CUES, raised by `shift` semitones and made `length` times
        longer (both default to no change), split into short tokens."""
        from ..link import opencat

        notes = LOW_CUES.get(stage)
        if not notes:
            return []
        # `dur` is a divisor of one second (4 = a quarter second), so a LONGER note is a SMALLER number
        shaped = [(max(1, tone + self._shift), max(1, int(dur / self._length + 0.5))) for tone, dur in notes]
        return [opencat.beep(c) for c in chunk_notes(shaped)]
