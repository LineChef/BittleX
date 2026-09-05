"""The voice loop: wake -> listen -> think -> speak -> act, repeat.

Kept deliberately small. Everything it touches is an interface (see the other
modules), so this same loop runs in text mode on a laptop and in full voice mode
on the robot.

Session / privacy behaviour:
- After a reply, the loop keeps listening for `follow_up_s` seconds so a
  conversation can continue without re-saying the wake word. On silence it drops
  back to wake-word-only. `follow_up_s=0` -> every turn needs the wake word.
- "go to sleep" ends the follow-up window immediately.
- "forget that" drops everything recorded since the wake word and does not reach
  Claude.
"""
from __future__ import annotations

import logging

from .actuator import Actuator
from .commands import match_local_command
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
        follow_up_s: float = 0.0,
    ):
        self._wake = wake_word
        self._stt = stt
        self._conv = conversation
        self._tts = tts
        self._act = actuator
        self._cue = cue
        self._memory = memory
        self._follow_up_s = max(0.0, follow_up_s)
        self._in_session = False

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

    def _end_session(self) -> None:
        self._in_session = False
        self._cue.set("idle")

    def _one_turn(self) -> None:
        if not self._in_session:
            self._wake.wait()
            if self._memory:
                self._memory.mark_session_start()

        self._cue.set("listening")
        timeout = self._follow_up_s if self._in_session else None
        user_text = self._stt.listen(timeout_s=timeout).strip()

        if not user_text:
            if self._in_session:
                log.info("follow-up window elapsed -- wake word needed again")
            self._end_session()
            return

        if user_text.lower() in _QUIT:
            raise KeyboardInterrupt

        cmd = match_local_command(user_text)
        if cmd == "sleep":
            log.info("'go to sleep' -- ending session")
            self._cue.set("speaking")
            self._tts.speak("Okay, going quiet. Say the wake word when you need me.")
            self._end_session()
            return
        if cmd == "forget":
            n_ex, n_fa = self._memory.forget_session() if self._memory else (0, 0)
            log.info("'forget that' -- dropped %d exchange(s), %d fact(s)", n_ex, n_fa)
            self._cue.set("speaking")
            if n_ex or n_fa:
                self._tts.speak("Okay, I've forgotten that.")
            else:
                self._tts.speak("There's nothing new to forget.")
            self._in_session = self._follow_up_s > 0
            self._cue.set("idle")
            return

        self._cue.set("thinking")
        try:
            context = self._memory.recall(user_text) if self._memory else None
            turn = self._conv.send(user_text, memory_context=context)
        except Exception:  # noqa: BLE001 -- one bad turn must not kill the loop
            log.exception("turn failed")
            self._cue.set("speaking")
            self._tts.speak("Sorry, I glitched. Say that again?")
            self._in_session = self._follow_up_s > 0
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

        self._in_session = self._follow_up_s > 0
        self._cue.set("idle")
