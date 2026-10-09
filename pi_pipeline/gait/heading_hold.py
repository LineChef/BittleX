"""Pi-side heading hold for the learned gait: steer by making one side's strides longer than the other's, outside the policy.

Why not the policy's yaw command: V2.1 never learned to turn (benchmark_v4 turn cells: measured yaw rate follows a commanded turn at +7% / -2%), so its
yaw input does nothing. A trotting robot does turn when the strides on one side are longer than on the other, so this scales the swing of the shoulder / hip
joints about the stance angle:  left legs (FL shoulder, BL hip) x (1 - u), right legs (FR shoulder, BR hip) x (1 + u), applied to the policy's joint targets.

Sign, MEASURED ON THE REAL G2 (2026-10-06, fixed-u walks, 12.5 s, heading change: right-positive): the first version of this module (and the sim's
steer_probe.py) took longer RIGHT strides to mean a RIGHT turn. On G2 it is the other way, as for a vehicle whose right wheel runs faster: longer right strides
turn him LEFT. The first A/B (hold on, drift +82 vs off +65 deg) steered the wrong way for that reason. Fixed-u walks with the old sign: u = -0.2 -> +89 deg,
0 -> +44, +0.2 -> -35 (about 25 deg/s of turn per unit of u, twice the sim's 12). So positive u here is now defined as a RIGHT turn again, which means
LONGER LEFT strides: left legs (FL shoulder, BL hip) x (1 + u), right legs (FR shoulder, BR hip) x (1 - u), applied to the policy's joint targets.
Heading here is the gait loop's rebased IMU yaw: + = RIGHT (the firmware convention, run_gait.POLICY_YAW_SIGN flips it only for the policy's input).

Controller: u = -(KP * e + KI * integral(e)), e = heading error in degrees (right-positive), so a drift to the right gives a negative u (longer right strides,
shorter left ones: G2 turns left). u is clipped to +-U_MAX and slew-limited, the integral is frozen while u is saturated (anti-windup), and the hold releases (u -> 0)
when asked to (standing, fallen). Default gains: loop gain 12 deg/s per u x KP 0.02 /deg = 0.24 /s (a ~4 s time constant) with a small integral term for
the steady push. Authority at u = 0.20 is about 5 deg/s on the real G2 (the sim said 2.4), more than G2's ~+3.3 deg/s average drift. Off unless run_gait is given --heading-hold.
"""
from __future__ import annotations

import math

STANCE_DEG = 50.0                       # the shoulder / hip stance angle the swing is scaled about (run_gait.STAND_URDF_DEG)
LEFT_JOINTS = (0, 6)                    # URDF order: 0 FLsh 1 FLel 2 FRsh 3 FRel 4 BRhip 5 BRkn 6 BLhip 7 BLkn
RIGHT_JOINTS = (2, 4)

# Largest / smallest target (degrees) a scaled joint may be sent: the range the UNSCALED V2.1 walk uses on that joint (logged on G2) plus a margin. Stretching the right
# strides by 25-38% took the back-right hip to 86 deg (unscaled max 75) and the front-right shoulder to -5 / 91; at that reach the leg lies parallel to the floor and G2
# lands on the leg instead of the foot (seen on G2, 2026-10-06, close to a fall). The stable runs (u = -0.20) reached 80-85 deg at the hip / shoulder.
JOINT_MARGIN_DEG = 6.0
JOINT_RANGE_DEG = {0: (11, 74), 2: (11, 80), 4: (22, 75), 6: (28, 85)}      # FL shoulder, FR shoulder, BR hip, BL hip: unscaled min / max

KP = 0.02                               # u per degree of heading error
KI = 0.004                              # u per degree-second of accumulated error
U_MAX = 0.20                            # largest stride difference (fraction): cancels up to ~2.4 deg/s of steady drift (G2's is ~+3 deg/s on average)
U_RATE = 0.20                           # largest change of u per second


def wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


