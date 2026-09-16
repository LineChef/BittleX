"""Spoken meta-commands the voice loop handles itself, without calling Claude.

These are privacy / session controls, not conversation:

- **"forget that"** and friends  -> drop everything recorded since the wake word
  (this session's exchanges + facts). See `Memory.forget_session`.
- **"go to sleep"** -> end the follow-up window now, so the next turn needs the
  wake word again.

Matching is deliberately strict (exact phrase, or the phrase followed by
trailing speech-to-text cruft) so a normal sentence that merely contains the
word "forget" or "sleep" is never swallowed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..personality.gir import level_to_intensity as _gir_level_to_intensity

# filler words stripped before matching, so "hey G2, forget that please" ==
# "forget that"
_STRIP_TOKENS = {
    "hey", "ok", "okay", "so", "um", "uh", "please", "now", "g2", "gee", "two",
    "geetwo", "robot",
}

_APOS = re.compile(r"['’`]")
_PUNCT = re.compile(r"[^\w\s]")

_FORGET = (
    "forget that",
    "forget it",
    "forget this",
    "forget what i just said",
    "forget what i said",
    "forget that conversation",
    "forget this conversation",
    "scratch that",
    "delete that",
    "dont remember that",
    "do not remember that",
    "dont save that",
    "do not save that",
)

_SLEEP = (
    "go to sleep",
)

# Emergency stop -- a hard, latching freeze. Matched loosely (these phrases are
# never a normal request) and handled before anything else, no Claude call.
_HALT = (
    "emergency stop", "freeze", "halt", "stop stop stop", "stop moving",
    "dont move", "hold still", "abort",
)
_RESUME = (
    "resume", "you can move", "as you were", "unfreeze", "carry on",
    "at ease", "you can go", "release",
)

# 'Shut down' -- graceful: lie down first, then go dormant (NOT the emergency
# freeze, and NOT an OS power-off).
_SHUTDOWN = (
    "shut down", "shutdown", "power down", "power off", "go dormant",
    "shut yourself down", "time to shut down",
)

# Tier 1 roam -- voice-armed only ("G2, go ahead and look around").
_EXPLORE = (
    "go ahead and look around", "look around", "have a look around",
    "exploration mode", "explore", "go explore", "go and explore",
    "check things out", "go for a wander", "wander around",
)
_UNEXPLORE = (
    "stop exploring", "stop looking around", "stop wandering", "come back",
    "thats enough", "that will do",
)

# "Come here" -- a directed walk toward you (distinct from "come back" above).
# No bare "come" (ambiguous with "come back"); needs "come here" / "come to me".
_COME = (
    "come here", "come to me", "over here", "here boy", "walk to me",
    "come over here",
)

# chirps on/off -- live-toggleable, matches Features.sound_cues in spirit but
# not backed by it (that flag is boot-time only; this is a runtime override).
_CHIRPS_ON = (
    "turn on your chirps", "turn on chirps", "enable chirps", "chirps on",
    "start chirping", "enable your chirping",
)
_CHIRPS_OFF = (
    "turn off your chirps", "turn off chirps", "disable chirps", "chirps off",
    "stop chirping", "no more chirping", "quiet the chirps",
)

# narration verbosity: "narration level 4", "set verbosity to 2" -- a 1-5
# level, parsed by _parse_named_level below. Distinct wording/name from the
# mood-nudging _REBUFF list below ("be quiet" etc. nudges mood, it doesn't
# touch this setting) so the two never collide.
_NARRATION_NAMES = ("narration", "verbosity")

# character mode: "enable gir mode", "turn on gir", "gir mode off", "set gir to 70"
_CHAR_NAMES = ("gir",)
_CHAR_ON = ("enable", "turn on", "switch on", "activate", "start", "go into", "be",
            "become", "set", "make", "put")
_CHAR_OFF = ("disable", "turn off", "switch off", "deactivate", "stop", "exit",
             "leave", "quit", "cancel", "end")


def _normalize(text: str) -> str:
    t = _PUNCT.sub(" ", _APOS.sub("", text.lower()))
    return " ".join(w for w in t.split() if w not in _STRIP_TOKENS)


def _hit(norm: str, phrases: tuple[str, ...]) -> bool:
    return any(norm == p or norm.startswith(p + " ") for p in phrases)


@dataclass
class CharacterCommand:
    name: str            # which character, e.g. "gir"
    on: bool             # enable vs disable
    level: float | None  # requested intensity 0..1, or None to use the default


_LEVEL_WORDS = {"zero": 0.0, "quarter": 0.25, "half": 0.5, "medium": 0.5,
                "full": 1.0, "max": 1.0, "maximum": 1.0, "low": 0.25, "high": 0.85}


def _parse_named_level(raw: str, lo: int = 1, hi: int = 5) -> int | None:
    """Parse 'level N' (a small integer, 1..hi) -- the primary way to set
    gir/narration intensity now. Kept separate from _parse_level below (which
    still handles old-style 'to 70%' / 'to full' phrasing for gir) so a
    number after 'level' is never ambiguous with a raw percentage."""
    m = re.search(r"\blevel\s+(\d{1,2})\b", raw)
    if not m:
        return None
    n = int(m.group(1))
    return n if lo <= n <= hi else None


def _parse_level(raw: str) -> float | None:
    """Parse a requested intensity from raw (un-normalised) lowercased text --
    'to 0.7', 'at 70', 'to full'. Old-style percentage/word phrasing, kept
    working for gir alongside the new 'level N' scale above."""
    m = re.search(r"(?:to|at)\s+(?:(\d+(?:\.\d+)?)\s*(%|percent)?|([a-z]+))", raw)
    if not m:
        return None
    if m.group(1):
        v = float(m.group(1))
        if m.group(2) or v > 1.0:
            v /= 100.0
        return max(0.0, min(1.0, v))
    return _LEVEL_WORDS.get(m.group(3))


def _has_verb(norm: str, verbs: tuple[str, ...]) -> bool:
    words = set(norm.split())
    return any((" " in v and v in norm) or (" " not in v and v in words) for v in verbs)


def parse_character_command(text: str) -> CharacterCommand | None:
    """Recognise 'enable/disable <name> mode' (optionally '... level <1-5>',
    the primary form -- or the old '... to <percent/word>' phrasing, still
    understood)."""
    n = _normalize(text)
    if not n:
        return None
    raw = text.lower()
    for name in _CHAR_NAMES:
        if name not in n.split():
            continue
        named = _parse_named_level(raw, hi=5)
        level = _gir_level_to_intensity(named) if named is not None else _parse_level(raw)
        # OFF is checked first so "stop being gir" / "no more gir" win.
        if (_has_verb(n, _CHAR_OFF)
                or re.search(rf"\b{name}\b(?:\s+mode)?\s+off\b", n)
                or re.search(rf"\b(?:no|not|less)\b(?:\s+\w+)?\s+{name}\b", n)):
            return CharacterCommand(name, on=False, level=None)
        if (_has_verb(n, _CHAR_ON)
                or re.search(rf"\b{name}\b(?:\s+mode)?\s+on\b", n)
                or level is not None):            # naming a level == turn it on / adjust
            return CharacterCommand(name, on=True, level=level)
    return None


def parse_narration_command(text: str) -> int | None:
    """Recognise 'narration level <1-5>' / 'verbosity level <1-5>' /
    'set narration to <1-5>' -> the requested level, or None."""
    n = _normalize(text)
    if not n or not any(name in n.split() for name in _NARRATION_NAMES):
        return None
    return _parse_named_level(text.lower(), hi=5)
    return None


# Short reproachful phrases -> nudge the mood model to SUBDUED for a while.
# Advisory only (no command action), so a loose match is low-cost; still kept
# tight so ordinary sentences don't trip it. Phrases are already in the form
# `_normalize` produces (lowercased, no punctuation, filler words dropped).
_REBUFF = (
    "leave me alone", "stop it", "stop that", "be quiet", "shut up",
    "go away", "quit it", "cut it out", "knock it off", "stop talking",
    "thats enough", "settle down", "calm down", "youre annoying",
    "stop bothering me",
)


def looks_like_rebuff(text: str) -> bool:
    """True for a short 'that's enough / leave me alone' style correction."""
    n = _normalize(text)
    return bool(n) and any(p in n for p in _REBUFF)


