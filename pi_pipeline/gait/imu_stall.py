"""Stall suspect from the IMU heading jitter -- LOG ONLY (user, 2026-10-10: "build the logging only first").

Finding (hardware session 2026-10-10, hardwood, V6, 0.10 m/s, wall 8 in ahead): while G2 steps against a wall his body rocks front-left / front-right and the
firmware heading jumps back and forth. The mean absolute heading change per IMU update (the stream is 5 Hz) over 8 s was 10.2-12.9 deg in 3 stall runs and
1.4-1.6 deg in 3 free walks; the worst of 45 windows of older real walks was 5.9 deg (nothing above 6 deg). Roll spread did not separate them; pitch range overlapped.
Sample sizes are small (3 stalls, ~3 min of older walking, no sharp turns), so this only OBSERVES: it never changes what G2 does. Review the "imu.stall_suspect" events
and the false-alarm count after real walks before anything acts on it.

Pure logic: feed `update(t, yaw_rad, commanded_forward)` every control tick; it takes a new sample only when the yaw value changes (a new IMU frame). While not
commanded forward, in the first `settle_s` after the start, or with too few samples, it is silent. One event per episode: it re-arms once the mean falls under `clear_deg`.
"""
from __future__ import annotations

import math
from collections import deque

WINDOW_S = 8.0
MIN_SAMPLES = 20                 # about 4 s of 5 Hz frames
TRIGGER_DEG = 8.0                # between the worst normal window (5.9) and the weakest stall (10.2)
CLEAR_DEG = 5.0
SETTLE_S = 1.5                   # skip the stand-up transient, as the analysis did


class ImuStallDetector:
    def __init__(self, window_s: float = WINDOW_S, min_samples: int = MIN_SAMPLES, trigger_deg: float = TRIGGER_DEG,
                 clear_deg: float = CLEAR_DEG, settle_s: float = SETTLE_S):
        self.window_s, self.min_samples, self.trigger_deg, self.clear_deg, self.settle_s = window_s, min_samples, trigger_deg, clear_deg, settle_s
        self._samples: deque = deque()          # (t, yaw_deg), one per distinct IMU frame
        self._last_yaw: float | None = None
        self._t_start: float | None = None
        self._armed = True
        self.last_mean_deg = 0.0
        self.events = 0

    def reset(self) -> None:
        self._samples.clear()
        self._last_yaw = None

    def mean_jitter_deg(self) -> float | None:
        """Mean absolute heading change per IMU update over the window, or None with too few samples."""
        if len(self._samples) < self.min_samples:
            return None
        ys = [y for _, y in self._samples]
        d = [abs((b - a + 180.0) % 360.0 - 180.0) for a, b in zip(ys, ys[1:])]
        return sum(d) / len(d)

    def update(self, t: float, yaw_rad: float, commanded_forward: bool) -> dict | None:
        """Returns an event dict the first time the window mean passes the trigger (and again only after it fell under the clear level), else None."""
        if self._t_start is None:
            self._t_start = t
        if not commanded_forward or t - self._t_start < self.settle_s:
            self.reset()
            return None
        yaw = math.degrees(yaw_rad)
        if self._last_yaw is not None and yaw == self._last_yaw:
            return None                                          # the same IMU frame as the last tick
        self._last_yaw = yaw
        self._samples.append((t, yaw))
        while self._samples and t - self._samples[0][0] > self.window_s:
            self._samples.popleft()
        m = self.mean_jitter_deg()
        if m is None:
            return None
        self.last_mean_deg = m
        if self._armed and m > self.trigger_deg:
            self._armed = False
            self.events += 1
            return {"mean_jitter_deg": round(m, 1), "samples": len(self._samples), "window_s": self.window_s}
        if not self._armed and m < self.clear_deg:
            self._armed = True
        return None
