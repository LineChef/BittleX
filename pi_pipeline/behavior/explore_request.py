"""G2 asks before he explores (owner, 2026-11-10: "G2 should request when he wants to explore").

Exploring is still voice-armed and never starts on its own (behavior/mode_controller.py): when G2 has sat idle for a while he asks, aloud, "Can I go exploring? Say Gee Two, yes.", and the roam
starts only on the answer, through the same path as "G2, explore". "No" (or no answer) makes him wait longer before he asks again, up to an hour. `G2_EXPLORE_REQUEST=0` turns the asking off;
`G2_EXPLORE_ASK_AFTER_S` (default 180, under the 300 s sleep delay) is how long he idles first.

`answer_kind(text)` is the one place that reads the answer; `ExploreRequester` is pure logic with a clock (the voice service runs it on a thread, `watch()`), so a test needs no hardware.
"""
from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger("g2.explore_request")

ASK_LINE = "Can I go exploring? Say Gee Two, yes."
DECLINE_LINE = "Okay, maybe later."

_YES = {"yes", "yeah", "yep", "yup", "sure", "okay", "ok", "go ahead", "go for it", "do it", "you can", "go explore", "explore", "yes please", "sure thing", "of course"}
_NO = {"no", "nope", "not now", "not yet", "later", "no thanks", "no thank you", "stay", "stay here", "don't", "do not", "not today", "maybe later"}


def enabled() -> bool:
    return os.environ.get("G2_EXPLORE_REQUEST", "1").strip().lower() not in ("0", "off", "false", "no")


def answer_kind(text: str) -> str | None:
    """"yes", "no" or None for a short spoken answer (the whole reply, punctuation and case ignored, a leading "gee two" allowed). Anything longer or different is not an answer."""
    t = "".join(ch for ch in (text or "").lower() if ch.isalpha() or ch in " '").strip()
    for lead in ("gee two ", "g2 ", "gee gee "):
        if t.startswith(lead):
            t = t[len(lead):].strip()
    if t in _YES:
        return "yes"
    if t in _NO:
        return "no"
    return None


class ExploreRequester:
    """Decides when G2 asks, and holds the question open for `window_s` seconds. `idle_s()` is how long nothing has happened; `eligible()` says he may ask now (resting or standing, nothing running,
    awake, battery fine); `ask()` speaks the line. The wait before the next ask is `ask_after_s`, doubled after each "no" or unanswered ask up to `max_wait_s`, and back to `ask_after_s` after a yes."""

    def __init__(self, *, idle_s, eligible, ask, ask_after_s: float = 180.0, window_s: float = 45.0, max_wait_s: float = 3600.0,
                 clock=time.monotonic, sleep=time.sleep, poll_s: float = 5.0):
        self._idle_s, self._eligible, self._ask = idle_s, eligible, ask
        self._base, self._window, self._max = ask_after_s, window_s, max_wait_s
        self._wait = ask_after_s
        self._clock, self._sleep, self._poll_s = clock, sleep, poll_s
        self._asked_at: float | None = None
        self._last_end: float = clock()          # when the last question ended (answered, declined or timed out): the next wait counts from here
        self._stop = threading.Event()
        self.asks = 0

    def is_open(self) -> bool:
        return self._asked_at is not None and self._clock() - self._asked_at <= self._window

    def tick(self) -> bool:
        """One check; True when G2 asked on this tick."""
        now = self._clock()
        if self._asked_at is not None and now - self._asked_at > self._window:
            self._asked_at, self._last_end = None, now           # no answer: he waits twice as long
            self._wait = min(self._wait * 2.0, self._max)
            log.info("no answer to the explore question: next ask in %.0f s", self._wait)
        if self._asked_at is not None:
            return False
        try:
            if self._idle_s() < self._wait or now - self._last_end < self._wait or not self._eligible():
                return False
        except Exception:  # noqa: BLE001
            return False
        self._asked_at = now
        self.asks += 1
        log.info("asking to explore (idle %.0f s, ask %d)", self._idle_s(), self.asks)
        try:
            self._ask()
        except Exception:  # noqa: BLE001
            log.debug("the explore question could not be spoken", exc_info=True)
        return True

    def answer(self, text: str) -> str | None:
        """The reply to an open question: "yes", "no" or None (not an answer, or no question open). Closes the question on yes or no."""
        if not self.is_open():
            return None
        kind = answer_kind(text)
        if kind is None:
            return None
        self._asked_at, self._last_end = None, self._clock()
        self._wait = self._base if kind == "yes" else min(self._wait * 2.0, self._max)
        log.info("explore question answered: %s", kind)
        return kind

    def watch(self) -> "ExploreRequester":
        def run():
            while not self._stop.is_set():
                self.tick()
                self._sleep(self._poll_s)
        threading.Thread(target=run, name="explore-request", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
