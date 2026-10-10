"""Power-saving sleep for the voice service (user, 2026-10-10): after G2 has rested (`d`) for `after_s` with no activity, he sighs and the Pi
saves power; the wake word (or any command) wakes him with a yawn.

What sleeping changes: Wi-Fi power-save on (the Pi's battery; +0.1-0.3 s per API call), the 5 Hz IMU print off (the stand guard does not need it while
he lies down; a little of the pack). The posture stays in rest (no curl-up), so waking needs no extra stand-up. The CPU governor stays `ondemand`:
`powersave` would starve the wake-word listener. `G2_SLEEP_AFTER_S` (default 300; 0 = off) sets the delay.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("g2.sleep")


class SleepWatch:
    def __init__(self, *, is_resting, is_busy=lambda: False, after_s: float = 300.0, on_sleep=(), on_wake=(),
                 clock=time.monotonic, sleep=time.sleep, poll_s: float = 5.0):
        self._is_resting, self._is_busy = is_resting, is_busy
        self._after_s = after_s
        self._on_sleep, self._on_wake = list(on_sleep), list(on_wake)
        self._clock, self._sleep, self._poll_s = clock, sleep, poll_s
        self._last = clock()
        self.asleep = False
        self._lock = threading.Lock()
        self._stop = threading.Event()

    @staticmethod
    def _run_all(fns, what: str) -> None:
        for fn in fns:
            try:
                fn()
            except Exception:  # noqa: BLE001 -- going to sleep or waking must never take the voice service down
                log.warning("%s step failed", what, exc_info=True)

    def note_activity(self, why: str = "activity") -> None:
        """Any command or exchange: restart the rest timer, and wake if asleep."""
        self._last = self._clock()
        self.wake(why)

    def wake(self, why: str = "wake word") -> bool:
        with self._lock:
            if not self.asleep:
                self._last = self._clock()
                return False
            self.asleep = False
            self._last = self._clock()
        log.info("waking (%s)", why)
        self._run_all(self._on_wake, "wake")
        return True

    def tick(self) -> bool:
        """One check; True if G2 went to sleep on this tick."""
        if self._after_s <= 0 or self.asleep:
            return False
        now = self._clock()
        if self._is_busy() or not self._is_resting():
            self._last = now
            return False
        if now - self._last < self._after_s:
            return False
        with self._lock:
            if self.asleep:
                return False
            self.asleep = True
        log.info("going to sleep after %.0f s at rest", now - self._last)
        self._run_all(self._on_sleep, "sleep")
        return True

    def start(self) -> "SleepWatch":
        def _run():
            while not self._stop.is_set():
                self.tick()
                self._sleep(self._poll_s)
        threading.Thread(target=_run, name="sleep-watch", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()


class WakeHook:
    """Wraps the wake-word detector: after the wake word, wake G2 (the yawn plays before the listening beep)."""

    def __init__(self, inner, watch: SleepWatch):
        self._inner, self._watch = inner, watch

    def wait(self, *a, **kw):
        r = self._inner.wait(*a, **kw)
        self._watch.note_activity("wake word")
        return r

    def __getattr__(self, name):
        return getattr(self._inner, name)
