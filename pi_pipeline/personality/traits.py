"""Personality traits and the behaviour knobs they steer.

A trait is a small, self-contained bias on how G2 behaves. Each one can
contribute to three channels, all optional:

1. `prompt_fragment()`  -> a sentence or two appended to Claude's system prompt,
   so the trait shows up in how G2 *talks and decides* when Claude is in the loop.
2. `bias(params)`        -> mutates `BehaviorParams` in place, so the trait shows
   up in the *autonomous* behaviours (explore mode, idle fidgets, cue frequency).
3. `cues(event)`         -> expressive reactions (a head tilt, a chirp, an
   approach) for a named event.

Every trait has a `level` in [0, 1] -- how strongly it's expressed. A trait
should scale all three channels by its level so 0.2 reads as "a little" and 0.9
as "a lot". Levels are set per-deployment via `G2_TRAITS` (see `personality.py`).

Add a trait later: subclass `Trait`, implement whichever channels apply, and add
it to `REGISTRY`. Nothing else changes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BehaviorParams:
    """Knobs the autonomous behaviour layer reads. Defaults are the *neutral*
    personality -- a G2 with no traits. Traits nudge these via `Trait.bias`;
    `Personality.behavior_params()` clamps the result back to sane ranges."""

    # --- explore mode ---
    idle_secs_before_explore: float = 45.0   # quiet time before G2 wanders on its own
    explore_leg_secs: float = 5.0            # seconds walked in one heading before reassessing
    investigate_secs: float = 3.0            # dwell time when examining one thing
    novelty_pull: float = 0.35              # 0..1 bias toward unvisited headings / novel objects
    approach_novelty: bool = False          # walk up to a novel detection vs. just orient to it
    revisit_secs: float = 150.0             # how long until a seen thing counts as novel again
    wander_turn_bias: float = 0.30          # 0..1 how much it changes heading between legs

    # --- expression ---
    vocalize_prob: float = 0.20            # 0..1 chance of an unprompted cue on an event
    fidget_prob: float = 0.05             # 0..1 chance of a small idle movement per idle tick

    # --- caution (feeds Avoider / terrain thresholds later) ---
    caution: float = 0.50                # 0..1 how early to slow / stop near obstacles & edges

    _UNIT_FIELDS = ("novelty_pull", "wander_turn_bias", "vocalize_prob",
                    "fidget_prob", "caution")
    _MIN_SECS = {"idle_secs_before_explore": 5.0, "explore_leg_secs": 1.0,
                 "investigate_secs": 0.5, "revisit_secs": 10.0}

    def clamp(self) -> "BehaviorParams":
        for f in self._UNIT_FIELDS:
            setattr(self, f, max(0.0, min(1.0, getattr(self, f))))
        for f, lo in self._MIN_SECS.items():
            setattr(self, f, max(lo, getattr(self, f)))
        return self


class Trait:
    """Base trait. Subclasses set `name` and override the channels they use.
    All three channels are no-ops by default, so a trait only writes what it
    actually affects."""

    name: str = "trait"

    def __init__(self, level: float = 0.5):
        self.level = max(0.0, min(1.0, float(level)))

    # 1. how G2 talks / decides (Claude in the loop)
    def prompt_fragment(self) -> str | None:
        return None

    # 2. how G2 behaves autonomously
    def bias(self, params: BehaviorParams) -> None:
        return None

    # 3. expressive reactions -- `event` is a short name the behaviour layer emits
    #    ("novelty", "explore_start", "greet", "startled", ...). Return skill /
    #    cue tokens; the caller decides which it can actually play.
    def cues(self, event: str) -> list[str]:
        return []

    def __repr__(self) -> str:  # pragma: no cover
        return f"{type(self).__name__}(level={self.level:.2f})"


# name -> class. Extended as traits are added.
from .curiosity import Curiosity  # noqa: E402  (import after Trait is defined)

REGISTRY: dict[str, type[Trait]] = {
    Curiosity.name: Curiosity,
}
