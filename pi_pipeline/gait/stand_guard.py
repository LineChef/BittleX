"""Keeps G2's firmware gyro balance from wobbling him while he stands.

Background (docs/hardware/petoi-firmware-reference.md, "Standing wobble"): the firmware's gyro-balance loop runs on an IMU that only
updates at 5 Hz, so it is barely stable; once disturbed (often by standing up from rest) it can lock into a roughly 2 Hz roll/pitch
oscillation that lasts a minute or more. With balance off (`gb`) G2 stands calm and a nudge dies out in seconds.

Two layers, both here:
  1. Balance off while idle: `gb` at start and re-sent every `reassert_s`, so the loop is not running when G2 is just standing. The
     actuator turns balance on (`gB`) only around a firmware gait and off again after it.
  2. A guard: `WobbleDetector` watches the 5 Hz IMU stream and, if the swing is large, rhythmic and sustained, `StandGuard` sends
     `gb` at once. This also catches stands started by the BiBoard's own voice module, which never pass through the Pi.

Both pause while a gait is running (the swing of walking is not a wobble).

When does balance come back on?
  * Around a firmware gait: the actuator sends `gB` just before a gait skill and `gb` just after it ends. That is the normal on-time.
  * If the idle policy is switched off (G2_BALANCE_OFF_IDLE=0, balance left to the firmware), a guard trip turns balance off and the
    guard then puts it back on ("probation") after `reenable_after_s` of quiet, with a doubling back-off: if the wobble returns within
    a minute of a re-enable, the next wait is twice as long (up to an hour). With the idle policy on, balance is simply off while he
    stands and there is nothing to re-enable."""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque

from .imu_parse import parse_imu_line

log = logging.getLogger("g2.stand_guard")


class WobbleDetector:
    """Feed it (time, roll, pitch) in degrees; True once a sustained, rhythmic swing is seen.

    A window of `window` samples is a wobble when, in roll or pitch, the swing (standard deviation after removing the mean) is at least
    `min_swing_deg` and the signal crosses its mean at least `min_crossings` times (a rhythm, not a single bump). It must stay that
    way for `sustain_s` seconds, so a nudge that rings down in a couple of seconds does not trip it. Defaults were tuned by replaying five
    real stand logs (2026-10-04): steady noise is about 0.1 degrees; the wobble swung 1-6 degrees at ~2 Hz. At these settings every log
    with a wobble trips within about 5 s of it starting and the balance-off log (one bump) never does. Sensitive on purpose: a false
    trip only sends `gb`, which the idle policy has on anyway."""

    def __init__(self, window: int = 20, min_swing_deg: float = 0.8, min_crossings: int = 4, sustain_s: float = 4.0,
                 dead_band_deg: float = 0.3):
        self.window, self.min_swing_deg, self.min_crossings = window, min_swing_deg, min_crossings
        self.sustain_s, self.dead_band_deg = sustain_s, dead_band_deg
        self._r: deque[float] = deque(maxlen=window)
        self._p: deque[float] = deque(maxlen=window)
        self._active_since: float | None = None

    def reset(self) -> None:
        self._r.clear(); self._p.clear(); self._active_since = None

    def _wobbling(self, v) -> bool:
        m = sum(v) / len(v)
        d = [x - m for x in v]
        std = math.sqrt(sum(x * x for x in d) / len(d))
        if std < self.min_swing_deg:
            return False
        crossings, last = 0, 0
        for x in d:
            if abs(x) < self.dead_band_deg:
                continue
            sign = 1 if x > 0 else -1
            if last and sign != last:
                crossings += 1
            last = sign
        return crossings >= self.min_crossings

    def update(self, t: float, roll_deg: float, pitch_deg: float) -> bool:
        self._r.append(roll_deg); self._p.append(pitch_deg)
        if len(self._r) < self.window:
            return False
        if self._wobbling(self._r) or self._wobbling(self._p):
            if self._active_since is None:
                self._active_since = t
            return t - self._active_since >= self.sustain_s
        self._active_since = None
        return False


