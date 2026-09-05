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


def _normalize(text: str) -> str:
    t = _PUNCT.sub(" ", _APOS.sub("", text.lower()))
    return " ".join(w for w in t.split() if w not in _STRIP_TOKENS)


def _hit(norm: str, phrases: tuple[str, ...]) -> bool:
    return any(norm == p or norm.startswith(p + " ") for p in phrases)


def match_local_command(text: str) -> str | None:
    """Return ``"forget"``, ``"sleep"``, or ``None``."""
    n = _normalize(text)
    if not n:
        return None
    if _hit(n, _FORGET):
        return "forget"
    if _hit(n, _SLEEP):
        return "sleep"
    return None
