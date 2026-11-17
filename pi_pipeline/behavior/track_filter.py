"""A small tracking filter for a target's bearing (2026-11-17, owner-approved after the first per-picture logs of the active look).

The camera's pictures arrive about four a second and the finder sees a pale ball in only a few of them, so a point estimate from the last picture alone loses a rolling ball. An alpha-beta filter keeps
an estimate of where the target is (`b`, degrees in G2's own frame, + = right) and how fast it moves (`v`, degrees per second), from the sightings it has accepted:

  * `update(t, z)` takes one sighting and corrects the estimate (a fixed gain on the residual, so a late or noisy sighting moves it a little, not all the way);
  * `predict(t)` says where the target should be at `t`: the claw uses it to COAST through pictures with no sighting and to LEAD a moving target;
  * `residual(t, z)` says how far a sighting is from the prediction: a sighting far from it is a different thing (the active look holds it until a second one agrees).

Pure arithmetic, no I/O, no time source of its own: every call is given the picture's capture time.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BearingFilter:
    alpha: float = 0.6                 # how much of the residual corrects the position
    beta: float = 0.3                  # how much of it corrects the speed
    max_speed: float = 200.0           # deg/s: a faster estimate is noise
    b: float | None = None             # the estimated bearing at `t`
    v: float = 0.0                     # the estimated speed, deg/s
    t: float | None = None             # when the estimate was last corrected (the capture time of the last accepted sighting)
    n: int = 0                         # sightings accepted since the last reset

    def reset(self) -> None:
        self.b, self.v, self.t, self.n = None, 0.0, None, 0

    def predict(self, t: float) -> float | None:
        """The bearing expected at `t` (the last estimate carried along at the estimated speed), or None before the first sighting."""
        if self.b is None or self.t is None:
            return None
        return self.b + self.v * (t - self.t)

    def residual(self, t: float, z: float) -> float | None:
        p = self.predict(t)
        return None if p is None else z - p

    def update(self, t: float, z: float) -> float:
        """Take one sighting at capture time `t` with bearing `z`; returns the corrected bearing."""
        if self.b is None or self.t is None:
            self.b, self.v, self.t, self.n = float(z), 0.0, float(t), 1
            return self.b
        dt = t - self.t
        if dt <= 0:                                                    # an old or repeated picture: it does not move the estimate
            return self.b
        pred = self.b + self.v * dt
        r = z - pred
        self.b = pred + self.alpha * r
        self.v = max(-self.max_speed, min(self.max_speed, self.v + self.beta * r / dt))
        self.t = float(t)
        self.n += 1
        return self.b

    def age(self, t: float) -> float | None:
        """Seconds since the last accepted sighting, or None before the first."""
        return None if self.t is None else t - self.t
