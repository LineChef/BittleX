"""A small voice-command listener for an exploration session (the full voice loop is not running then).

Wake word, then one short command, checked against the local command table only -- no Claude, no API calls:
  "emergency stop" / "freeze" -> halt;  "resume" -> release;  "go ahead and look around" -> arm roam;  "that's enough" / "come back" -> disarm;
  "end exploration mode" -> end the session (the voice service comes back; no emergency stop involved);  "shut down" -> end the session too (never powers anything off);  "tell me what you see" -> say what the detector sees;
  "this is a mug" / "remember this as my mug" -> look at it and take a picture saved under that name (the driver's survey, behavior/survey.py).
"""
from __future__ import annotations

import logging
import threading
import time

from ..vision.describe_local import describe
from ..voice.commands import match_local_command
from ..voice.loop import asks_what_g2_sees
from .survey import parse_naming

log = logging.getLogger("g2.behavior.explore_listener")


class ExploreListener:
    def __init__(self, wake, stt, say, rt, frame, *, on_arm=None, on_stop=None, listen_s: float = 8.0, settle_s: float = 1.2):
        self._wake, self._stt, self._say, self._rt, self._frame = wake, stt, say, rt, frame
        self._on_arm, self._on_stop, self._listen_s = on_arm, on_stop, listen_s
        self._settle_s = settle_s
        self._done = threading.Event()

    def start(self) -> "ExploreListener":
        threading.Thread(target=self._run, name="explore-listener", daemon=True).start()
        return self

    def stop(self) -> None:
        self._done.set()

    def _run(self) -> None:
        while not self._done.is_set():
            try:
                self._wake.wait()
                if self._done.is_set():
                    break
                log.info("wake word heard: listening for a command (%.0f s)", self._listen_s)
                try:
                    self._rt.post(listen_hold=True)             # stand still: a walking G2's servos drown the microphone (2026-10-08: three wake words, no command heard)
                except Exception:  # noqa: BLE001
                    log.debug("could not ask for a listening pause", exc_info=True)
                time.sleep(self._settle_s)                     # let him stop before the window opens
                text = (self._stt.listen(timeout_s=self._listen_s) or "").strip()
                if not text:
                    log.info("nothing recognized after the wake word")
                    self._reply("I didn't catch that.")                  # so you can tell the wake word registered and the speech did not
                    continue
                log.info("heard: %r", text)
                reply = self.handle(text)
                if reply is None:
                    log.info("not a command I know in exploration: %r", text)
                    self._reply("I didn't understand that.")
                else:
                    log.info("answered: %r", reply)
            except Exception:  # noqa: BLE001 -- a listener hiccup must not end the session
                log.exception("explore listener error")

    def handle(self, text: str) -> str | None:
        cmd = match_local_command(text)
        if cmd == "halt":
            self._rt.halt()
            return self._reply("Stopping.")
        if cmd == "resume":
            self._rt.release()
            return self._reply("Okay.")
        if cmd == "explore":
            if self._on_arm:
                self._on_arm()
            self._rt.post(arm_explore=True)
            return self._reply("Okay, exploring.")
        if cmd in ("unexplore", "sleep"):
            self._rt.post(disarm_explore=True)
            return self._reply("Okay, that's enough.")
        if cmd == "restart_voice":
            if self._on_stop:
                self._on_stop()                       # closes the session; the voice service then starts fresh
            return self._reply("Okay, restarting my voice.")
        if cmd == "end_explore":
            if self._on_stop:
                self._on_stop()                       # closes the session; the voice service comes back
            return self._reply("Okay, ending exploration mode.")
        if cmd == "shutdown":
            if self._on_stop:
                self._on_stop()
            return self._reply("Ending the exploration test.")
        if cmd is None:
            name = parse_naming(text)
            if name:
                log.info("naming request: %r (bow, look up, stand, then one picture saved under that name)", name)
                self._rt.post(name_request=name)
                return self._reply(f"Okay, let me look at the {name}.")
        if cmd is None and asks_what_g2_sees(text):
            return self._reply(describe(list(self._frame() or [])))
        return None

    def _reply(self, text: str) -> str:
        try:
            self._say(text)
        except Exception:  # noqa: BLE001
            log.debug("say failed", exc_info=True)
        return text
