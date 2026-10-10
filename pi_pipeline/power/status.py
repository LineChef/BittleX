"""What G2 says when asked about his power (user, 2026-10-10: "what is your power level", "how much battery do you have left"): percent, never volts.

The G2 pack is read as a voltage and converted to a percent (`battery.pack_percent`); the Pi's battery cannot be read, so it is estimated from the time since boot against the measured
full-charge runtime (`runtime_tracker`). A reading taken while he walks sags, so the pack is only read when he is not walking."""
from __future__ import annotations

from .battery import pack_percent
from .runtime_tracker import MEASURED


def pack_phrase(volts: float | None) -> str:
    if volts is None:
        return "I can't read my battery while I'm walking."
    return f"My battery is at about {pack_percent(volts)} percent."


def pi_phrase(tracker) -> str | None:
    """The Pi's estimated charge, or None when there is no measured runtime to compare with."""
    state, _ = tracker.battery_state()
    if state == "paused":
        return "You told me I'm plugged in, so I'm not counting the Pi's battery."
    full = tracker.mean_runtime_s(sources=MEASURED)
    elapsed = tracker.armed_elapsed_s(from_boot=True)
    if not full or elapsed is None:
        return None
    left = max(0.0, full - elapsed)
    pct = int(round(100.0 * left / full))
    mins = int(left // 60)
    when = f"{mins // 60} hours {mins % 60} minutes" if mins >= 60 else f"{mins} minutes"
    return f"The Pi has about {pct} percent left, roughly {when}."


def battery_report(volts: float | None, tracker) -> str:
    parts = [pack_phrase(volts)]
    try:
        p = pi_phrase(tracker)
    except Exception:  # noqa: BLE001 -- a bad record must not stop the answer
        p = None
    if p:
        parts.append(p)
    return " ".join(parts)
