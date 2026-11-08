"""Make room before a big model loads (user, 2026-11-08; the 2026-11-07 roam: Piper loaded while the embedder was in memory and free memory fell to 40 MB with 136 MB in swap).

The two big optional models on the Pi Zero 2 W are the speech engine (about 90 MB, 10 s to load) and the image embedder (about 130 MB, 7.5 s). Each registers here with how to release itself and how long it has been idle. Before one loads,
`make_room(need_mb, keep=name)` looks at the free memory (`MemAvailable`) and, if loading would leave less than `FLOOR_MB`, releases the other one -- but only if it has been idle for `min_idle_s`, so two models that are both in use
are never swapped in and out of each other (that would cost 7-10 s a time). Never raises; does nothing off Linux.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("g2.membudget")
FLOOR_MB = 70.0              # free memory to keep after the load (the memory log warns under 80)
_holders: dict = {}          # name -> (release() -> bool, idle_for(seconds) -> bool)
_lock = threading.Lock()


def register(name: str, release, idle_for) -> None:
    with _lock:
        _holders[name] = (release, idle_for)


def unregister(name: str) -> None:
    with _lock:
        _holders.pop(name, None)


def free_mb() -> float | None:
    """MemAvailable in MB, or None when it cannot be read."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def make_room(need_mb: float, keep: str, min_idle_s: float = 15.0, floor_mb: float | None = None, free=free_mb) -> list:
    """Release idle holders other than `keep` until `need_mb` fits above the floor. Returns the names released."""
    released: list = []
    try:
        floor = FLOOR_MB if floor_mb is None else floor_mb
        f = free()
        if f is None:
            return released
        with _lock:
            others = [(n, h) for n, h in _holders.items() if n != keep]
        for name, (release, idle_for) in others:
            if f - need_mb >= floor:
                break
            try:
                if idle_for(min_idle_s) and release():
                    released.append(name)
                    f = free() or f
            except Exception:  # noqa: BLE001
                log.exception("releasing %s", name)
        if released:
            log.info("made room for %s (%.0f MB needed, %.0f MB free): released %s", keep, need_mb, f, ", ".join(released))
    except Exception:  # noqa: BLE001
        log.exception("make_room")
    return released
