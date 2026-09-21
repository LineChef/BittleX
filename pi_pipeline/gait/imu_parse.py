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
    for prefix in ("MCU:", "ICM:"):
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
