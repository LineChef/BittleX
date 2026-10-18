"""Small pieces shared by the walk loops (run_gait.py) and the bench walks (walk_tools.py): the IMU -> policy quaternion, the loop constants,
and the fire-and-forget send. Split out of run_gait.py 2026-10-18 (no behaviour change); run_gait re-exports every name."""
from __future__ import annotations

import math
import os

import numpy as np


def euler_to_quat(roll, pitch, yaw):
    """(r,p,y) rad -> quaternion [x,y,z,w], inverse of residual_policy.quat_to_euler."""
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return np.array([
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    ])


# The firmware IMU stream (imu_parse) reports + yaw for a RIGHT turn (confirmed on G2 2026-10-02); the policy was
# trained in PyBullet, where + yaw is a LEFT turn (z up). Until 2026-10-06 the rebased yaw went into the policy with
# the wrong sign: harmless for V2.1 (it ignores heading, docs/archive/rl/v3-retrain-plan.md §1.1), wrong for any policy that
# uses it. Logs keep the firmware convention (+ = right); only the policy's input is flipped.
POLICY_YAW_SIGN = float(os.environ.get("G2_POLICY_YAW_SIGN", "-1"))   # -1 is correct; +1 reproduces the pre-2026-10-06 behaviour, for A/B tests only


def policy_quat(roll, pitch, yaw_fw):
    """IMU (roll, pitch, rebased firmware yaw) rad -> the quaternion the policy expects (PyBullet yaw sign)."""
    return euler_to_quat(roll, pitch, POLICY_YAW_SIGN * yaw_fw)


FALL_ABORT_S = 0.3                                # how long a >fall_abort_deg tilt must persist before the loop rests
STAND_URDF_DEG = [50, 0, 50, 0, 50, 0, 50, 0]     # matches env.reset() start pose
IMU_STALE_S = 0.6     # no IMU frame for this long (3 missed 5 Hz prints) -> stop


def _latest_imu_line(lk):
    """Newest IMU line received since the last call (non-blocking), or None."""
    lines = lk.poll_imu()
    return lines[-1] if lines else None


def _send(lk, cmd):
    """Fire-and-forget serial send -- no reply wait."""
    lk.send(cmd, read_reply=False, settle=0.0)
