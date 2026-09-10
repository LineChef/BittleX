"""Mood from recent events (behaviour-ideas B6).

A slow-moving mood, derived from how much interaction there's been lately, that
biases idle behaviour and phrasing. NOT the fast per-utterance cue -- this is
"G2 has been alone all afternoon" territory.

  MoodModel.update(now, last_interaction_s=..., exchanges_recent=...,
                   rebuffed_recent=False) -> Mood
  mood.phrasing_hint()  -> a sentence to append to the system prompt (or "")
  mood.idle_bias()      -> IdleBias(sit_mult, rest_mult, seek_attention)

Pure logic + a clock, like the rest of `personality/`. First-cut thresholds;
tune once there's real multi-session history.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class Mood(Enum):
    NEUTRAL = "neutral"
    CONTENT = "content"      # regular friendly interaction lately
    PLAYFUL = "playful"      # lots of recent back-and-forth
    LONELY = "lonely"        # long silence
    SUBDUED = "subdued"      # recently told off / rebuffed -- lie low a while


@dataclass
class MoodConfig:
    lonely_after_s: float = 45 * 60.0       # silence this long -> LONELY
    content_within_s: float = 20 * 60.0     # last interaction within this -> at least CONTENT
    playful_exchanges: int = 6              # this many recent exchanges -> PLAYFUL
    subdued_s: float = 8 * 60.0             # a rebuff keeps G2 SUBDUED this long


@dataclass
class IdleBias:
    sit_mult: float = 1.0        # multiply IdlePosture sit/rest delays
    rest_mult: float = 1.0
    seek_attention: bool = False  # LONELY -> a little attention-seeking wander


_HINTS = {
    Mood.NEUTRAL: "",
    Mood.CONTENT: "You've had steady company today; you feel settled and warm.",
    Mood.PLAYFUL: "There's been a lot of back-and-forth lately; you're in a bouncy, playful mood.",
    Mood.LONELY:  "You've been on your own for a while; a little wistful, keen for company.",
    Mood.SUBDUED: "You were told off recently; keep it low-key and a touch careful for now.",
}


class MoodModel:
    def __init__(self, cfg: MoodConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or MoodConfig()
        self._clock = clock
        self._mood = Mood.NEUTRAL
        self._rebuffed_at: float | None = None

    @property
    def mood(self) -> Mood:
        return self._mood

    def note_rebuff(self, now: float | None = None) -> None:
        """Call on a 'stop it' / 'leave me alone' / harsh correction."""
        self._rebuffed_at = self._clock() if now is None else now

    def update(self, now: float | None = None, *, last_interaction_s: float | None = None,
               exchanges_recent: int = 0) -> Mood:
        now = self._clock() if now is None else now
        c = self.cfg

        if self._rebuffed_at is not None and now - self._rebuffed_at < c.subdued_s:
            self._mood = Mood.SUBDUED
            return self._mood

        if last_interaction_s is None:
            # no recency data (runtime not feeding the memory store) -> no mood
            # colouring. "Unknown" must not read as "lonely".
            self._mood = Mood.NEUTRAL
            return self._mood

        gap = last_interaction_s
        if gap >= c.lonely_after_s:
            self._mood = Mood.LONELY
        elif exchanges_recent >= c.playful_exchanges and gap <= c.content_within_s:
            self._mood = Mood.PLAYFUL
        elif gap <= c.content_within_s:
            self._mood = Mood.CONTENT
        else:
            self._mood = Mood.NEUTRAL
        return self._mood

    def phrasing_hint(self) -> str:
        return _HINTS[self._mood]

    def idle_bias(self) -> IdleBias:
        if self._mood is Mood.LONELY:
            return IdleBias(sit_mult=0.6, rest_mult=0.7, seek_attention=True)
        if self._mood is Mood.SUBDUED:
            return IdleBias(sit_mult=1.4, rest_mult=1.3, seek_attention=False)
        if self._mood is Mood.PLAYFUL:
            return IdleBias(sit_mult=1.2, rest_mult=1.0, seek_attention=False)
        return IdleBias()
