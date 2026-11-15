"""Where the ball is when the camera cannot say (2026-11-15 goal runs).

Inside about 3 in the ball is too close for the claw camera to give a usable bearing: a 5 degree turn moved the reading from +10 to -22 degrees, and a ball touching the edge of the frame reads a
clipped bearing of about +-39 degrees. The chase then turned on noise ("could not line up", "overshot") and sent him back to start again.

`BallTrack` keeps the ball's place in G2's own frame (inches, x to his right, y ahead) from the last GOOD picture (ball at 3 in or farther and not at the frame edge) and moves it with what he does
afterwards: a turn of `deg` (the gyro's count) rotates it, a walk of `inches` brings it nearer, a back-up takes it farther. A blind picture (too close, or at the edge) is then answered with the tracked
bearing instead of the camera's, so a line-up inside 3 in turns on the last steady picture plus the yaw counted since, not on parallax. Pure logic: no I/O, a clock in.
"""
from __future__ import annotations

import dataclasses
import math
import time

BLIND_IN = 3.0          # nearer than this the camera bearing is not used
MAX_AGE_S = 20.0        # a track older than this is not used (the ball may have moved)
MAX_DRIFT_IN = 8.0      # walked or backed up this far since the last good picture: the estimate is too uncertain to use


class BallTrack:
    def __init__(self, clock=time.monotonic, blind_in: float = BLIND_IN):
        self._clock = clock
        self.blind_in = blind_in
        self.x: float | None = None
        self.y: float | None = None
        self._t: float | None = None
        self._moved_in = 0.0
        self.used_estimate = False                   # the last `see` answered with the track, not the camera

    def clear(self) -> None:
        self.x = self.y = self._t = None
        self._moved_in = 0.0

    @property
    def valid(self) -> bool:
        return self.x is not None and self._t is not None and self._clock() - self._t <= MAX_AGE_S and self._moved_in <= MAX_DRIFT_IN

    def bearing(self) -> float | None:
        return math.degrees(math.atan2(self.x, self.y)) if self.valid else None

    def see(self, ball):
        """A new picture's reading in, the reading to decide on out: the camera's own when it is good (and the track is refreshed from it), the tracked bearing when it is blind and there is a valid track."""
        self.used_estimate = False
        edge = bool(getattr(ball, "touches_edge", False))
        if ball.distance_in >= self.blind_in and not edge:
            b = math.radians(ball.bearing_deg)
            self.x, self.y = ball.distance_in * math.sin(b), ball.distance_in * math.cos(b)
            self._t, self._moved_in = self._clock(), 0.0
            return ball
        est = self.bearing()
        if est is None:
            return ball                              # nothing better to go on: the camera's reading
        self.used_estimate = True
        return dataclasses.replace(ball, bearing_deg=est)

    def turned(self, deg: float) -> None:
        """He turned `deg` degrees (+ = right): the ball is that much farther to his left."""
        if self.x is None:
            return
        r = math.hypot(self.x, self.y)
        phi = math.atan2(self.x, self.y) - math.radians(deg)
        self.x, self.y = r * math.sin(phi), r * math.cos(phi)

    def walked(self, inches: float) -> None:
        """He walked `inches` forward (negative: backed up): the ball is that much nearer (farther)."""
        if self.x is None:
            return
        self.y -= inches
        self._moved_in += abs(inches)
        if self.y < 0.5:
            self.y = 0.5                             # it cannot be behind the claw: at the claw
