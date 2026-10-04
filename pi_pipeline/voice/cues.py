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

    def __init__(self, actuator, inner: Cue | None = None):
        self._act = actuator
        self._inner = inner or LogCue()

    def set(self, stage: Stage) -> None:
        self._inner.set(stage)
        from ..behavior.chirps import cue_chirp

        token = cue_chirp(stage)
        send = getattr(self._act, "send_token", None)
        if token is None or send is None:
            return
        try:
            send(token)
        except Exception:  # noqa: BLE001 -- a cue must never take the loop down
            log.debug("buzzer cue %r failed", stage, exc_info=True)
