"""Shared IMU-line parser for anything that reads the BiBoard's serial stream.

Used by both `gait/run_gait.py` (the real-time control loop) and
`app/sensors.py` (SensorHub's imu_level/imu_stable/held checks) -- pulled
out into its own module 2026-09-20 after the two copies drifted out of
sync (sensors.py's copy was still the old, wrong-format guess after
run_gait.py's was fixed, and its own failure mode was silent: an
unparseable line just falls through to the "no data -> assume level and
stable" default forever, which is worse than a loud failure). Import this
one everywhere instead of copy-pasting it again.
"""
from __future__ import annotations

import math

# The firmware stream's line prefixes (MPU6050 / ICM42670). link/serial_link.py
# keeps an identical IMU_PREFIXES for its reply/IMU demux -- a test asserts
# they match.
IMU_PREFIXES = ("MCU:", "ICM:")


def parse_imu_line(line, fmt="auto", deg_in=True):
    """Return (roll, pitch, yaw [rad], gx, gy, gz [rad/s]) or None if this line
    isn't an IMU frame.

    CONFIRMED against `PetoiCamp/OpenCatEsp32` src (`src/imu.h` `print6Axis()`,
    called from `readEnvironment()` on every loop() while `printGyroQ` is on,
    i.e. after sending `gP` -- see `T_GYRO`/`C_PRINT` in `src/OpenCat.h`)
    2026-09-20 -- the real, currently-shipping line shape is:

        MCU:<ax><ay><az><yaw><pitch><roll>      (MPU6050 chip)
        ICM:<ax><ay><az><yaw><pitch><roll>      (ICM42670 chip)

    fixed-width (`%6.2f` for accel in g, `%7.1f` for angles in degrees),
    no explicit delimiter -- BiBoard V1 compiles support for BOTH chips and
    picks whichever is physically present at runtime, so either prefix is
    valid. `PRINT_ACCELERATION` is unconditionally defined in current
    firmware, so the accel triplet is always present. yaw is printed
    negated (`-mpu.ypr[0]` / `-icm.ypr[0]`) -- sign re-negated back to raw
    here; NOT yet empirically confirmed against a real board (do one
    physical rotation check at bring-up step 13a and flip if backwards).

    IMPORTANT GAP (found during this same research pass, not yet resolved):
    this line carries ACCELERATION, not GYRO/angular-velocity -- the
    firmware's raw-gyro print path is dead code (commented out in
    `imu.h`), so no true angular-rate is available over serial at all under
    stock firmware. `ResidualGaitPolicy` needs real roll/pitch angular
    velocity (see `gait/residual_policy.py`) -- this stream cannot supply
    it. Deliberately NOT smuggled into the gyro return slot below (that
    would silently feed the wrong physical quantity, in the wrong units,
    to the policy as if it were angular rate -- worse than returning
    nothing) -- the gyro slot returns zero here, same convention already
    used elsewhere in this function when no true gyro is available. Needs
    a real fix before this stream is trustworthy for the policy loop: e.g.
    finite-differencing consecutive `ypr` samples in the control loop (the
    policy's own training obs already relies on a finite-diff angular-accel
    channel, so precedent exists), or revisiting the no-firmware-fork
    stance for just a gyro-print re-enable. Flagged, not fixed here --
    needs a decision, not a guess.

    ALSO NOTE (rate, not format): `print6Axis()` self-throttles to at most
    one line every `PRINT6AXIS_MIN_INTERVAL` = 200ms -- a firmware-side 5Hz
    ceiling on fresh orientation data, independent of this parser. A caller
    ticking faster than that (e.g. run_gait's 80Hz control loop) will see
    the same parsed frame repeat across several ticks. See
    docs/hardware/petoi-firmware-reference.md and the priority callout at
    the top of docs/project-plan.md.

    Older/fallback shapes kept for robustness in case a different firmware
    build is ever in play:
      - "ypr <yaw> <pitch> <roll>"                (DMP, degrees)
      - "<ax> <ay> <az> <gx> <gy> <gz>"           (raw 6-axis, true gyro)
      - "<yaw> <pitch> <roll> <gx> <gy> <gz>"     (ypr + gyro, if enabled)
    """
    s = line.strip().replace(",", " ")
    if not s:
        return None
    k = math.pi / 180.0 if deg_in else 1.0
    for prefix in IMU_PREFIXES:
        if s.startswith(prefix):
            try:
                nums = [float(x) for x in s[len(prefix):].split()]
            except ValueError:
                return None
            if len(nums) != 6:
                return None
            _ax, _ay, _az, neg_yaw, pitch, roll = nums  # accel not used -- see docstring gap
            yaw = -neg_yaw
            return (roll * k, pitch * k, yaw * k, 0.0, 0.0, 0.0)
    toks = s.split()
    try:
        if toks and toks[0].lower() in ("ypr", "ang"):
            nums = [float(x) for x in toks[1:4]]
            yaw, pitch, roll = nums
            g = [0.0, 0.0, 0.0]
        else:
            nums = [float(x) for x in toks]
            if len(nums) == 3:                      # roll pitch yaw (or ypr)
                if fmt == "ypr":
                    yaw, pitch, roll = nums
                else:
                    roll, pitch, yaw = nums
                g = [0.0, 0.0, 0.0]
            elif len(nums) >= 6:
                if fmt == "6axis":                  # ax ay az gx gy gz -> no orientation
                    return None
                yaw, pitch, roll = nums[0:3]
                g = nums[3:6]
            else:
                return None
    except ValueError:
        return None
    return (roll * k, pitch * k, yaw * k, g[0] * k, g[1] * k, g[2] * k)


