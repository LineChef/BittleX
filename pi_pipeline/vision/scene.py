"""Turn detections into words.

- `summarize(frame)` -- a plain, deterministic description of what's in view.
  No LLM. Used for logging and as the input to `narrate`.
- `narrate(frame, ask)` -- a spoken-style answer to "what do you see", where
  `ask` is any `str -> str` callable (inject the voice layer's Claude call, or a
  dedicated one). `vision` never imports `voice`.
"""
from __future__ import annotations

from collections import Counter

from .feed import Frame


def _bearing_word(bearing: str) -> str:
    return {"left": "on my left", "right": "on my right", "ahead": "dead ahead"}[bearing]


def _distance_word(area: float) -> str:
    if area >= 0.22:
        return "right in front of"
    if area >= 0.10:
        return "close to"
    if area >= 0.03:
        return "a little way from"
    return "far from"


def summarize(frame: Frame, min_confidence: float = 0.4) -> str:
    seen = [d for d in frame if d.confidence >= min_confidence]
    if not seen:
        return "Nothing notable in view."
    parts = []
    for d in sorted(seen, key=lambda d: -d.area):
        parts.append(f"a {d.label} {_distance_word(d.area)} me, {_bearing_word(d.bearing)}")
    counts = Counter(d.label for d in seen)
    lead = ", ".join(f"{n} {lbl}{'s' if n > 1 else ''}" for lbl, n in counts.items())
    return f"In view: {lead}. " + "; ".join(parts) + "."


def narrate(frame: Frame, ask, min_confidence: float = 0.4) -> str:
    """`ask(prompt) -> str`. Returns G2's spoken answer.

    Privacy: this sends only the *text* description built from detections
    (labels + rough positions) to `ask` -- never a raw image. Do not change that
    without a deliberate opt-in: a photo of the home/people going to a cloud LLM
    is a different privacy posture. The guard below enforces the text-only path.
    """
    if isinstance(frame, (bytes, bytearray, memoryview)):
        raise TypeError("narrate() takes a detection Frame, not raw image bytes")
    facts = summarize(frame, min_confidence)
    prompt = (
        "This is what your camera sees right now (positions are from your point "
        f"of view): {facts}\n\nSay what you see in one or two casual sentences, "
        "as G2. Don't list coordinates."
    )
    return ask(prompt).strip()
