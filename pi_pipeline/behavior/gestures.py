"""Expressive gestures -- the little Petoi behaviours G2 fires to feel alive:
idle fidgets, a greeting when it meets someone, an excited hop.

Pure logic + a clock, same shape as `idle_posture.py` / `mode_controller.py`.
Each `Gesture` maps to an OpenCat skill token (`link/opencat.py`); the caller
sends `link.send(GESTURE_TOKEN[g])` and waits for it to finish. These are
*flavour* -- never emitted while a task/conversation is active, mid-walk, or
unlevel; the caller passes those gates in.

  IDLE FIDGET   -- while sitting/idle, occasionally: stretch, scratch, sniff,
                   a nod, shift-sit. Weighted, with per-gesture + global
                   cooldowns so it's sparse and non-repetitive.
  GREETING      -- picked once when enrollment / a "say hi" moment starts:
                   wave, shake a paw, or a play-bow.
  EXCITED       -- a hop, for "found something great" / recognised a bonded
                   person after a while. Rate-limited hard (it's loud + jars).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from ..link import opencat


class Gesture(Enum):
    NONE = "none"
    STRETCH = "stretch"
    SCRATCH = "scratch"
    SNIFF = "sniff"
    NOD = "nod"
    SIT_SHIFT = "sit_shift"      # re-settle the sit -- smallest fidget
    WAVE = "wave"
    SHAKE_PAW = "shake_paw"
    PLAY_BOW = "play_bow"
    HIGH_FIVE = "high_five"
    HOP = "hop"


GESTURE_TOKEN = {
    Gesture.STRETCH: opencat.STRETCH,
    Gesture.SCRATCH: opencat.SCRATCH,
    Gesture.SNIFF: opencat.SNIFF,
    Gesture.NOD: opencat.NOD,
    Gesture.SIT_SHIFT: opencat.SIT,
    Gesture.WAVE: opencat.WAVE,
    Gesture.SHAKE_PAW: opencat.SHAKE_PAW,
    Gesture.PLAY_BOW: opencat.PLAY_BOW,
    Gesture.HIGH_FIVE: opencat.HIGH_FIVE,
    Gesture.HOP: opencat.JUMP,
}

_IDLE_SET = (Gesture.STRETCH, Gesture.SCRATCH, Gesture.SNIFF, Gesture.NOD, Gesture.SIT_SHIFT)
_GREETING_SET = (Gesture.WAVE, Gesture.SHAKE_PAW, Gesture.PLAY_BOW)


@dataclass
class GestureConfig:
    idle_min_quiet_s: float = 12.0       # must be idle at least this long before a fidget
    idle_interval_s: float = 45.0        # mean gap between idle fidgets (caller may jitter)
    idle_cooldown_s: float = 90.0        # a given idle gesture can't repeat within this
    explore_sniff_cooldown_s: float = 20.0  # SNIFF at a novel find, min gap
    hop_cooldown_s: float = 300.0        # excited hop is loud -- keep it rare
    greet_cooldown_s: float = 45.0       # one greeting gesture per meeting, then quiet
    # weights for the idle pick (higher = more often). SIT_SHIFT is the safe default.
    idle_weights: dict = field(default_factory=lambda: {
        Gesture.SIT_SHIFT: 3.0, Gesture.NOD: 2.0, Gesture.STRETCH: 2.0,
        Gesture.SCRATCH: 1.5, Gesture.SNIFF: 1.0})


class GesturePicker:
    def __init__(self, cfg: GestureConfig | None = None, *, clock=time.monotonic, rng=None):
        import random
        self.cfg = cfg or GestureConfig()
        self._clock = clock
        self._rng = rng or random.Random()
        self._last: dict[Gesture, float] = {}
        self._last_any_idle = 0.0
        self._last_greet = 0.0
        self._last_hop = 0.0
        self._reason = "init"

    @property
    def last_reason(self) -> str:
        return self._reason

    def _fired(self, g: Gesture, now: float) -> None:
        self._last[g] = now

    def _cool(self, g: Gesture, now: float, window: float) -> bool:
        return now - self._last.get(g, -1e9) >= window

    # --- idle fidget ---------------------------------------------------------
    def update(self, now: float | None = None, *, idle_quiet_s: float = 0.0,
               can_gesture: bool = True) -> Gesture:
        """Call each tick while idle. `can_gesture` is the caller's gate
        (sitting, level, not in conversation, no task). Returns a Gesture to
        run, or NONE."""
        now = self._clock() if now is None else now
        if not can_gesture or idle_quiet_s < self.cfg.idle_min_quiet_s:
            self._reason = "gated / not idle long enough"
            return Gesture.NONE
        # Poisson-ish: ~one per idle_interval_s. Caller ticks at a known rate; we
        # just gate on the min gap and roll a die scaled so the mean comes out right.
        if now - self._last_any_idle < self.cfg.idle_interval_s * 0.5:
            self._reason = "within min idle gap"
            return Gesture.NONE
        due = (now - self._last_any_idle) / self.cfg.idle_interval_s
        if self._rng.random() > min(1.0, 0.5 * due):
            self._reason = f"not due yet ({due:.1f})"
            return Gesture.NONE
        pool = [(g, self.cfg.idle_weights.get(g, 1.0)) for g in _IDLE_SET
                if self._cool(g, now, self.cfg.idle_cooldown_s)]
        if not pool:
            self._reason = "all idle gestures cooling down"
            return Gesture.NONE
        g = self._weighted(pool)
        self._fired(g, now)
        self._last_any_idle = now
        self._reason = f"idle fidget: {g.value}"
        return g

    # --- explicit triggers ------------------------------------------------
    def greeting(self, now: float | None = None) -> Gesture:
        """One expressive greeting at the start of a meeting / enrollment."""
        now = self._clock() if now is None else now
        if now - self._last_greet < self.cfg.greet_cooldown_s:
            self._reason = "greeting on cooldown"
            return Gesture.NONE
        g = self._weighted([(x, 1.0) for x in _GREETING_SET])
        self._last_greet = now
        self._fired(g, now)
        self._reason = f"greeting: {g.value}"
        return g

    def sniff_find(self, now: float | None = None) -> Gesture:
        """SNIFF when the explore layer lands on a novel object."""
        now = self._clock() if now is None else now
        if not self._cool(Gesture.SNIFF, now, self.cfg.explore_sniff_cooldown_s):
            self._reason = "sniff cooling down"
            return Gesture.NONE
        self._fired(Gesture.SNIFF, now)
        self._reason = "sniff a find"
        return Gesture.SNIFF

    def excited_hop(self, now: float | None = None) -> Gesture:
        """A hop for recognising a bonded person after a while / a big find.
        Loud -- hard rate limit."""
        now = self._clock() if now is None else now
        if now - self._last_hop < self.cfg.hop_cooldown_s:
            self._reason = "hop on cooldown"
            return Gesture.NONE
        self._last_hop = now
        self._fired(Gesture.HOP, now)
        self._reason = "excited hop"
        return Gesture.HOP

    def _weighted(self, pool):
        tot = sum(w for _, w in pool)
        r = self._rng.random() * tot
        for g, w in pool:
            r -= w
            if r <= 0:
                return g
        return pool[-1][0]
