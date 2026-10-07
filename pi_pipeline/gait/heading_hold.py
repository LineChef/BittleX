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

KP = 0.02                               # u per degree of heading error
KI = 0.004                              # u per degree-second of accumulated error
U_MAX = 0.20                            # largest stride difference (fraction): cancels up to ~2.4 deg/s of steady drift (G2's is ~+3 deg/s on average)
U_RATE = 0.20                           # largest change of u per second


def wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


class HeadingHold:
    def __init__(self, target_deg: float = 0.0, kp: float = KP, ki: float = KI, u_max: float = U_MAX, u_rate: float = U_RATE, ff: float = 0.0):
        self.target_deg, self.kp, self.ki, self.u_max, self.u_rate = target_deg, kp, ki, u_max, u_rate
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


def apply_stride_difference(joint_deg, u: float):
    """The policy's 8 joint targets (URDF order, degrees) with the left swing scaled by (1 + u) and the right by (1 - u) about the stance angle
    (u > 0: longer left strides = a RIGHT turn on the real G2; measured, see the module docstring)."""
    out = [float(v) for v in joint_deg]
    for j in LEFT_JOINTS:
        out[j] = STANCE_DEG + (1.0 + u) * (out[j] - STANCE_DEG)
    for j in RIGHT_JOINTS:
        out[j] = STANCE_DEG + (1.0 - u) * (out[j] - STANCE_DEG)
    return [int(round(v)) for v in out]
