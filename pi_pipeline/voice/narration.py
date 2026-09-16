"""Narration verbosity -- how much G2 explains its own actions and reasoning
out loud. Voice-facing 1-5 level scale, same pattern as gir mode's
(`personality/gir.py`) -- kept small deliberately: 5 levels each mean
something genuinely distinguishable, rather than padding out to 10 with thin,
invented gradations. Session-only: resets to DEFAULT_LEVEL on restart,
doesn't persist across runs (unlike gir's character_state).

Level 3 (default) has an empty hint -- Claude's ordinary behavior, no special
instruction -- so "no command given yet" and "explicitly set to level 3" are
the same state.
"""
from __future__ import annotations

LEVELS = 5
DEFAULT_LEVEL = 3

_DESCRIPTIONS: dict[int, str] = {
    1: "silent -- act without narrating, just the direct answer",
    2: "terse -- brief replies, no explanation of routine actions",
    3: "normal -- Claude's default balance, no special instruction",
    4: "detailed -- explain actions and reasoning as you go",
    5: "maximum -- explain everything you do and why, in detail",
}

_HINTS: dict[int, str] = {
    1: "Stay silent about your own actions and reasoning; give only the "
       "direct answer, nothing else.",
    2: "Keep replies brief; don't explain routine actions or reasoning "
       "unless asked.",
    3: "",
    4: "Briefly explain what you're doing and why as you take actions.",
    5: "Explain everything you do and why, in detail, as you go.",
}


def describe_level(n: int) -> str:
    return _DESCRIPTIONS.get(n, _DESCRIPTIONS[DEFAULT_LEVEL])


def hint_for_level(n: int) -> str:
    return _HINTS.get(n, _HINTS[DEFAULT_LEVEL])
