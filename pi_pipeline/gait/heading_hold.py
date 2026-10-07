"""Pi-side heading hold for the learned gait: steer by making one side's strides longer than the other's, outside the policy.

Why not the policy's yaw command: V2.1 never learned to turn (benchmark_v4 turn cells: measured yaw rate follows a commanded turn at +7% / -2%), so its
yaw input does nothing. A trotting robot does turn when the strides on one side are longer than on the other, so this scales the swing of the shoulder / hip
joints about the stance angle:  left legs (FL shoulder, BL hip) x (1 - u), right legs (FR shoulder, BR hip) x (1 + u), applied to the policy's joint targets.

Measured in the calibrated sim (rl_training/opencat-gym/steer_probe.py, V2.1, 12.5 s walks, 8 episodes per u):
    u = -0.2 -> +27 deg (left),  -0.1 -> +15,  0 -> -4,  +0.1 -> -20,  +0.2 -> -32 (right):  linear, about 12 deg/s of right turn per unit u,
    i.e. positive u = LONGER RIGHT strides = a RIGHT turn (the opposite of what one might guess).
Heading here is the gait loop's rebased IMU yaw: + = RIGHT (the firmware convention, run_gait.POLICY_YAW_SIGN flips it only for the policy's input).

Controller: u = -(KP * e + KI * integral(e)), e = heading error in degrees (right-positive), so a drift to the right gives a negative u (longer left strides,
shorter right ones). u is clipped to +-U_MAX and slew-limited, the integral is frozen while u is saturated (anti-windup), and the hold releases (u -> 0)
when asked to (standing, fallen). Default gains: loop gain 12 deg/s per u x KP 0.02 /deg = 0.24 /s (a ~4 s time constant) with a small integral term for
the steady push. Authority is limited: a steady drift above ~2.4 deg/s (G2's average is ~+3) is only partly cancelled (about half), a smaller one is
removed. Off unless run_gait is given --heading-hold.
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
    def __init__(self, target_deg: float = 0.0, kp: float = KP, ki: float = KI, u_max: float = U_MAX, u_rate: float = U_RATE):
        self.target_deg, self.kp, self.ki, self.u_max, self.u_rate = target_deg, kp, ki, u_max, u_rate
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
        want = -(self.kp * e + self.ki * self.integral)
        if abs(want) < self.u_max:                       # anti-windup: only integrate while the output is not saturated
            self.integral += e * dt
        want = max(-self.u_max, min(self.u_max, -(self.kp * e + self.ki * self.integral)))
        return self._slew(want, dt)

    def _slew(self, want: float, dt: float) -> float:
        step = self.u_rate * dt
        self.u += max(-step, min(step, want - self.u))
        return self.u


def apply_stride_difference(joint_deg, u: float):
    """The policy's 8 joint targets (URDF order, degrees) with the left swing scaled by (1 - u) and the right by (1 + u) about the stance angle."""
    out = [float(v) for v in joint_deg]
    for j in LEFT_JOINTS:
        out[j] = STANCE_DEG + (1.0 - u) * (out[j] - STANCE_DEG)
    for j in RIGHT_JOINTS:
        out[j] = STANCE_DEG + (1.0 + u) * (out[j] - STANCE_DEG)
    return [int(round(v)) for v in out]