class HeadingHold:
    def __init__(self, target_deg: float = 0.0, kp: float = KP, ki: float = KI, u_max: float = U_MAX, u_rate: float = U_RATE, ff: float = 0.0, i_lim: float = 0.08):
        self.target_deg, self.kp, self.ki, self.u_max, self.u_rate = target_deg, kp, ki, u_max, u_rate
        self.i_lim = i_lim                  # the integral term's contribution to u is clamped to +-i_lim (it wound up on G2 and kept steering left after the heading was back)
        self.ff = ff                        # feed-forward stride difference added to the feedback (the known steady drift, so the integral term starts near the answer)
        self.integral = 0.0
        self.u = 0.0
        self.fixed_u = None                 # set to a number to hold that stride difference with no feedback (measures the lever's real sign / authority)

    def reset(self) -> None:
        self.integral = 0.0
        self.u = 0.0

    def update(self, yaw_rad: float, dt: float, active: bool = True) -> float:
        """One control tick. yaw_rad: the rebased IMU yaw, right-positive. Returns the stride difference u to apply."""
        if not active:
            return self._slew(0.0, dt)
        if self.fixed_u is not None:
            return self._slew(max(-self.u_max, min(self.u_max, self.fixed_u)), dt)
        e = wrap_deg(math.degrees(yaw_rad) - self.target_deg)
        want = self.ff - (self.kp * e + self.ki * self.integral)
        if abs(want) < self.u_max:                       # anti-windup: only integrate while the output is not saturated
            self.integral += e * dt
        want = max(-self.u_max, min(self.u_max, self.ff - (self.kp * e + self.ki * self.integral)))
        return self._slew(want, dt)

    def _slew(self, want: float, dt: float) -> float:
        step = self.u_rate * dt
        self.u += max(-step, min(step, want - self.u))
        return self.u


FOOT_JOINT = {"fl": 0, "fr": 2, "br": 4, "bl": 6}        # one foot's shoulder / hip joint, URDF order (front-left, front-right, back-right, back-left)


def parse_foot_trim(text: str):
    """`bl=+0.25` -> ("bl", 0.25); None for an empty text. The foot's swing is scaled about the stance angle by (1 + that number): positive = a longer step on that foot."""
    if not text:
        return None
    foot, _, val = text.partition("=")
    foot = foot.strip().lower()
    if foot not in FOOT_JOINT:
        raise ValueError(f"unknown foot {foot!r}; use one of {', '.join(FOOT_JOINT)}")
    return foot, float(val)


def parse_foot_trims(text: str):
    """`fl=-0.3/fr=+0.3` -> [("fl", -0.3), ("fr", 0.3)]: several feet at once, "/"-separated; None for an empty text."""
    if not text:
        return None
    return [parse_foot_trim(part) for part in text.split("/") if part.strip()] or None


def apply_foot_trims(joint_deg, trims):
    out = joint_deg
    for foot, g in trims:
        out = apply_foot_trim(out, foot, g)
    return out


def apply_foot_trim(joint_deg, foot: str, g: float):
    """The policy's 8 joint targets (URDF order, degrees) with ONE foot's swing scaled about the stance angle by (1 + g) and every other joint left alone, clamped to the reach the walk itself
    uses (JOINT_RANGE_DEG). A per-foot steering test (2026-10-07: in the sim only the back feet steer, and G2's steering is opposite and about 4 times stronger, so which foot steers on G2 is measured)."""
    out = [float(v) for v in joint_deg]
    j = FOOT_JOINT[foot]
    out[j] = STANCE_DEG + (1.0 + g) * (out[j] - STANCE_DEG)
    lo, hi = JOINT_RANGE_DEG[j]
    out[j] = max(lo - JOINT_MARGIN_DEG, min(hi + JOINT_MARGIN_DEG, out[j]))
    return [int(round(v)) for v in out]


def apply_stride_difference(joint_deg, u: float):
    """The policy's 8 joint targets (URDF order, degrees) with the left swing scaled by (1 + u) and the right by (1 - u) about the stance angle
    (u > 0: longer left strides = a RIGHT turn on the real G2; measured, see the module docstring)."""
    out = [float(v) for v in joint_deg]
    for j in LEFT_JOINTS:
        out[j] = STANCE_DEG + (1.0 + u) * (out[j] - STANCE_DEG)
    for j in RIGHT_JOINTS:
        out[j] = STANCE_DEG + (1.0 - u) * (out[j] - STANCE_DEG)
    for j in LEFT_JOINTS + RIGHT_JOINTS:                                  # never past the reach the walk itself uses (see JOINT_RANGE_DEG)
        lo, hi = JOINT_RANGE_DEG[j]
        out[j] = max(lo - JOINT_MARGIN_DEG, min(hi + JOINT_MARGIN_DEG, out[j]))
    return [int(round(v)) for v in out]


def default_foot_hold():
    """Which foot every real-hardware policy walk steers with: `G2_FOOT_HOLD` (default `fl`, the front-left foot, which turned G2 on the real robot 2026-10-07: a closed-loop hold kept V2.1
    within 13-21 deg of its starting heading over 10 ft against +148 deg without). `off` / `none` / empty turns it off. Returns the foot name or None."""
    import os
    v = os.environ.get("G2_FOOT_HOLD", "fl").strip().lower()
    return None if v in ("", "off", "none", "0", "false") else v


def default_foot_hold_ff() -> float:
    """`G2_FOOT_HOLD_FF`: the feed-forward trim of the everyday hold (default 0.0 until the hardware A/B has run; try -0.25)."""
    import os
    try:
        return float(os.environ.get("G2_FOOT_HOLD_FF", "0") or 0.0)
    except ValueError:
        return 0.0


