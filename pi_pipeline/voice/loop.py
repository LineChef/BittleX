"""The voice loop: wake -> listen -> think -> speak -> act, repeat.

Kept deliberately small. Everything it touches is an interface (see the other
modules), so this same loop runs in text mode on a laptop and in full voice mode
on the robot.
"""
from __future__ import annotations

import logging

from .actuator import Actuator
from .conversation import Conversation
from .cues import Cue
from .stt import STT
from .tts import TTS
from .wake_word import WakeWord

log = logging.getLogger("g2.loop")

_QUIT = {"/quit", "/exit", "goodbye g2", "bye g2"}


class VoiceLoop:
    def __init__(
        self,
        *,
        wake_word: WakeWord,
        stt: STT,
        conversation: Conversation,
        tts: TTS,
        actuator: Actuator,
        cue: Cue,
        memory=None,  # Phase 9: object with .recall(text) -> str and .record(user, reply)
    ):
        self._wake = wake_word
        self._stt = stt
        self._conv = conversation
        self._tts = tts
        self._act = actuator
        self._cue = cue
        self._memory = memory

    def run_forever(self) -> None:
        self._cue.set("idle")
        log.info("G2 voice loop ready")
        try:
            while True:
                self._one_turn()
        except KeyboardInterrupt:
            print()
            log.info("stopping")
        finally:
            self._act.stop()
            self._act.close()

    def _one_turn(self) -> None:
        self._wake.wait()

        self._cue.set("listening")
        user_text = self._stt.listen().strip()
        if not user_text:
            self._cue.set("idle")
            return
        if user_text.lower() in _QUIT:
            raise KeyboardInterrupt

        self._cue.set("thinking")
        try:
            context = self._memory.recall(user_text) if self._memory else None
            turn = self._conv.send(user_text, memory_context=context)
        except Exception:  # noqa: BLE001 -- one bad turn must not kill the loop
            log.exception("turn failed")
            self._cue.set("speaking")
            self._tts.speak("Sorry, I glitched. Say that again?")
            self._cue.set("idle")
            return

        self._cue.set("speaking")
        if turn.speech:
            self._tts.speak(turn.speech)
        for skill in turn.actions:
            self._act.perform(skill)

        if self._memory:
            try:
                self._memory.record(user_text, turn)
            except Exception:  # noqa: BLE001
                log.exception("memory.record failed")

        self._cue.set("idle")
