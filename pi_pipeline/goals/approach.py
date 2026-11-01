"""What a goal plugs in (goals plan, "Adding a goal later"). The framework knows nothing about balls: an approach brings its knobs, a way to run one attempt, a scorer and a
diagnosis table, and everything else (the session loop, the judge, the journal, the notes and the report) is shared.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from .spec import Knob


@dataclass
class AttemptContext:
    """What an attempt may use. `say` prints / logs; `announce` speaks a short cue (None: silent); `stop()` is the user's stop."""
    stop: Callable[[], bool] = lambda: False
    say: Callable[[str], None] = print
    announce: Callable[[str], None] | None = None


@dataclass
class AttemptResult:
    ended: str                        # how it ended, in the approach's words ("punted", "time", "fell", "battery", "stopped")
    seconds: float
    trace: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class Outcome:
    code: str                         # the diagnosis table's key ("hit", "missed", "never_found", ...); "aborted" = not counted
    score: float | None               # 0 to 1; None = not counted (stopped by the user, battery)
    success: bool
    text: str                         # first person, plain ("I punched from 3.2 in and the ball went 14 in")
    numbers: dict = field(default_factory=dict)

    @property
    def counted(self) -> bool:
        return self.score is not None

    @property
    def fell(self) -> bool:
        return self.code == "fell"


class Approach(Protocol):
    name: str
    diagnosis: dict                   # outcome code -> [(knob name, +1 | -1 | "other"), ...] in order of preference

    def knobs(self) -> list[Knob]: ...
    def base_settings(self) -> dict: ...                      # the user's own settings (their file) and the defaults: the start of a goal's first session
    def conditions(self) -> dict: ...                         # extra conditions results are counted under (the shared ones are the attachment and the floor)
    def run_attempt(self, settings: dict, ctx: AttemptContext) -> AttemptResult: ...
    def score(self, result: AttemptResult, settings: dict) -> Outcome: ...
    def battery_ok(self, min_pct: int) -> tuple[bool, str]: ...
    def open(self) -> None: ...                               # hardware up (link, camera) for a session
    def close(self) -> None: ...                              # hardware down; G2 rests


REGISTRY: dict[str, Callable[..., Approach]] = {}


def register(name: str):
    def deco(cls):
        REGISTRY[name] = cls
        return cls
    return deco


def make(name: str, **kw) -> Approach:
    if name not in REGISTRY:
        from . import ball_punt  # noqa: F401  -- registers itself
    if name not in REGISTRY:
        raise KeyError(f"no approach named {name!r} (known: {', '.join(sorted(REGISTRY))})")
    return REGISTRY[name](**kw)
