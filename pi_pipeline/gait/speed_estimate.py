"""Forward-speed estimate from the IMU, for CarpetDetector (`gait/carpet.py`).

CarpetDetector needs "measured forward speed" each control tick to compare
against the commanded speed. Bittle has no wheel encoder / optical flow / GPS --
only the 6-axis IMU. This turns body-frame forward acceleration into a usable
speed estimate with a **ZUPT** (zero-velocity update) tied to the gait phase:

  over one full gait cycle of *steady* walking, body velocity is periodic, so
  the integral of forward acceleration over a cycle is ~0. Any nonzero result is
  accelerometer bias (offset + a gravity component from body pitch). Estimate
  that bias once per cycle and subtract it; integrate the bias-corrected accel
  with a short leak so residual error stays bounded.

The output is a noisy estimate of *mean* forward speed -- which is exactly what
CarpetDetector wants (it windows efficiency over ~2 s anyway).

HARDWARE-GATED on two counts, both marked below:
  1. the accel source -- `run_gait.parse_imu_line` currently returns orientation
     + gyro only; body-X accel needs plumbing once the real IMU stream format is
     confirmed (`--imu-format 6axis` carries ax/ay/az).
  2. the constants (`leak_hz`, `bias_lerp`, `min_cycle_s`) want bench tuning.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeedEstimatorConfig:
    leak_hz: float = 0.7          # leaky-integrator pull toward 0 (time const ~1.4 s)
    bias_lerp: float = 0.30       # how fast the per-cycle bias estimate adapts
    min_cycle_s: float = 0.25     # ignore absurdly short "cycles" (phase glitches)
    max_speed: float = 0.5        # clamp the estimate to something physical (m/s)


class ZuptSpeedEstimator:
    """`update(accel_fwd, phase, dt)` -> forward-speed estimate (m/s).

    `accel_fwd` -- body-frame forward linear acceleration, m/s^2, gravity removed.
    `phase`     -- gait phase 0..1 (from `residual_policy.phase_frac()`); the
                   wrap from ~1 back to ~0 marks a cycle boundary / ZUPT point.
    Pass `accel_fwd=None` when the IMU stream carries no accel -> estimate holds
    at 0 (CarpetDetector then just sees 0 efficiency, i.e. inert until plumbed).
    """

    def __init__(self, cfg: SpeedEstimatorConfig | None = None):
        self.cfg = cfg or SpeedEstimatorConfig()
        self._v = 0.0             # leaky-integrated bias-corrected speed
        self._bias = 0.0          # estimated accel bias (m/s^2)
        self._cycle_dv = 0.0      # integral of raw accel over the current cycle
        self._cycle_t = 0.0       # elapsed time in the current cycle
        self._last_phase = 0.0
        self._inert = False

    @property
    def v_est(self) -> float:
        return self._v

    def reset(self) -> None:
        self.__init__(self.cfg)

    def update(self, accel_fwd, phase: float, dt: float) -> float:
        c = self.cfg
        if accel_fwd is None:
            self._inert = True
            self._v = 0.0
            return 0.0
        self._inert = False
        a = float(accel_fwd)

        # per-cycle bias estimate: on a phase wrap, the accumulated dv "should"
        # be ~0 for steady walking -> the rest is bias.
        self._cycle_dv += a * dt
        self._cycle_t += dt
        if phase < self._last_phase and self._cycle_t >= c.min_cycle_s:
            bias_now = self._cycle_dv / self._cycle_t
            self._bias += c.bias_lerp * (bias_now - self._bias)
            self._cycle_dv = 0.0
            self._cycle_t = 0.0
        self._last_phase = phase

        # leaky integration of the bias-corrected accel
        self._v += (a - self._bias) * dt
        self._v -= c.leak_hz * self._v * dt
        self._v = max(-c.max_speed, min(c.max_speed, self._v))
        return self._v
