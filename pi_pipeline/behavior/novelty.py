"""What G2 has seen recently -- so "curious" can mean "drawn to the *un*seen".

Pure bookkeeping, no I/O. Two things are tracked, each with a last-seen
timestamp (monotonic seconds, passed in by the caller):

  objects   -- detection labels ("mug", "shoe", "cat")
  headings  -- coarse compass bins, so explore mode can prefer directions it
               hasn't been lately

Both fade: after `revisit_secs` a thing is "novel" again, and staleness ramps
back to 1.0 so a long-unvisited heading pulls hardest.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class NoveltyConfig:
    revisit_secs: float = 150.0   # seen -> novel again after this quiet
    heading_bins: int = 8         # compass resolution for "directions explored"


class Novelty:
    def __init__(self, cfg: NoveltyConfig | None = None):
        self.cfg = cfg or NoveltyConfig()
        self._obj_seen: dict[str, float] = {}
        self._head_seen: dict[int, float] = {}

    # --- objects ---

    def see_object(self, label: str, now: float) -> None:
        if label:
            self._obj_seen[label] = now

    def is_novel_object(self, label: str, now: float) -> bool:
        last = self._obj_seen.get(label)
        return last is None or (now - last) >= self.cfg.revisit_secs

    # --- headings (radians, any range; wrapped to bins) ---

    def _bin(self, bearing: float) -> int:
        n = self.cfg.heading_bins
        return int(math.floor((bearing % (2 * math.pi)) / (2 * math.pi) * n)) % n

    def see_heading(self, bearing: float, now: float) -> None:
        self._head_seen[self._bin(bearing)] = now

    def heading_staleness(self, bearing: float, now: float) -> float:
        """0.0 = just visited, 1.0 = never visited or fully faded."""
        last = self._head_seen.get(self._bin(bearing))
        if last is None:
            return 1.0
        return max(0.0, min(1.0, (now - last) / self.cfg.revisit_secs))

    def stalest_heading(self, now: float, choices: int = 12) -> float:
        """Bearing (radians, -pi..pi) of the least-recently-visited direction,
        sampled over `choices` evenly-spaced headings."""
        best_b, best_s = 0.0, -1.0
        for k in range(choices):
            b = -math.pi + 2 * math.pi * k / choices
            s = self.heading_staleness(b, now)
            if s > best_s:
                best_b, best_s = b, s
        return best_b

    # --- housekeeping ---

    def forget_before(self, cutoff: float) -> None:
        """Drop entries older than `cutoff` so the dicts don't grow forever."""
        self._obj_seen = {k: v for k, v in self._obj_seen.items() if v >= cutoff}
        self._head_seen = {k: v for k, v in self._head_seen.items() if v >= cutoff}