class FootHold:
    """Heading hold on ONE front foot (measured on G2, 2026-10-07, scripted walk): front-left alone takes ~9 deg/s of turn per unit of trim (-0.25 -> -35 deg, -0.5 -> -57 deg over
    12.5 s against ~78 deg of drift), the back feet do nothing, and a front pair adds a lean. Trim g scales that foot's swing (apply_foot_trim); a NEGATIVE g shortens the step and
    turns G2 left, so a drift to the right (e > 0, right-positive) asks for g < 0.

    g = -(KP * deadband(e) + KD * rate): the proportional term acts only outside +-DEADBAND_DEG; the rate term is the ease-off in both directions: it adds trim while the heading
    is running away and takes it off as soon as the heading is already turning back (rate toward the target), so the correction does not overshoot while the 5 Hz IMU is still
    reporting the old heading. g is clamped to [G_MIN, G_MAX] and slew-limited. G_MIN was -0.6 (the trim the first walks tolerated); 2026-10-09 V4 on hardware turned right ~8 deg/s with the hold off and the hold sat at -0.6 the whole walk
    (one unit of trim is ~9 deg/s), so it is -0.9 (user: more authority); -1.0 would stop the foot's swing altogether and below that it would reverse."""

    def __init__(self, foot: str = "fl", target_deg: float = 0.0, kp: float = 0.02, kd: float = 0.08, deadband_deg: float = 6.0,
                 g_min: float = -0.9, g_max: float = 0.2, g_rate: float = 0.30, rate_tau_s: float = 0.8, ki: float = 0.01, i_lim: float = 0.4, ff: float = 0.0, g_release: float = 1.2, release_rate_dps: float = 3.0):
        self.g_release, self.release_rate_dps = g_release, release_rate_dps   # easing off is faster than building up: once the heading turns back (or is already past the target) the trim drops at g_release per second
        self.ff = ff                         # feed-forward trim added to the feedback: the average trim the hold ends up at anyway (about -0.2..-0.3 on G2), so it does not have to ramp to it
        self.foot, self.target_deg, self.kp, self.kd, self.deadband_deg = foot, target_deg, kp, kd, deadband_deg
        self.g_min, self.g_max, self.g_rate, self.rate_tau_s = g_min, g_max, g_rate, rate_tau_s
        self.ki, self.i_lim, self.integral = ki, i_lim, 0.0      # the steady push a P term alone leaves as a standing heading error; cleared when the heading crosses the target
        self.g = 0.0
        self.rate_dps = 0.0                  # low-passed heading rate, deg/s, right-positive
        self._last_yaw = None
        self._last_t = 0.0
        self._t = 0.0

    def reset(self) -> None:
        self.g, self.rate_dps, self._last_yaw = 0.0, 0.0, None

    def update(self, yaw_rad: float, dt: float, active: bool = True) -> float:
        self._t += dt
        yaw = math.degrees(yaw_rad)
        if self._last_yaw is None:
            self._last_yaw, self._last_t = yaw, self._t
        elif yaw != self._last_yaw:           # a new IMU sample (5 Hz): turn the change into a rate
            span = max(1e-3, self._t - self._last_t)
            raw = wrap_deg(yaw - self._last_yaw) / span
            a = min(1.0, span / self.rate_tau_s)
            self.rate_dps += a * (raw - self.rate_dps)
            self._last_yaw, self._last_t = yaw, self._t
        if not active:
            self._releasing = True
            return self._slew(0.0, dt)
        e = wrap_deg(yaw - self.target_deg)
        out = max(0.0, abs(e) - self.deadband_deg) * (1.0 if e >= 0 else -1.0)
        releasing = self.g < 0.0 and (e <= 0.0 or self.rate_dps < -self.release_rate_dps)     # the trim is pushing left and the heading is already at / past the target or turning left
        self._releasing = releasing
        if releasing or out == 0.0 or (self.integral != 0.0 and (out > 0) != (self.integral > 0)):
            self.integral = 0.0                   # inside the deadband or past the target: drop the wound-up term (it kept steering after the heading was back on the old hold)
        else:
            self.integral = max(-self.i_lim / self.ki, min(self.i_lim / self.ki, self.integral + out * dt))
        want = self.ff - (self.kp * out + self.ki * self.integral + self.kd * self.rate_dps)
        return self._slew(max(self.g_min, min(self.g_max, want)), dt)

    def _slew(self, want: float, dt: float) -> float:
        # a trim moving away from zero is slew-limited (g_rate); one moving back to zero while releasing, or being released because the hold went inactive, uses the faster g_release
        toward_zero = abs(want) < abs(self.g)
        step = (self.g_release if (toward_zero and getattr(self, "_releasing", True)) else self.g_rate) * dt
        self.g += max(-step, min(step, want - self.g))
        return self.g
