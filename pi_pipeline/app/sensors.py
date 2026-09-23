"""`SensorHub` -- the `sensors()` callable `BehaviorRuntime` wants.

Turns the raw robot inputs into the small dict of continuous state the
behaviour driver reads each tick:

  imu_level     -- body roughly upright (|roll|, |pitch| under a threshold)
  imu_stable    -- not being jostled (angular-rate magnitude low)
  held          -- picked up: off-level and moving for a sustained stretch
  person_present-- a person/face label in the latest detection frame

The IMU thresholds are FIRST-CUT and HARDWARE-GATED -- tune once the real DMP
stream is in front of us (`run_gait.py --probe-imu` shows the format).
IMU parsing and rate estimation come from `gait/imu_parse.py`'s `ImuFeed`,
shared with the gait loop -- until 2026-09-20 this module had its own
separate, unfixed parser copy that had quietly drifted out of sync (an
unparseable line fell through to the "no data -> assume level and stable"
default below, forever).

The firmware stream has no gyro, so angular rate is the finite difference of
consecutive 5 Hz frames. Until 2026-09-22 this read the parser's zero gyro
slot, so `imu_stable` was always True and `held` could never fire. Reads are
`link.poll_imu()` (non-blocking): the old blocking `read_line()` held the
shared link's lock for up to a second per tick with no data, delaying any
voice-loop send (including an emergency stop) behind it. `start_stream()`
sends `gP`; nothing else turns the stream on in app mode.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from ..gait.imu_parse import ImuFeed

log = logging.getLogger("g2.app.sensors")


@dataclass
class SensorConfig:
    level_deg: float = 25.0          # |roll| or |pitch| under this -> "level"   # HARDWARE
    gyro_stable_rps: float = 1.2     # angular-rate magnitude under this -> "stable" # HARDWARE
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
        self._feed = ImuFeed(self.cfg.imu_format)
        self._level = True
        self._stable = True
        self._unlevel_since: float | None = None

    # --- IMU --------------------------------------------------------------
    def start_stream(self) -> None:
        """Turn on the firmware's continuous IMU print (`gP`)."""
        if self._link is not None:
            self._link.send("gP", read_reply=False, settle=0.0)

    def stop_stream(self) -> None:
        """Turn it off (`gp` -- lowercase is print-off, not a toggle)."""
        if self._link is not None:
            self._link.send("gp", read_reply=False, settle=0.0)

    def _ingest_imu(self, now: float) -> None:
        """Take whatever IMU frames arrived since last tick; keep the latest."""
        if self._link is None:
            return
        if not self._feed.update(self._link.poll_imu(), now):
            if self._feed.age(now) > self.cfg.stale_after_s:
                self._level, self._stable = True, True   # no data -> don't block resting
                self._unlevel_since = None
            return
        roll, pitch, _yaw, gx, gy, gz = self._feed.frame
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
