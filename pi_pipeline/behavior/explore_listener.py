"""A small voice-command listener for an exploration session (the full voice loop is not running then).

Wake word, then one short command, checked against the local command table only -- no Claude, no API calls:
  "emergency stop" / "freeze" -> halt;  "resume" -> release;  "go ahead and look around" -> arm roam;  "that's enough" / "come back" -> disarm;
  "shut down" -> end the session (never powers anything off);  "tell me what you see" -> say what the detector sees;
  "this is a mug" / "remember this as my mug" -> look at it and take a picture saved under that name (the driver's survey, behavior/survey.py).
"""
from __future__ import annotations

import logging
import threading

from ..vision.describe_local import describe
from ..voice.commands import match_local_command
from ..voice.loop import asks_what_g2_sees
from .survey import parse_naming

log = logging.getLogger("g2.behavior.explore_listener")


class ExploreListener:
    def __init__(self, wake, stt, say, rt, frame, *, on_arm=None, on_stop=None, listen_s: float = 8.0):
        self._wake, self._stt, self._say, self._rt, self._frame = wake, stt, say, rt, frame
        self._on_arm, self._on_stop, self._listen_s = on_arm, on_stop, listen_s
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
                text = (self._stt.listen(timeout_s=self._listen_s) or "").strip()
                if text:
                    log.info("heard: %r", text)
                    self.handle(text)
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
        if cmd == "shutdown":
            if self._on_stop:
                self._on_stop()
            return self._reply("Ending the exploration test.")
        if cmd is None:
            name = parse_naming(text)
            if name:
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
