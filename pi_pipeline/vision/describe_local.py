"""Say what the on-camera detector sees, in a sentence. Free: no picture, no API call.

The detector only knows a few classes (people the household has enrolled, a dog, a cat), so this is a list of those, not a description of the
room. `describe(frame)` takes the detections of one frame (`vision.feed.Detection`)."""
from __future__ import annotations

_NUM = {1: "a", 2: "two", 3: "three", 4: "four"}


def _where(c: float) -> str:
    return "on my left" if c < 0.40 else "on my right" if c > 0.60 else "straight ahead"


def describe(frame, *, min_conf: float = 0.4) -> str:
    seen = [d for d in (frame or []) if d.confidence >= min_conf]
    if not seen:
        return "I don't see anything I recognise right now."
    seen.sort(key=lambda d: -d.area)
    parts = []
    for d in seen[:4]:
        size = " close up" if d.area >= 0.16 else " in the distance" if d.area < 0.03 else ""
        parts.append(f"a {d.label} {_where(d.center_x)}{size}")
    if len(seen) > 4:
        parts.append(f"and {len(seen) - 4} more")
    if len(parts) == 1:
        return f"I see {parts[0]}."
    return "I see " + ", ".join(parts[:-1]) + (" and " if not parts[-1].startswith("and ") else " ") + parts[-1] + "."
