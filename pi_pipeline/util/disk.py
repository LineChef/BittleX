"""Disk-space warning for the SD card: warn once when it passes a threshold, then remind every few hours."""
from __future__ import annotations

import logging
import shutil
import threading
import time

log = logging.getLogger("g2.disk")

DEFAULT_THRESHOLD_PCT = 85.0


def disk_status(path: str = "/") -> tuple[float, float]:
    """(percent used, free GB) for the filesystem holding `path`."""
    u = shutil.disk_usage(path)
    return 100.0 * u.used / u.total, u.free / 1e9


def warning_text(pct: float, free_gb: float, threshold: float) -> str | None:
    if pct < threshold:
        return None
    return (f"SD card {pct:.0f}% full ({free_gb:.1f} GB free, warning at {threshold:.0f}%) -- clear old "
            "logs and captures (~/g2_logs, ~/g2_runs, ~/g2_cap) or trim the journal: "
            "sudo journalctl --vacuum-size=20M")


class DiskWatch:
    """Checks the disk on a timer. `tick()` returns a warning the first time usage crosses the threshold and again
    every `repeat_s` while it stays above; dropping back below re-arms it."""

    def __init__(self, threshold_pct: float = DEFAULT_THRESHOLD_PCT, *, path: str = "/",
                 repeat_s: float = 6 * 3600.0, status=disk_status, clock=time.monotonic):
        self.threshold, self.path, self.repeat_s = threshold_pct, path, repeat_s
        self._status, self._clock = status, clock
        self._last_warned: float | None = None

    def tick(self) -> str | None:
        pct, free = self._status(self.path)
        msg = warning_text(pct, free, self.threshold)
        if msg is None:
            self._last_warned = None
            return None
        now = self._clock()
        if self._last_warned is not None and now - self._last_warned < self.repeat_s:
            return None
        self._last_warned = now
        return msg


def _emit(msg: str) -> None:
    log.warning(msg)
    try:
        from ..diag import diag
        diag.event("disk", "WARN", "disk.full", detail=msg)
    except Exception:  # noqa: BLE001 -- the warning is already in the log
        pass


def start_disk_watch(threshold_pct: float = DEFAULT_THRESHOLD_PCT, *, interval_s: float = 1800.0,
                     path: str = "/") -> DiskWatch:
    """Check now, then every `interval_s` on a daemon thread. Warns via the log and the diagnostics event log."""
    watch = DiskWatch(threshold_pct, path=path)

    def _run() -> None:
        while True:
            try:
                msg = watch.tick()
                if msg:
                    _emit(msg)
            except Exception:  # noqa: BLE001 -- a failed check must never matter to the robot
                log.debug("disk check failed", exc_info=True)
            time.sleep(interval_s)

    threading.Thread(target=_run, name="disk-watch", daemon=True).start()
    return watch
