"""Place memory (behaviour-ideas B11) -- stable spatial patterns, not a timeline.

While roaming (Tier 1), G2 sees labelled things at rough headings. `PlaceMemory`
accumulates those sightings and, once it has seen the *same label in the same
rough direction* enough times, emits a durable pattern note like

    "the dog is often over to the left"

Deliberately NOT "saw the dog at 3pm" -- no timestamps, no counts of when. The
notes are plain sentences the caller hands to `Memory.store.add_fact` (which
rejects anything with a date/clock/schedule anyway). Pure bookkeeping.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# 4 coarse directions -- enough for "where does the cat hang out", no more.
def _direction(bearing_rad: float) -> str:
    b = ((bearing_rad + math.pi) % (2 * math.pi)) - math.pi   # wrap to [-pi, pi]
    if abs(b) <= math.pi / 4:
        return "straight ahead"
    if abs(b) >= 3 * math.pi / 4:
        return "back the other way"
    return "to the right" if b > 0 else "to the left"


@dataclass
class PlaceMemoryConfig:
    min_sightings: int = 3        # same label + direction this many times -> a pattern
    decay_sightings_at: int = 12  # cap the count so an old pattern can shift


class PlaceMemory:
    def __init__(self, cfg: PlaceMemoryConfig | None = None):
        self.cfg = cfg or PlaceMemoryConfig()
        self._counts: dict[tuple[str, str], int] = {}
        self._emitted: set[tuple[str, str]] = set()
        self._pending: list[str] = []

    def observe(self, label: str, bearing_rad: float) -> None:
        label = (label or "").strip().lower()
        if not label:
            return
        key = (label, _direction(bearing_rad))
        n = min(self._counts.get(key, 0) + 1, self.cfg.decay_sightings_at)
        self._counts[key] = n
        if n >= self.cfg.min_sightings and key not in self._emitted:
            self._emitted.add(key)
            lab, direction = key
            self._pending.append(f"The {lab} is often {direction} from where I usually sit.")

    def pending_notes(self) -> list[str]:
        """New pattern sentences since the last call (each emitted once)."""
        out, self._pending = self._pending, []
        return out

    def reset(self) -> None:
        self._counts.clear()
        self._emitted.clear()
        self._pending.clear()
