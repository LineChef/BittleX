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

from ..personality import character_state
from ..personality.mood import MoodModel
from .actuator import Actuator
from .commands import looks_like_rebuff, match_local_command, parse_character_command
from .conversation import Conversation, ConversationError

_DEFAULT_CHARACTER_LEVEL = 0.4
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
        # slow-moving mood from interaction recency -> a one-line system-prompt
        # note + (on the robot) idle-timing bias. Needs a memory to read
        # recency from; harmless without one (stays NEUTRAL -> empty hint).
        self._mood = MoodModel()

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

    def _handle_character(self, cc) -> None:
        """Toggle an opt-in character mode (e.g. 'enable gir mode'). Rebuilds the
        personality on the live Conversation and persists it for next start."""
        self._cue.set("speaking")
        if cc is None:
            self._tts.speak("I didn't catch which mode you meant.")
            return
        p = self._conv.personality
        if cc.on:
            lvl = cc.level if cc.level is not None else _DEFAULT_CHARACTER_LEVEL
            self._conv.set_personality(p.with_character(cc.name, lvl))
            character_state.save(cc.name, lvl)
            log.info("character mode %s ON at %.2f", cc.name, lvl)
            self._tts.speak(f"Okay, {cc.name} mode on.")
        else:
            self._conv.set_personality(p.without_character(cc.name))
            character_state.clear()
            log.info("character mode %s OFF", cc.name)
            self._tts.speak(f"Okay, {cc.name} mode off.")

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
        if cmd == "character":
            self._handle_character(parse_character_command(user_text))
            self._in_session = self._follow_up_s > 0
            self._cue.set("idle")
            return

        # slow mood: refresh from interaction recency, fold the hint into the
        # system prompt for this turn (a rebuff drops it to SUBDUED for a while)
        if looks_like_rebuff(user_text):
            self._mood.note_rebuff()
        recency = getattr(self._memory, "recency", None)
        age, n_recent = recency() if callable(recency) else (None, 0)
        self._mood.update(last_interaction_s=age, exchanges_recent=n_recent)
        self._conv.set_mood_hint(self._mood.phrasing_hint())

        self._cue.set("thinking")
        try:
            context = self._memory.recall(user_text) if self._memory else None
            turn = self._conv.send(user_text, memory_context=context)
        except ConversationError as e:      # known reason -> say it plainly
            log.warning("Claude call failed (%s): %s", e.kind, e.spoken)
            self._cue.set("speaking")
            self._tts.speak(e.spoken)
            self._in_session = self._follow_up_s > 0
            self._cue.set("idle")
            return
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
