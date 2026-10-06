"""Say what G2 is doing while he explores.

`Narrator.narrate(effects)` looks at the effects a behavior tick produced and, from their `reason` text, picks at most one short spoken line.
Lines are rate-limited (`min_gap_s` between any two, `repeat_s` before the same line again) and handed to a worker thread, so a slow
text-to-speech never delays the behavior loop; a line that arrives while G2 is still talking is dropped, not queued.
"""
from __future__ import annotations

import logging
import queue
import threading
import time

from .driver import EffectKind

log = logging.getLogger("g2.behavior.narrator")

# (reason prefix, kind of line, text). `{x}` is whatever follows the prefix (a detection label).
_RULES = (
    ("approach novelty", "approach", "Something new. I'm going to take a look."),
    ("approach ", "approach", "I'm heading over to the {x}."),
    ("found novelty", "found", "Found something."),
    ("investigate ", "investigate", "Let me look at this {x}."),
    ("new leg", "leg", "Heading off in a new direction."),
    ("leg done", "pause", "Stopping for a moment."),
    ("dwelling", "pause", "Having a good look around."),
    ("on leg", "wander", "Exploring."),
    ("what was that", "sound", "What was that?"),
    ("toward a sound", "sound", "I heard something."),
    ("follow person", "person", "I see someone."),
    ("look at ", "noticed", "I noticed a {x}."),
    ("look-around", "scan", "Looking around."),
    ("recognised ", "recognised", "I recognise someone."),
    ("cliff:", "cliff", "There's an edge. Backing away."),
)


def line_for(reason: str, private=()) -> tuple[str, str] | None:
    """(kind, text) for a behavior reason, or None if it is not worth saying."""
    r = (reason or "").strip().lower()
    for prefix, kind, text in _RULES:
        if r.startswith(prefix):
            x = r[len(prefix):].strip() or "thing"
            if x in {p.lower() for p in private}:                 # a bonded person's name is never spoken
                x = "person"
            return kind, text.format(x=x).replace("the person", "someone").replace("a person", "someone")
    return None


class Narrator:
    def __init__(self, speak, *, min_gap_s: float = 8.0, repeat_s: float = 40.0, clock=time.monotonic, threaded: bool = True, private=()):
        self._private = tuple(private)
        self._speak, self._min_gap, self._repeat, self._clock = speak, min_gap_s, repeat_s, clock
        self._last_any: float | None = None
        self._last_kind: dict[str, float] = {}
        self._q: "queue.Queue[str]" = queue.Queue(maxsize=1)
        self.enabled = True
        self.said: list[str] = []
        self._threaded = threaded
        if threaded:
            threading.Thread(target=self._run, name="narrator", daemon=True).start()

    def _run(self) -> None:
        while True:
            text = self._q.get()
            try:
                self._speak(text)
            except Exception:  # noqa: BLE001 -- narration must never take the behavior loop down
                log.debug("narration speak failed", exc_info=True)

    def narrate(self, effects) -> str | None:
        if not self.enabled:
            return None
        now = self._clock()
        for e in effects:
            if e.kind in (EffectKind.CHIRP, EffectKind.DIAG, EffectKind.CAPTURE, EffectKind.CUE, EffectKind.POWER):
                continue
            hit = line_for(e.reason, self._private)
            if hit is None:
                continue
            kind, text = hit
            if self._last_any is not None and now - self._last_any < self._min_gap:
                continue
            if now - self._last_kind.get(kind, -1e9) < self._repeat:
                continue
            if self._threaded:
                try:
                    self._q.put_nowait(text)
                except queue.Full:
                    return None                               # still talking: drop this one
            else:
                self._speak(text)
            self._last_any = self._last_kind[kind] = now
            self.said.append(text)
            log.info("narrate: %s", text)
            return text
        return None


def attach(bindings, narrator: Narrator) -> None:
    """Make `bindings.dispatch` narrate after it has acted."""
    inner = bindings.dispatch

    def dispatch(tick_or_effects):
        out = inner(tick_or_effects)
        effects = getattr(tick_or_effects, "effects", tick_or_effects)
        try:
            narrator.narrate(list(effects))
        except Exception:  # noqa: BLE001
            log.debug("narration failed", exc_info=True)
        return out

    bindings.dispatch = dispatch