class StandGuard:
    """Background thread that keeps firmware balance off while idle and trips the `WobbleDetector`. `link` needs `send`, `poll_imu`
    (a shared, locked link). `is_busy()` says a gait is running (everything pauses); `note_activity()` is called when any command
    is sent, opening a short quiet window (a stand-up or skill is expected to move him)."""

    def __init__(self, link, *, is_busy=lambda: False, detector: WobbleDetector | None = None, balance_off_idle: bool = True,
                 guard: bool = True, reassert_s: float = 60.0, quiet_after_activity_s: float = 8.0, on_trip=None,
                 reenable_after_s: float | None = None, max_reenable_s: float = 3600.0,
                 clock=time.monotonic, sleep=time.sleep, poll_s: float = 0.2):
        self._link, self._is_busy = link, is_busy
        self._det = detector or WobbleDetector()
        self._balance_off_idle, self._guard = balance_off_idle, guard
        self._reassert_s, self._quiet_s, self._on_trip = reassert_s, quiet_after_activity_s, on_trip
        self._clock, self._sleep, self._poll_s = clock, sleep, poll_s
        self._reenable_s, self._wait_s, self._max_reenable_s = reenable_after_s, reenable_after_s, max_reenable_s
        self._forced_off_at: float | None = None       # when a trip turned balance off (only tracked when probation is on)
        self._reenabled_at: float | None = None
        self._quiet_until = 0.0
        self._last_gb = -1e9
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.trips = 0

    def note_activity(self) -> None:
        self._quiet_until = self._clock() + self._quiet_s
        self._det.reset()

    def _gb(self, why: str) -> None:
        try:
            self._link.send("gb", read_reply=False, settle=0.0)
            self._last_gb = self._clock()
            log.info("firmware gyro balance off (%s)", why)
        except Exception:  # noqa: BLE001 -- the guard must never take the service down
            log.debug("sending gb failed", exc_info=True)

    def start(self) -> "StandGuard":
        if self._balance_off_idle:
            self._gb("idle policy")
        if self._guard:
            try:
                self._link.send("gP", read_reply=False, settle=0.0)       # the 5 Hz IMU print the detector reads
            except Exception:  # noqa: BLE001
                log.debug("starting the IMU print failed", exc_info=True)
        self._thread = threading.Thread(target=self._run, name="stand-guard", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._guard:
            try:
                self._link.send("gp", read_reply=False, settle=0.0)
            except Exception:  # noqa: BLE001
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._sleep(self._poll_s)

    def tick(self) -> bool:
        """One pass: drain the IMU lines, re-assert balance off, run the detector. True if the detector tripped."""
        now = self._clock()
        try:
            lines = self._link.poll_imu() if self._guard else []
        except Exception:  # noqa: BLE001
            lines = []
        if self._is_busy():
            self._quiet_until = now + self._quiet_s
            self._det.reset()
            return False
        if self._balance_off_idle and now - self._last_gb >= self._reassert_s:
            self._gb("periodic re-assert")
        if self._forced_off_at is not None and self._reenable_s and now - self._forced_off_at >= self._wait_s:
            try:                                                   # probation: put the firmware balance back
                self._link.send("gB", read_reply=False, settle=0.0)
                log.info("firmware gyro balance back on (probation after %.0f s of quiet)", self._wait_s)
            except Exception:  # noqa: BLE001
                log.debug("sending gB failed", exc_info=True)
            self._forced_off_at, self._reenabled_at = None, now
            self._det.reset()
            self.note_activity()
        if not self._guard or now < self._quiet_until:
            return False
        tripped = False
        for line in lines:
            r = parse_imu_line(line)
            if r is None:
                continue
            if self._det.update(now, math.degrees(r[0]), math.degrees(r[1])):
                tripped = True
        if tripped:
            self.trips += 1
            log.warning("standing wobble detected -- turning firmware gyro balance off")
            try:
                from ..diag import diag
                diag.event("gait", "WARN", "stand.wobble_guard", trips=self.trips)
            except Exception:  # noqa: BLE001
                pass
            self._gb("wobble guard")
            self._det.reset()
            if self._reenable_s:
                if self._reenabled_at is not None and now - self._reenabled_at < 60.0:
                    self._wait_s = min(self._wait_s * 2, self._max_reenable_s)   # it came straight back: wait longer next time
                self._forced_off_at, self._reenabled_at = now, None
            if self._on_trip:
                try:
                    self._on_trip()
                except Exception:  # noqa: BLE001
                    log.debug("on_trip handler raised", exc_info=True)
        return tripped
