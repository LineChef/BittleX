"""State cues for the voice loop: listening / thinking / speaking.

Claude round-trips have noticeable latency on this hardware, so a cue tells the
user which stage they're in. `LogCue` is enough on a dev machine; on the robot
this grows a buzzer-pattern and/or posture implementation (a Phase 7 task).
"""
from __future__ import annotations

import logging
from typing import Literal, Protocol

Stage = Literal["idle", "listening", "thinking", "speaking"]

log = logging.getLogger("g2.cue")


class Cue(Protocol):
    def set(self, stage: Stage) -> None: ...


class LogCue:
    def set(self, stage: Stage) -> None:
        log.info("[%s]", stage)
