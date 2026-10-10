"""The voice loop: wake -> listen -> think -> speak -> act, repeat.

Kept deliberately small. Everything it touches is an interface (see the other
modules), so this same loop runs in text mode on a laptop and in full voice mode
on the robot.

Session / privacy behaviour:
- After a reply, the loop keeps listening for `follow_up_s` seconds so a
  conversation can continue without re-saying the wake word. On silence it drops
  back to wake-word-only. `follow_up_s=0` -> every turn needs the wake word.
- "go to sleep" ends the follow-up window immediately.
- "let's talk" starts conversation mode: G2 keeps listening without the wake word (each turn waits `conversation_window_s`
  for you to start speaking) until a quiet gap, "that's all", "go to sleep" or `conversation_max_s`.
- Side chatter: a turn taken WITHOUT the wake word (a question window or conversation mode) is dropped before Claude when it is
  too long to be a request to a robot (`side_max_words`, `conversation_max_words`) or says it is aimed at someone else
  ("I'm not talking to you"). Safety commands (stop, shut down, ...) always work.
- "forget that" drops everything recorded since the wake word and does not reach
  Claude.
"""
from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time

from ..personality import character_state
from ..personality import gir
from ..personality.mood import MoodModel
from . import narration
from . import skills
from .actuator import Actuator
from ..behavior.survey import SurveyConfig, clean_name, naming_plan, parse_naming, picture_pose_steps
from .commands import (
    addressed_elsewhere, is_clear_shutdown, looks_like_rebuff, match_local_command, parse_character_command,
    parse_floor_command, parse_walk_command,
    parse_narration_command,
)
from .conversation import Conversation, ConversationError

_DEFAULT_CHARACTER_LEVEL = gir.level_to_intensity(gir.DEFAULT_LEVEL)
from .cues import Cue
from .stt import STT
from .timing import TurnTrace
from .tts import TTS
from .wake_word import WakeWord


def _say_seconds(secs) -> str:
    """'ten seconds', '1 minute' ... for the local walk's spoken acknowledgement."""
    if not secs:
        return "a bit"
    s = int(round(secs))
    if s % 60 == 0 and s >= 60:
        return "a minute" if s == 60 else f"{s // 60} minutes"
    return "1 second" if s == 1 else f"{s} seconds"

log = logging.getLogger("g2.loop")

# "what do you see", "what are you looking at", "look around", "can you see ...", "describe what you see", "what's in front of you"
_LOOK_RE = re.compile(
    r"\b(what (do|can|are) you (see|seeing|looking at)|what('s| is| are) (in front of|around|ahead of|near) you|"
    r"what('s| is) (that|this)|look (at|around|over)|can you see|do you see|describe (what|the|your)|tell me what you see)\b", re.I)


# Teaching G2 how he looks (take a picture of him in a mirror and keep a note) versus asking him from memory (NO picture):
#   teach:  "this is a mirror", "that's you in the mirror", "can you see yourself", "your reflection", "remember what you look like"
#   recall: "do you remember what you look like?", "what do you look like?", "describe yourself" -> answered from memory
# Order matters: a mirror word always teaches; a question about it recalls; the bare command "remember what you look like" teaches.
_MIRROR_RE = re.compile(
    r"\b(this is (what )?you|that('s| is) (what )?you|look(ing)? in the mirror|(this|that|it)('s| is) a mirror|in (the|a) mirror|"
    r"see yourself|your reflection)\b", re.I)
_RECALL_LOOKS_RE = re.compile(
    r"\b((do|did|can|could|would|will) you (still |even )?(remember|know) what you look like|what do you look like|"
    r"describe yourself|how do you look)\b", re.I)
_REMEMBER_LOOKS_RE = re.compile(r"\bremember what you look like\b", re.I)


def asks_g2_to_learn_his_looks(text: str) -> bool:
    t = text or ""
    if _MIRROR_RE.search(t):
        return True
    if _RECALL_LOOKS_RE.search(t):
        return False
    return bool(_REMEMBER_LOOKS_RE.search(t))


