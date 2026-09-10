"""Bridge `BehaviorDriver` ticks into the diagnostics event stream.

`BehaviorDriver` stays pure (no `diag` import, unit-testable) and emits
`Effect(DIAG, (name, detail))` markers on every transition. The loop that runs
the driver calls `emit_tick(tick)` each step so a session's `events.jsonl` reads
back as a behaviour timeline:

    mode.transition   idle->explore   because "45s quiet >= idle_secs_before_explore(45)"
    posture.transition sit->resting   because "160s sat >= 90s"
    cliff.reflex      stop            because "edge at 0.18 m"

See docs/hardware/diagnostics.md "Decision events".
"""
from __future__ import annotations

from ..diag import diag
from .driver import DriverTick, EffectKind

# DIAG marker name -> (level, diag event name). Anything not listed is emitted
# at INFO under its own name.
_MAP = {
    "mode": ("INFO", "mode.transition"),
    "posture": ("INFO", "posture.transition"),
    "enroll": ("INFO", "enroll.transition"),
    "enroll.start": ("INFO", "enroll.start"),
    "enroll.complete": ("INFO", "enroll.complete"),
    "enroll.abort": ("WARN", "enroll.abort"),
    "cliff.reflex": ("WARN", "cliff.reflex"),
}


def emit_tick(tick: DriverTick, *, subsystem: str = "behavior") -> int:
    """Emit a diag event for each DIAG effect in `tick`. Returns the count."""
    n = 0
    for e in tick.effects:
        if e.kind is not EffectKind.DIAG:
            continue
        if isinstance(e.payload, (tuple, list)) and len(e.payload) == 2:
            name, detail = e.payload
        else:
            name, detail = str(e.payload), ""
        level, ev = _MAP.get(name, ("INFO", str(name)))
        diag.event(subsystem, level, ev, detail=detail, because=e.reason,
                   mode=tick.mode.value, posture=tick.posture.value,
                   enroll=tick.enroll_state.value)
        n += 1
    return n
