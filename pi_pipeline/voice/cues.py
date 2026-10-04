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


# Cue melodies as (tone, duration divisor). The buzzer is clearly louder at LOW notes -- on 2026-10-04 notes 26/30 were faint,
# +7 and +14 semitones were not heard at all, and the pair 4 and 8 was the loudest of a sweep -- so all cues live down there.
LOW_CUES: dict[str, list[tuple[int, int]]] = {
    "listening": [(8, 3), (8, 3)],     # two equal beeps: ready, say your command
    "thinking": [(4, 4), (9, 2)],      # a rising "?": got your words, asking Claude
    "heard": [(4, 3), (8, 3)],         # quick "got it" for a recognised local command
}


class BuzzerCue:
    """Logs each stage and also beeps it on G2's buzzer, so you can hear that G2 heard the wake
    word, got your command, or recognised a local command. Melodies are the ones in
    `behavior.chirps` (listening = two sharp beeps, thinking = rising "?", heard = quick blip).
    A beep failing never breaks the loop."""

    def __init__(self, actuator, inner: Cue | None = None, *, shift: float = 0.0, length: float = 1.0):
        self._act = actuator
        self._inner = inner or LogCue()
        self._shift = int(round(shift))
        self._length = length

    def set(self, stage: Stage) -> None:
        self._inner.set(stage)
        token = self._token(stage)
        send = getattr(self._act, "send_token", None)
        if token is None or send is None:
            return
        try:
            send(token)
        except Exception:  # noqa: BLE001 -- a cue must never take the loop down
            log.debug("buzzer cue %r failed", stage, exc_info=True)

    def _token(self, stage: Stage) -> str | None:
        """The `b...` string for a stage: its melody from LOW_CUES, raised by `shift` semitones and made `length`
        times longer (both default to no change)."""
        from ..link import opencat

        notes = LOW_CUES.get(stage)
        if not notes:
            return None
        # `dur` is a divisor of one second (4 = a quarter second), so a LONGER note is a SMALLER number
        return opencat.beep([(max(1, tone + self._shift), max(1, int(dur / self._length + 0.5)))
                             for tone, dur in notes])
