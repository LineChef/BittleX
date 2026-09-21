"""`SensorHub` -- the `sensors()` callable `BehaviorRuntime` wants.

Turns the raw robot inputs into the small dict of continuous state the
behaviour driver reads each tick:

  imu_level     -- body roughly upright (|roll|, |pitch| under a threshold)
  imu_stable    -- not being jostled (gyro magnitude low)
  held          -- picked up: off-level and moving for a sustained stretch
  person_present-- a person/face label in the latest detection frame

The IMU thresholds are FIRST-CUT and HARDWARE-GATED -- tune once the real DMP
stream is in front of us (`run_gait.py --probe-imu` shows the format).
`parse_imu_line` is imported from `gait/imu_parse.py`, shared with the gait
loop -- until 2026-09-20 this module had its own separate, unfixed copy that
had quietly drifted out of sync (see that module's docstring for what was
wrong and how it fails: NOT loudly -- an unparseable line just falls through
to `_ingest_imu`'s "no data -> assume level and stable" default below,
forever, since `_last_imu_at` never advances either).
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from ..gait.imu_parse import parse_imu_line

log = logging.getLogger("g2.app.sensors")


@dataclass
class SensorConfig:
    level_deg: float = 25.0          # |roll| or |pitch| under this -> "level"   # HARDWARE
    gyro_stable_rps: float = 1.2     # gyro magnitude under this -> "stable"     # HARDWARE
    held_after_s: float = 0.6        # off-level + moving this long -> "held"    # HARDWARE
    imu_format: str = "auto"
    person_labels: tuple = ("person", "face")  # detection labels that count as a person
    person_min_conf: float = 0.35
    stale_after_s: float = 1.5       # no IMU frame for this long -> assume level/stable


class SensorHub:
    def __init__(self, link=None, feed_source=None, cfg: SensorConfig | None = None,
                 *, clock=time.monotonic):
        self._link = link
        self._feed_source = feed_source or (lambda: [])
        self.cfg = cfg or SensorConfig()
        self._clock = clock
        self._last_imu_at = 0.0
        self._level = True
        self._stable = True
        self._unlevel_since: float | None = None

    # --- IMU --------------------------------------------------------------
    def _ingest_imu(self, now: float) -> None:
        """Drain whatever IMU frames are waiting; keep the most recent."""
        if self._link is None:
            return
        latest = None
        for _ in range(8):                      # bounded drain per tick
            line = self._link.read_line()
            if not line:
                break
            p = parse_imu_line(line, self.cfg.imu_format)
            if p is not None:
                latest = p
        if latest is None:
            if now - self._last_imu_at > self.cfg.stale_after_s:
                self._level, self._stable = True, True   # no data -> don't block resting
                self._unlevel_since = None
            return
        roll, pitch, _yaw, gx, gy, gz = latest
        self._last_imu_at = now
        self._level = (abs(math.degrees(roll)) < self.cfg.level_deg
                       and abs(math.degrees(pitch)) < self.cfg.level_deg)
        gmag = math.sqrt(gx * gx + gy * gy + gz * gz)
        self._stable = gmag < self.cfg.gyro_stable_rps
        if not self._level and not self._stable:
            if self._unlevel_since is None:
                self._unlevel_since = now
        else:
            self._unlevel_since = None

    def _held(self, now: float) -> bool:
        return (self._unlevel_since is not None
                and now - self._unlevel_since >= self.cfg.held_after_s)

    # --- vision ---------------------------------------------------------
    def _person_present(self) -> bool:
        try:
            frame = self._feed_source() or []
        except Exception:  # noqa: BLE001
            return False
        want = self.cfg.person_labels
        return any(getattr(d, "label", "") in want
                   and getattr(d, "confidence", 0.0) >= self.cfg.person_min_conf
                   for d in frame)

    # --- the one call BehaviorRuntime makes ---------------------------------
    def sample(self) -> dict:
        now = self._clock()
        self._ingest_imu(now)
        return {
            "imu_level": self._level,
            "imu_stable": self._stable,
            "held": self._held(now),
            "person_present": self._person_present(),
        }

    __call__ = sample
