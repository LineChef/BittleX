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


def _parse_level(raw: str) -> float | None:
    """Parse a requested intensity from raw (un-normalised) lowercased text --
    'to 0.7', 'at 70', 'level 70%', 'to full'."""
    m = re.search(r"(?:to|at|level)\s+(?:(\d+(?:\.\d+)?)\s*(%|percent)?|([a-z]+))", raw)
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
    """Recognise 'enable/disable <name> mode' (optionally '... to <level>')."""
    n = _normalize(text)
    if not n:
        return None
    raw = text.lower()
    for name in _CHAR_NAMES:
        if name not in n.split():
            continue
        level = _parse_level(raw)
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
    """Return ``"forget"``, ``"sleep"``, ``"character"``, or ``None``."""
    n = _normalize(text)
    if not n:
        return None
    if _hit(n, _FORGET):
        return "forget"
    if _hit(n, _SLEEP):
        return "sleep"
    if parse_character_command(text) is not None:
        return "character"
    return None