def match_local_command(text: str) -> str | None:
    """Return ``"halt"``, ``"resume"``, ``"shutdown"``, ``"come"``, ``"explore"``,
    ``"unexplore"``, ``"forget"``, ``"sleep"``, ``"chirps_on"``, ``"chirps_off"``,
    ``"narration_level"``, ``"character"``, or ``None``. Checked in that order
    -- an emergency stop wins over everything."""
    n = _normalize(text)
    if not n:
        return None
    if _has_verb(n, _HALT):
        return "halt"
    if _has_verb(n, _RESUME):
        return "resume"
    if _hit(n, _SHUTDOWN) or _has_verb(n, ("shutdown",)):
        return "shutdown"
    if _hit(n, _COME):
        return "come"
    if _hit(n, _EXPLORE) or _has_verb(n, ("explore",)):
        return "explore"
    if _hit(n, _UNEXPLORE):
        return "unexplore"
    if _hit(n, _FORGET):
        return "forget"
    if _hit(n, _SLEEP):
        return "sleep"
    if _hit(n, _CHIRPS_ON):
        return "chirps_on"
    if _hit(n, _CHIRPS_OFF):
        return "chirps_off"
    if parse_narration_command(text) is not None:
        return "narration_level"
    if parse_character_command(text) is not None:
        return "character"
    return None