def _wrap(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


class ImuFeed:
    """Latest-frame holder for the firmware IMU stream.

    Stock firmware prints a frame at most every 200 ms (`print6Axis()`'s
    PRINT6AXIS_MIN_INTERVAL -> 5 Hz) and the MCU:/ICM: line has no angular
    rate. Callers that tick faster (run_gait at 80 Hz, SensorHub) feed every
    received line through `update()` and read `frame` every tick: orientation
    is held between prints, and angular rate is the finite difference of the
    last two frames (by Pi receive time), held likewise. Lines that do carry a
    true gyro (the legacy 6-number shapes parse_imu_line still accepts) pass
    their rate through unchanged.

    rate_mode "zero" reports zero rate instead of the finite difference.
    """

    MIN_FD_DT = 0.05     # frames closer than this (a buffered burst) don't update the rate

    def __init__(self, fmt="auto", rate_mode="fd"):
        if rate_mode not in ("fd", "zero"):
            raise ValueError(f"rate_mode must be 'fd' or 'zero', not {rate_mode!r}")
        self.fmt = fmt
        self.rate_mode = rate_mode
        self.frame = None            # (roll, pitch, yaw, gx, gy, gz) or None before the first frame
        self.stamp = None            # receive time of the latest frame
        self.frames = 0
        self._prev = None            # (t, roll, pitch, yaw) of the frame the rate was last taken from

    def update(self, lines, now):
        """Ingest raw lines received since the last call. True if any parsed."""
        fresh = False
        for line in lines:
            p = parse_imu_line(line, self.fmt) if line else None
            if p is None:
                continue
            r, pi, y, gx, gy, gz = p
            if line.lstrip().startswith(IMU_PREFIXES):
                gx, gy, gz = self._rate(now, r, pi, y)
            self.frame = (r, pi, y, gx, gy, gz)
            self.stamp = now
            self.frames += 1
            fresh = True
        return fresh

    def _rate(self, t, r, p, y):
        held = self.frame[3:] if self.frame is not None else (0.0, 0.0, 0.0)
        if self.rate_mode == "zero":
            return 0.0, 0.0, 0.0
        if self._prev is None:
            self._prev = (t, r, p, y)
            return 0.0, 0.0, 0.0
        t0, r0, p0, y0 = self._prev
        dt = t - t0
        if dt < self.MIN_FD_DT:
            return held
        self._prev = (t, r, p, y)
        return (_wrap(r - r0) / dt, _wrap(p - p0) / dt, _wrap(y - y0) / dt)

    def age(self, now):
        """Seconds since the latest frame (inf before the first)."""
        return math.inf if self.stamp is None else now - self.stamp
