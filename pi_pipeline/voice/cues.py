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
        """The `b...` string for a stage: the chirp melody, raised by `shift` semitones and stretched by `length`."""
        from ..behavior.chirps import _CUE_MOOD, CHIRP
        from ..link import opencat

        mood = _CUE_MOOD.get(stage)
        if mood is None:
            return None
        return opencat.beep([(max(1, tone + self._shift), max(1, round(dur * self._length)))
                             for tone, dur in CHIRP[mood]])
