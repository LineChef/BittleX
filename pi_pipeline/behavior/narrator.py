"""Say what G2 is doing while he explores.

`Narrator.narrate(effects)` looks at the effects a behavior tick produced and, from their `reason` text, picks at most one short spoken line.
Lines are rate-limited (`min_gap_s` between any two, `repeat_s` before the same line again) and handed to a worker thread, so a slow
text-to-speech never delays the behavior loop; a line that arrives while G2 is still talking is dropped, not queued.
"""
from __future__ import annotations

import logging
import queue
import re
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
    ("new leg", "leg", "Searching."),
    ("leg done", "pause", "Stopping for a moment to look around."),
    ("dwelling", "pause", "Having a good look around."),
    ("on leg", "wander", "Exploring."),
    ("what was that", "sound", "What was that?"),
    ("toward a sound", "sound", "I heard something."),
    ("follow person", "person", "I see someone."),
    ("look at ", "noticed", "I noticed a {x}."),
    ("look-around", "scan", "Looking around."),
    ("recognised ", "recognised", "I recognise someone."),
    ("cliff:", "cliff", "There's an edge. Backing away."),
    ("hit: back up", "hit", "Oof! I bumped into something. Backing up."),
    ("hit: turn around", "hit_turn", "Turning around."),
    ("straight first", "straight", "Patrolling."),
)

# Wall turns (behavior/driver.py `_wall_reflex`): "wall ahead (8 in, 3 groups): turn right" / "wall blocked (0 in, 5 groups): turn left"; said with what he sees and which way he goes
_WALL = re.compile(r"^wall (ahead|blocked) \(([\d.]+) in.*?\): turn (left|right)")


def fixed_lines() -> list[str]:
    """Every narration sentence that does not depend on a detection label, for pre-making the speech (voice/speech_cache.py)."""
    out = [t for _p, _k, t in _RULES if "{x}" not in t]
    for side in ("left", "right"):
        out.append(f"I'm right up against a wall. Turning {side}.")
        out += [f"I see a wall about {n} inches ahead. Turning {side}." for n in range(7, 31)]
    return out


def line_for(reason: str, private=()) -> tuple[str, str] | None:
    """(kind, text) for a behavior reason, or None if it is not worth saying."""
    r = (reason or "").strip().lower()
    m = _WALL.match(r)
    if m:
        state, inches, side = m.groups()
        if state == "blocked" or float(inches) <= 6:
            return "wall", f"I'm right up against a wall. Turning {side}."
        return "wall", f"I see a wall about {int(round(float(inches)))} inches ahead. Turning {side}."
    for prefix, kind, text in _RULES:
        if r.startswith(prefix):
            x = r[len(prefix):].strip() or "thing"
            if x in {p.lower() for p in private}:                 # a bonded person's name is never spoken
                x = "person"
            return kind, text.format(x=x).replace("the person", "someone").replace("a person", "someone")
    return None


class Narrator:
    def __init__(self, speak, *, min_gap_s: float = 5.0, repeat_s: float = 25.0, clock=time.monotonic, threaded: bool = True, private=(), prepare=None, play=None):
        self._prepare, self._play = (prepare, play) if prepare and play else (None, None)      # synthesise and play apart, so a line that took too long to make can still be dropped
        self.late_s = 8.0                        # a line not ready to play this long after it was decided is dropped (the speech lag, 2026-10-10: heard 7 to 17 s late)
        self._private = tuple(private)
        self._speak, self._min_gap, self._repeat, self._clock = speak, min_gap_s, repeat_s, clock
        self._last_any: float | None = None
        self._last_kind: dict[str, float] = {}
        self._q: "queue.Queue[tuple[float, str]]" = queue.Queue(maxsize=1)
        self.enabled = True
        self.stale_s = 6.0                       # a line queued longer than this is old news (2026-10-08: lines were spoken 4-120 s late): dropped
        self.said: list[str] = []
        self._threaded = threaded
        if threaded:
            threading.Thread(target=self._run, name="narrator", daemon=True).start()

    def _run(self) -> None:
        while True:
            queued_at, text = self._q.get()
            if not self.enabled or self._clock() - queued_at > self.stale_s:
                log.info("narration dropped (%s): %s", "muted" if not self.enabled else "stale", text)
                continue
            try:
                self._say_timed(queued_at, text)
            except Exception:  # noqa: BLE001 -- narration must never take the behavior loop down
                log.debug("narration speak failed", exc_info=True)

    def _say_timed(self, queued_at: float, text: str) -> None:
        """Speak one line and log where the time went (queue, synthesis, waiting for the speaker, playing), so a late line can be traced."""
        t0 = self._clock()
        if self._prepare is None:
            self._speak(text)
            log.info("narration timing: queued %.1f s, speech call %.1f s: %s", t0 - queued_at, self._clock() - t0, text)
            return
        item = self._prepare(text)
        t1 = self._clock()
        if item is None:
            return
        if not self.enabled or t1 - queued_at > self.late_s:
            log.info("narration dropped (%s): %s (queued %.1f s, synthesis %.1f s)", "muted" if not self.enabled else "late", text, t0 - queued_at, t1 - t0)
            return
        self._play(item)
        t2 = self._clock()
        log.info("narration timing: queued %.1f s, synthesis %.1f s, play %.1f s (incl. waiting for the speaker), %.1f s from decision to end: %s", t0 - queued_at, t1 - t0, t2 - t1, t2 - queued_at, text)

    def quiet(self, on: bool) -> None:
        """Mute narration (a command window is open: G2 must hear, not talk) and forget a line that is waiting."""
        self.enabled = not on
        if on:
            try:
                while True:
                    self._q.get_nowait()
            except queue.Empty:
                pass

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
                    self._q.put_nowait((now, text))
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
