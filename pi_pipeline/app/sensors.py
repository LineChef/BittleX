"""`SensorHub` -- the `sensors()` callable `BehaviorRuntime` wants.

Turns the raw robot inputs into the small dict of continuous state the
behaviour driver reads each tick:

  imu_level     -- body roughly upright (|roll|, |pitch| under a threshold)
  imu_stable    -- not being jostled (gyro magnitude low)
  held          -- picked up: off-level and moving for a sustained stretch
  person_present-- a person/face label in the latest detection frame

The IMU thresholds are FIRST-CUT and HARDWARE-GATED -- tune once the real DMP
stream is in front of us (`run_gait.py --probe-imu` shows the format;
`parse_imu_line` is shared with the gait loop).
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

log = logging.getLogger("g2.app.sensors")


def parse_imu_line(line: str, fmt: str = "auto", deg_in: bool = True):
    """(roll, pitch, yaw [rad], gx, gy, gz [rad/s]) or None if not an IMU frame.

    Kept in sync with `gait/run_gait.py`'s copy (that module is script-style and
    not cleanly importable). Handles the common OpenCat `print6Axis` shapes:
      "ypr <yaw> <pitch> <roll>" | "<y> <p> <r> <gx> <gy> <gz>" | 3-num r/p/y.
    """
    s = line.strip().replace(",", " ")
    if not s:
        return None
    toks = s.split()
    try:
        if toks and toks[0].lower() in ("ypr", "ang"):
            yaw, pitch, roll = (float(x) for x in toks[1:4])
            g = [0.0, 0.0, 0.0]
        else:
            nums = [float(x) for x in toks]
            if len(nums) == 3:
                yaw, pitch, roll = nums if fmt == "ypr" else (nums[2], nums[1], nums[0])
                g = [0.0, 0.0, 0.0]
            elif len(nums) >= 6:
                if fmt == "6axis":                 # ax ay az gx gy gz -> no orientation
                    return None
                yaw, pitch, roll = nums[0:3]
                g = nums[3:6]
            else:
                return None
    except ValueError:
        return None
    k = math.pi / 180.0 if deg_in else 1.0
    return (roll * k, pitch * k, yaw * k, g[0] * k, g[1] * k, g[2] * k)


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