_CANCEL_WORDS = {"cancel", "stop", "wait", "no", "dont", "never", "mind", "abort", "hold"}


def _normalize_words(text: str) -> set[str]:
    return set(re.sub(r"[^a-z\s]", " ", re.sub(r"['’`]", "", (text or "").lower())).split())


_SILENT_LOOK = "I looked, but I'm not sure how to put it into words. Ask me again?"


def asks_what_g2_sees(text: str) -> bool:
    return bool(_LOOK_RE.search(text or ""))

_QUIT = {"/quit", "/exit", "goodbye g2", "bye g2"}


class _SpeechWorker:
    """Speaks queued sentences in order on background threads, so a streamed reply's actions are never held up behind
    speech. When the TTS can `prepare()` and `play()` separately (Piper), the next sentence is synthesised while the
    previous one is still playing; otherwise each sentence is spoken in turn. `finish()` waits until all is spoken."""

    def __init__(self, tts, on_first=None):
        self._tts = tts
        self._on_first = on_first
        self._first = True
        self.said = False
        self._text_q: "queue.Queue[str | None]" = queue.Queue()
        self._pipelined = hasattr(tts, "prepare") and hasattr(tts, "play")
        if self._pipelined:
            self._audio_q: "queue.Queue[object]" = queue.Queue()
            self._threads = [threading.Thread(target=self._synth_loop, name="synth", daemon=True),
                             threading.Thread(target=self._play_loop, name="speech", daemon=True)]
        else:
            self._threads = [threading.Thread(target=self._speak_loop, name="speech", daemon=True)]
        for t in self._threads:
            t.start()

    def say(self, text: str) -> None:
        self.said = True
        self._text_q.put(text)

    def _begin(self) -> None:
        if self._first:
            self._first = False
            if self._on_first:
                self._on_first()

    def _speak_loop(self) -> None:
        while True:
            text = self._text_q.get()
            if text is None:
                return
            self._begin()
            try:
                self._tts.speak(text)
            except Exception:  # noqa: BLE001 -- a TTS failure must not take the turn down
                log.exception("speech failed")

    def _synth_loop(self) -> None:
        while True:
            text = self._text_q.get()
            if text is None:
                self._audio_q.put(None)
                return
            try:
                self._audio_q.put(self._tts.prepare(text))
            except Exception:  # noqa: BLE001
                log.exception("speech synthesis failed")

    def _play_loop(self) -> None:
        while True:
            item = self._audio_q.get()
            if item is None:
                return
            self._begin()
            try:
                self._tts.play(item)
            except Exception:  # noqa: BLE001
                log.exception("speech playback failed")

    def finish(self) -> None:
        self._text_q.put(None)
        for t in self._threads:
            t.join()


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
        question_window_s: float = 0.0,  # how long to keep listening after G2 asks a question (0 = never)
        on_event=None,  # Phase 10: called with wake_word= / conversation_ended= / told_sleep=
        camera=None,  # object with .snapshot() -> Snapshot | None; a picture is attached when the user asks what G2 sees
        on_power=None,  # called with True when told "you're unplugged", False for "you're plugged in" (the Pi-battery warning's arming)
        on_poweroff=None,  # called to power the Pi off cleanly after a clear "shut down" (and no "cancel" within `shutdown_confirm_s`)
        shutdown_confirm_s: float = 6.0,
        announce_online: bool = False,  # say "G2 online." once the loop is ready (the voice service turns this on; G2_ANNOUNCE_ONLINE=off silences it)
        conversation_window_s: float = 0.0,  # conversation mode ("let's talk"): seconds to wait for you to start speaking each turn (0 = mode off)
        conversation_max_s: float = 600.0,  # conversation mode ends by itself after this long
        side_max_words: int = 0,  # a question-window turn (no wake word) longer than this many words is treated as side chatter (0 = no limit)
        conversation_max_words: int = 0,  # the same limit inside conversation mode (0 = no limit)
        namer=None,  # object called with a picture kind ("name:mug") that takes and saves one picture and returns its path or None (vision.exploration_pictures.ExplorationPictureSaver)
    ):
        self._namer = namer
        self._announce_online = announce_online
        self._wake = wake_word
        self._stt = stt
        self._conv = conversation
        self._tts = tts
        self._act = actuator
        self._cue = cue
        self._memory = memory
        self._camera = camera
        self._on_power = on_power
        self._on_poweroff = on_poweroff
        self._shutdown_confirm_s = shutdown_confirm_s
        self._last_look = None                         # the Snapshot of the look in progress, for the sighting note
        self._follow_up_s = max(0.0, follow_up_s)
        self._question_window_s = max(0.0, question_window_s)
        self._session_window = self._follow_up_s
        self._in_session = False
        self._conv_window_s = max(0.0, conversation_window_s)
        self._conv_max_s = max(0.0, conversation_max_s)
        self._side_max_words = max(0, int(side_max_words))
        self._conv_max_words = max(0, int(conversation_max_words))
        self._conversing = False
        self._conv_started = 0.0
        # bridge to the behaviour runtime (if running alongside); no-op otherwise
        self._events = on_event or (lambda **_kw: None)
        # slow-moving mood from interaction recency -> a one-line system-prompt
        # note + (on the robot) idle-timing bias. Needs a memory to read
        # recency from; harmless without one (stays NEUTRAL -> empty hint).
        self._mood = MoodModel()

    def _look(self, user_text: str) -> dict:
        """kwargs for Conversation.send: a camera picture plus the detector's hint when the user asks what G2 sees; {} otherwise.
        If the camera fails, a note says so, so Claude does not make something up."""
        learn = asks_g2_to_learn_his_looks(user_text)
        self._last_look = None
        if self._camera is None or not (learn or asks_what_g2_sees(user_text)):
            return {}
        self._cue.set("thinking")
        self._pose_for_picture()
        snap = self._camera.snapshot()
        self._last_look = snap
        if snap is None:
            return {"image_note": "[G2's camera could not take a picture right now.]"}
        if learn:
            note = ("[Picture from G2's camera. The user says this shows YOU, G2 (a small robot, probably in a mirror). Describe your own "
                    "appearance out loud in one or two sentences, and save one short fact about it with the remember tool, written as "
                    "\"I look like ...\". Describe only yourself, not any people.]")
        else:
            note = "[Picture from G2's camera. Describe what you see out loud now.]"
        return {"image": snap.jpeg, "image_note": f"{note} {snap.hint()}"}

    def _pose_token(self, token: str) -> None:
        """One step of the picture pose sequence: a raw OpenCat skill token through the actuator's `perform_token` (`perform` only knows skill names and ignores a token)."""
        fn = getattr(self._act, "perform_token", None)
        (fn or self._act.perform)(token)

    def _pose_for_picture(self) -> None:
        """Any picture, any time the camera is used (user, 2026-10-07): look down (the inspect bow), look up, stand again and settle before the shot, the same sequence as a survey stop
        or a naming. A failed skill must not stop the picture or the voice loop."""
        import time
        if self._act is None:
            return
        t0 = time.monotonic()
        try:
            for delay, skill in picture_pose_steps(SurveyConfig()):
                wait = delay - (time.monotonic() - t0)
                if wait > 0:
                    time.sleep(wait)
                self._pose_token(skill)
            end = picture_pose_steps(SurveyConfig(), settle_only=True)
            wait = end - (time.monotonic() - t0)
            if wait > 0:
                time.sleep(wait)
        except Exception:  # noqa: BLE001
            log.exception("the picture pose sequence failed")

    def _refuse_sound(self) -> None:
        """The losing horn when G2 refuses a request (user, 2026-10-10, a measured approximation of the game-show clip); `G2_REFUSE_SOUND=0` turns it off."""
        from . import prompt_tones
        prompt_tones.play_horn_if_enabled("G2_REFUSE_SOUND", wait=True)

    def _speak(self, text: str) -> None:
        """Speak `text`; a speaker/TTS failure is logged, never raised (it must not take the voice loop down)."""
        try:
            self._tts.speak(text)
        except Exception:  # noqa: BLE001
            log.exception("speech failed")

    def run_forever(self) -> None:
        self._cue.set("idle")
        log.info("G2 voice loop ready")
        if self._announce_online:
            from . import restart_notice
            restart_notice.announce_online(self._speak)        # "G2 online.": the loop has finished starting and is listening
        try:
            while True:
                self._one_turn()
        except KeyboardInterrupt:
            print()
            log.info("stopping")
        finally:
            self._act.stop()
            self._act.close()

    def _set_session(self, expects_reply: bool = False) -> None:
        """Decide whether the next turn needs the wake word. G2 listens on without it only for the short question window
        (when its reply asked something) or the general follow-up window (off on the robot). In conversation mode the
        conversation window applies after every turn, until the mode's time limit."""
        if self._conversing:
            if self._conv_max_s and time.monotonic() - self._conv_started > self._conv_max_s:
                log.info("conversation mode ended: time limit (%.0f s)", self._conv_max_s)
                self._end_session()
                return
            self._in_session, self._session_window = True, self._conv_window_s
            return
        if expects_reply and self._question_window_s > 0:
            self._in_session, self._session_window = True, self._question_window_s
        elif self._follow_up_s > 0:
            self._in_session, self._session_window = True, self._follow_up_s
        else:
            self._in_session = False

    def _name_object(self, name: str) -> None:
        """Naming an object by voice, outside an exploration session: the same picture sequence as a survey stop (look down, look up, stand, settle, picture), saved under the name
        (`behavior/survey.naming_plan`), then the spoken confirmation. Runs here in the loop (about 8 s), so nothing else is said or moved meanwhile."""
        import time
        log.info("naming an object (voice): picture sequence")
        self._cue.set("speaking")
        self._speak(f"Okay, let me look at the {name}.")
        saved = None
        t0 = time.monotonic()
        try:
            for delay, kind, payload, _why in naming_plan(name, SurveyConfig()):
                wait = delay - (time.monotonic() - t0)
                if wait > 0:
                    time.sleep(wait)
                if kind == "skill":
                    self._pose_token(payload)
                elif kind == "shot":
                    saved = self._namer(payload)
        except Exception:  # noqa: BLE001 -- a failed picture must not end the voice loop
            log.exception("naming picture failed")
        self._cue.set("speaking")
        if saved:
            self._speak(f"Okay, I will remember the {name}.")
        else:
            self._speak("I could not keep that picture. It may be too like one I already have, or the camera did not answer.")
        self._set_session()
        self._cue.set("idle")

    def _restart_service(self) -> None:
        """Restart this voice service: ask systemd (`sudo -n systemctl restart g2-voice`); if that is not allowed, exit with an error so the unit's `Restart=on-failure` brings it back. Never returns when it works."""
        import subprocess
        import sys
        try:
            subprocess.Popen(["sudo", "-n", "systemctl", "restart", "g2-voice"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:  # noqa: BLE001
            log.warning("could not ask systemd to restart the voice service; exiting so it restarts", exc_info=True)
        sys.exit(1)

    def _end_session(self) -> None:
        if self._conversing:
            log.info("conversation mode off")
        self._conversing = False
        self._in_session = False
        self._cue.set("idle")
        self._events(conversation_ended=True)

    def _handle_character(self, cc) -> None:
        """Toggle an opt-in character mode (e.g. 'enable gir mode'). Rebuilds the
        personality on the live Conversation and persists it for next start."""
        self._cue.set("speaking")
        if cc is None:
            self._speak("I didn't catch which mode you meant.")
            return
        p = self._conv.personality
        if cc.on:
            lvl = cc.level if cc.level is not None else _DEFAULT_CHARACTER_LEVEL
            self._conv.set_personality(p.with_character(cc.name, lvl))
            character_state.save(cc.name, lvl)
            n = gir.nearest_level(lvl)   # echo back *what* the level does, not just the number
            log.info("character mode %s ON at %.2f (level %d)", cc.name, lvl, n)
            self._speak(f"Okay, {cc.name} mode on, {gir.describe_level(n)}.")
        else:
            self._conv.set_personality(p.without_character(cc.name))
            character_state.clear()
            log.info("character mode %s OFF", cc.name)
            self._speak(f"Okay, {cc.name} mode off.")

    def _is_side_chatter(self, text: str, woke: bool) -> bool:
        """True when a turn that is not a local command should not reach Claude: told it was for someone else, or (taken without the
        wake word) too long to be a request to a robot. A turn that followed the wake word is never dropped for length."""
        if addressed_elsewhere(text):
            log.info("ignored: the person said they were not talking to G2")
            return True
        if woke:
            return False
        limit = self._conv_max_words if self._conversing else self._side_max_words
        n = len(text.split())
        if limit and n > limit:
            log.info("ignored side chatter: %d words heard without the wake word (limit %d%s)", n, limit,
                     ", conversation mode" if self._conversing else "")
            return True
        return False

    def _one_turn(self) -> None:
        trace = TurnTrace()
        woke = not self._in_session            # False: this turn is taken without the wake word (a question window or conversation mode)
        if not self._in_session:
            self._wake.wait()
            self._cue.set("awake")       # right after the wake word: the chime that says G2 is listening
            trace.stamp("wake")
            warm = getattr(self._conv, "warm_up", None)
            if callable(warm):
                warm()           # open the API connection in the background while the person is still speaking
            self._events(wake_word=True)
            if self._memory:
                self._memory.mark_session_start()

        self._cue.set("listening")
        timeout = self._session_window if self._in_session else None
        user_text = self._stt.listen(timeout_s=timeout).strip()
        trace.stamp("transcript")
        speech_end = getattr(self._stt, "last_speech_t", None)
        if speech_end is not None:
            trace.stamp("speech_end", speech_end)
        if os.environ.get("G2_LOG_HEARD"):   # opt-in: transcripts stay out of the logs otherwise
            log.info("heard: %r", user_text)
        info = getattr(self._stt, "last_info", None)
        if info:
            log.info("command window: %s", info)          # mic peak, blocks read, the last partial transcripts: tells a deaf mic from a missed phrase

        if not user_text:
            if self._in_session:
                log.info("%s elapsed -- wake word needed again", "conversation window" if self._conversing else "follow-up window")
                self._cue.set("closed")          # the window ended: he has stopped listening
            self._end_session()
            return
        self._cue.set("captured")                # he thinks you have finished speaking and has your words

        if user_text.lower() in _QUIT:
            raise KeyboardInterrupt

        cmd = match_local_command(user_text)
        if cmd is None:                                    # "hi step and walk forward": switch the gait here, then handle the rest as its own request
            from ..gait import gait_mode
            both = gait_mode.split_compound(user_text)
            if both:
                from ..gait.residual_policy import default_policy_path
                gait, said = gait_mode.request(user_text.split(" and ")[0], default_policy_path())
                log.info("gait command (voice, compound): %s, then %r", gait or "refused", both[1])
                if gait:
                    self._cue.set("gait_switch")
                    self._speak("Hi step on." if gait == "hi_step" else "Walking normally.")
                else:
                    self._refuse_sound()
                user_text = both[1]
                cmd = match_local_command(user_text)
        if cmd is None and self._namer is not None:
            name = clean_name(parse_naming(user_text))
            if name:                                       # "this is the dishwasher": the same picture sequence as in an exploration session, no Claude call
                self._events(ack=True)
                self._cue.set("heard")
                self._name_object(name)
                return
        if cmd is not None:
            # G2 always signals that he registered a command -- an instant "heard
            # you" chirp (+ cue), before the slower spoken reply. Makes a
            # misheard command obvious so you can say "resume" / "never mind".
            self._events(ack=True)
            self._cue.set("heard")

        if cmd == "end_converse" and not self._conversing:
            cmd = None                                      # "that's all" outside conversation mode is just a sentence for Claude
        if cmd is None and self._is_side_chatter(user_text, woke):
            self._cue.set("idle")
            if not self._conversing or addressed_elsewhere(user_text):
                self._end_session()                         # not answering a question, or told it was not for G2: back to the wake word
            else:
                self._set_session()
            return

        if cmd == "converse":
            if self._conv_window_s <= 0:
                self._cue.set("speaking")
                self._speak("Conversation mode isn't turned on.")
                self._set_session()
                self._cue.set("idle")
                return
            self._conversing, self._conv_started = True, time.monotonic()
            log.info("conversation mode on (window %.0f s, limit %.0f s)", self._conv_window_s, self._conv_max_s)
            self._cue.set("speaking")
            self._speak("Okay, let's talk. Say that's all when you're done.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "end_converse":
            self._cue.set("speaking")
            self._speak("Okay, back to the wake word.")
            self._end_session()
            return
        if cmd == "halt":
            log.warning("EMERGENCY STOP (voice command %r)", user_text)
            self._events(halt=True)
            self._cue.set("speaking")
            self._speak("Stopping.")
            self._end_session()
            return
        if cmd == "resume":
            log.info("emergency stop released (voice)")
            self._events(release=True)
            self._cue.set("speaking")
            self._speak("Okay, moving again.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd in ("unplugged", "plugged"):
            on_battery = cmd == "unplugged"
            log.info("told %s", "he is on battery" if on_battery else "he is plugged in")
            if self._on_power is not None:
                self._on_power(on_battery)
            self._cue.set("speaking")
            if self._on_power is None:
                self._speak("Okay. I can't track my battery here, though.")
            elif on_battery:
                self._speak("Okay, I'm on battery. I'll count from now and warn you before I run low.")
            else:
                self._speak("Okay, I'm charging. I'll pause my battery warning.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "explore":
            log.info("explore armed (voice)")
            self._cue.set("speaking")
            from . import prompt_tones
            self._speak("Exploration mode.")             # said BEFORE the hand-over: the launch stops this service
            prompt_tones.play_start_horn(wait=True)      # then the Viking horn, nothing before the words (user, 2026-10-10)
            self._events(arm_explore=True)
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "end_explore":
            log.info("end exploration mode (voice): not exploring in this service")
            self._events(disarm_explore=True)
            self._cue.set("speaking")
            self._speak("Okay, no exploring.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "unexplore":
            log.info("explore disarmed (voice)")
            self._events(disarm_explore=True)
            self._cue.set("speaking")
            self._speak("Okay, coming back.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "come":
            log.info("come-here (voice)")
            self._events(come_here=True)
            self._cue.set("speaking")
            self._speak("Coming.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "gait":                                   # "hi step" / "walk normally": works from any mode; the state is shared with an exploration session
            from ..gait import gait_mode
            from ..gait.residual_policy import default_policy_path
            gait, said = gait_mode.request(user_text, default_policy_path())
            log.info("gait command (voice): %s", gait or "refused")
            if gait:
                self._cue.set("gait_switch")             # the short double beep
            else:
                self._refuse_sound()                     # the losing horn: G2 will not do that
            self._cue.set("speaking")
            self._speak(said)
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "walk":                                   # "walk for ten seconds": straight to the walk, no Claude call (the same path a Claude walk takes)
            secs = skills.clamp_seconds(parse_walk_command(user_text))
            log.info("walk %.1f s (voice, local)", secs or 0.0)
            self._cue.set("speaking")
            self._act.perform("walk_forward", seconds=secs)
            self._speak(f"Walking for {_say_seconds(secs)}.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "restart_voice":
            log.info("voice service restart requested (voice)")
            self._cue.set("speaking")
            self._speak("Restarting voice loop. I will say G2 online when I am back.")
            self._restart_service()
            return
        if cmd == "shutdown":
            log.info("shutdown requested (voice) -- lie down then dormant")
            self._events(shutdown=True)
            self._cue.set("speaking")
            if self._on_poweroff is not None and is_clear_shutdown(user_text):
                self._speak(f"Okay, lying down and switching the computer off in {int(self._shutdown_confirm_s)} seconds. Say cancel to stop me.")
                reply = (self._stt.listen(timeout_s=self._shutdown_confirm_s) or "") if self._shutdown_confirm_s > 0 else ""
                if any(w in _normalize_words(reply) for w in _CANCEL_WORDS):
                    log.info("power-off cancelled (voice): %r", reply)
                    self._speak("Okay, staying on.")
                    self._end_session()
                    return
                self._speak("Goodbye. Please flip my battery switch off.")   # the PiSugar S keeps powering the Pi after it halts
                self._end_session()
                try:
                    self._on_poweroff()
                except Exception:  # noqa: BLE001 -- say so rather than fail silently
                    log.exception("power-off failed")
                    self._speak("I lay down, but I couldn't switch the computer off.")
                return
            self._speak("Okay, lying down and shutting down. Wake me when you need me.")
            self._end_session()
            return
        if cmd == "sleep":
            log.info("'go to sleep' -- ending session")
            self._events(told_sleep=True)
            self._cue.set("speaking")
            self._speak("Okay, going quiet. Say the wake word when you need me.")
            self._end_session()
            return
        if cmd == "forget":
            n_ex, n_fa = self._memory.forget_session() if self._memory else (0, 0)
            log.info("'forget that' -- dropped %d exchange(s), %d fact(s)", n_ex, n_fa)
            self._cue.set("speaking")
            if n_ex or n_fa:
                self._speak("Okay, I've forgotten that.")
            else:
                self._speak("There's nothing new to forget.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "character":
            self._handle_character(parse_character_command(user_text))
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "chirps_on":
            log.info("chirps enabled (voice)")
            self._events(chirps_on=True)
            self._cue.set("speaking")
            self._speak("Okay, chirps on.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "chirps_off":
            log.info("chirps disabled (voice)")
            self._events(chirps_off=True)
            self._cue.set("speaking")
            self._speak("Okay, chirps off.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "voice_language":
            log.info("resetting the BiBoard voice module to English (voice)")
            self._cue.set("speaking")
            self._speak("Okay, setting my voice module to English.")
            send = getattr(self._act, "send_token", None)
            if send is not None:
                for tok in ("XAc", "XAb", "XAa"):          # enable, Chinese, English: the documented recovery; never Xa / XAd
                    send(tok)
                    time.sleep(1.2)
            self._set_session()
            self._cue.set("idle")
            return
        if cmd in ("floor", "floor_query"):
            from ..telemetry import autolog
            self._cue.set("speaking")
            if cmd == "floor":
                label = autolog.set_surface(parse_floor_command(user_text) or "unknown")
                log.info("floor label set to %r (voice)", label)
                self._speak(f"Okay, the floor is {label}.")
            else:
                label, age = autolog.get_surface_info()
                self._speak(f"I have the floor down as {label}." if label != "unknown" else "I don't know what floor I'm on. Tell me, like the floor is tile.")
            self._set_session()
            self._cue.set("idle")
            return
        if cmd == "narration_level":
            n = parse_narration_command(user_text)
            log.info("narration verbosity level %s (voice)", n)
            self._cue.set("speaking")
            if n is None:
                self._speak(f"Narration levels go 1 to {narration.LEVELS} -- which one?")
            else:
                self._conv.set_narration_hint(narration.hint_for_level(n))
                self._speak(f"Okay, narration level {n}: {narration.describe_level(n)}.")
            self._set_session()
            self._cue.set("idle")
            return

        # slow mood: refresh from interaction recency, fold the hint into the
        # system prompt for this turn (a rebuff drops it to SUBDUED for a while)
        if looks_like_rebuff(user_text):
            self._mood.note_rebuff()
            if os.environ.get("G2_GRUNT", "1") != "0":
                from . import prompt_tones
                prompt_tones.play_grunt(wait=True)           # G2 does not like that (user, 2026-10-10); the speaker is the only voice here, so waiting 0.4 s is harmless
        recency = getattr(self._memory, "recency", None)
        age, n_recent = recency() if callable(recency) else (None, 0)
        self._mood.update(last_interaction_s=age, exchanges_recent=n_recent)
        self._conv.set_mood_hint(self._mood.phrasing_hint())
        try:
            from ..gait import gait_mode
            setter = getattr(self._conv, "set_gait_hint", None)
            if setter is not None:
                setter(gait_mode.claude_hint())
        except Exception:  # noqa: BLE001 -- a missing gait file must never stop a turn
            log.debug("gait hint skipped", exc_info=True)

        # a conversational turn: still signal "heard you" -- the Claude round
        # trip has real latency on this hardware, so an instant chirp + the
        # thinking cue tell you G2 registered it.
        self._events(ack=True)
        self._cue.set("thinking")
        streaming = bool(getattr(self._conv, "supports_streaming", False))
        done: list[str] = []
        speaker = _SpeechWorker(self._tts, on_first=lambda: trace.stamp("voice_start")) if streaming else None

        def _do(skill: str, seconds) -> None:
            if not done:
                trace.stamp("move_sent")
            done.append(skill)
            if seconds is None:
                self._act.perform(skill)
            else:
                self._act.perform(skill, seconds=seconds)

        def _on_action(skill: str, seconds) -> None:    # streamed: runs the moment the tool call is complete
            self._cue.set("speaking")
            _do(skill, seconds)

        def _on_speech(sentence: str) -> None:           # streamed: one finished sentence at a time
            self._cue.set("speaking")
            speaker.say(sentence)

        try:
            context = self._memory.recall(user_text) if self._memory else None
            pic = self._look(user_text)
            if streaming:
                turn = self._conv.send(user_text, memory_context=context,
                                       on_action=_on_action, on_speech=_on_speech, **pic)
            else:
                turn = self._conv.send(user_text, memory_context=context, **pic)
        except ConversationError as e:      # known reason -> say it plainly
            log.warning("Claude call failed (%s): %s", e.kind, e.spoken)
            if speaker:
                speaker.finish()
            self._cue.set("speaking")
            self._speak(e.spoken)
            self._set_session()
            self._cue.set("idle")
            return
        except Exception:  # noqa: BLE001 -- one bad turn must not kill the loop
            log.exception("turn failed")
            if speaker:
                speaker.finish()
            self._cue.set("speaking")
            self._speak("Sorry, I glitched. Say that again?")
            self._set_session()
            self._cue.set("idle")
            return

        call = getattr(self._conv, "last_call", None) or {}
        if "start" in call:
            trace.stamp("claude_start", call["start"])
            trace.stamp("claude_end", call["end"])
            if call.get("first") is not None:
                trace.stamp("claude_first", call["first"])
            warm = getattr(self._conv, "warm_info", None) or {}
            if warm:
                trace.meta["warm"] = bool(warm.get("ok") and warm.get("t_end", float("inf")) <= call["start"])

        if getattr(turn, "streamed", False):
            # the speech and the moves were already delivered while the reply streamed in
            if pic.get("image") and not speaker.said:
                speaker.say(_SILENT_LOOK)                # asked what G2 sees, a picture was taken, nothing was said
            elif done and not speaker.said:
                speaker.say("Okay.")                     # never move silently -- always a spoken ack
            speaker.finish()
        else:
            if speaker:
                speaker.finish()
            self._cue.set("speaking")
            secs = list(getattr(turn, "action_seconds", None) or [])
            for i, skill in enumerate(turn.actions):     # move first, then talk
                _do(skill, secs[i] if i < len(secs) else None)
            if turn.speech or turn.actions:
                trace.stamp("voice_start")
            if turn.speech:
                self._speak(turn.speech)
            elif pic.get("image"):
                self._speak(_SILENT_LOOK)
            elif turn.actions:
                self._speak("Okay.")
        if "claude_start" in trace.times:
            trace.meta["actions"] = len(turn.actions)
            trace.meta["streamed"] = bool(getattr(turn, "streamed", False))
            log.info(trace.line())

        if self._memory:
            try:
                self._memory.record(user_text, turn)
                if pic.get("image") and turn.speech and self._last_look is not None and hasattr(self._memory, "record_observation"):
                    labels = ", ".join(sorted({d[0] for d in self._last_look.detections if d[1] >= 0.4}))
                    self._memory.record_observation(turn.speech, labels)
            except Exception:  # noqa: BLE001
                log.exception("memory.record failed")

        self._set_session(bool(getattr(turn, "expects_reply", False)))
        self._cue.set("idle")
