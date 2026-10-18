"""How G2's body has been doing lately, for his mood: a low battery, a recent fall, how his last exploration went.

The traits in this package shape the Claude prompt and the behaviour knobs, but they heard nothing from the body. This is a small state file both the voice
service and an exploration session write to (they can be separate processes), and two readers use:

  * `hint()`        one plain sentence folded into the mood hint of each Claude turn (voice/loop.py), e.g. "Your battery is low ..."
  * `idle_mult()`   a multiplier on the idle sit / rest delays (behavior/driver.py, through DriverInputs.body_idle_mult): below 1 settles sooner
                    (sleepier on a low battery, quieter right after a fall)

    ~/.local/share/g2/body_state.json      (`G2_BODY_STATE` = a path, or `off`)

Every note expires on its own (a battery note after `BATTERY_S`, a fall after `FALL_S`, an exploration after `EXPLORE_S`), so a stale file never colours
him for long. Local only, never sent anywhere except as the one hint sentence inside the normal Claude call.
Every function swallows its own errors: mood bookkeeping must never disturb anything else.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("g2.body")

DEFAULT_PATH = "~/.local/share/g2/body_state.json"
BATTERY_S = 2 * 3600.0
FALL_S = 30 * 60.0
EXPLORE_S = 3 * 3600.0
_LOCK = threading.Lock()


def _path() -> Path | None:
    v = os.environ.get("G2_BODY_STATE", DEFAULT_PATH).strip()
    if v.lower() in ("", "off", "0", "false", "no"):
        return None
    return Path(os.path.expanduser(v))


def read(path: Path | None = None) -> dict:
    p = path or _path()
    if p is None:
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _update(**fields) -> None:
    p = _path()
    if p is None:
        return
    try:
        with _LOCK:
            st = read(p)
            st.update(fields)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(st))
            os.replace(tmp, p)
    except Exception:  # noqa: BLE001
        log.debug("body state write failed", exc_info=True)


def note_battery(level: str, now: float | None = None) -> None:
    """A low-battery alert fired (`level`: "low" or "critical")."""
    _update(battery=str(level).lower(), battery_t=time.time() if now is None else now)


def note_fall(now: float | None = None) -> None:
    _update(fall_t=time.time() if now is None else now)


def note_exploration(recap: dict, now: float | None = None) -> None:
    """The recap of a finished exploration (reflection/recap.py): how many things he saw, bumps, falls."""
    try:
        ev = recap.get("events") or {}
        _update(explore_t=time.time() if now is None else now, explore_seen=len(recap.get("seen") or {}), explore_hits=int(ev.get("wall.hit", 0)),
                explore_fell=bool(ev.get("fall")), explore_stops=int(recap.get("stops") or 0))
    except Exception:  # noqa: BLE001
        log.debug("body state: bad recap", exc_info=True)


def _fresh(st: dict, key: str, span: float, now: float) -> bool:
    t = st.get(key)
    return isinstance(t, (int, float)) and 0 <= now - t <= span


def hint(now: float | None = None, state: dict | None = None) -> str:
    """One or two short sentences for the system prompt, or "" when nothing about the body is worth mentioning."""
    now = time.time() if now is None else now
    st = read() if state is None else state
    out = []
    if st.get("battery") and _fresh(st, "battery_t", BATTERY_S, now):
        out.append("Your battery is critically low: you feel drained, keep replies very short and mention needing a charge."
                   if st["battery"] == "critical" else "Your battery is low: you feel a bit tired and keep replies short.")
    if _fresh(st, "fall_t", FALL_S, now):
        out.append("You fell over a little while ago and feel shaken; you are being careful.")
    elif _fresh(st, "explore_t", EXPLORE_S, now):
        if st.get("explore_fell") or st.get("explore_hits", 0) >= 3:
            out.append("Your last exploration was bumpy; you are a bit more careful now.")
        elif st.get("explore_seen", 0) >= 2 or st.get("explore_stops", 0) >= 3:
            out.append("Your last exploration went well and you feel curious about what you found.")
    return " ".join(out)


def idle_mult(now: float | None = None, state: dict | None = None) -> float:
    """Multiplier on the idle sit / rest delays: 0.6 on a critical battery, 0.75 on a low one or right after a fall, else 1."""
    now = time.time() if now is None else now
    st = read() if state is None else state
    m = 1.0
    if st.get("battery") and _fresh(st, "battery_t", BATTERY_S, now):
        m = min(m, 0.6 if st["battery"] == "critical" else 0.75)
    if _fresh(st, "fall_t", FALL_S, now):
        m = min(m, 0.75)
    return m


class CachedBody:
    """`idle_mult()` re-read at most every `every_s` (the behaviour runtime asks at 8 Hz)."""

    def __init__(self, every_s: float = 10.0, clock=time.monotonic):
        self._every, self._clock = every_s, clock
        self._at, self._mult = -1e9, 1.0

    def idle_mult(self) -> float:
        now = self._clock()
        if now - self._at >= self._every:
            self._at = now
            try:
                self._mult = idle_mult()
            except Exception:  # noqa: BLE001
                self._mult = 1.0
        return self._mult
