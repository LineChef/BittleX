"""Eased stand-up before a walk: the Pi steps the legs from the rest pose to the policy's stand pose.

The walk loops used to send the stand pose as one `i` command from rest, which moves every leg servo at top speed and jerks G2's heading before the first step
(2026-10-10: heading change 10-12 deg in 2 of 3 stand-ups, roll up to 16 deg; a 20 s run started at 12:30 instead of 12). The firmware's `kbalance` was tried first and stood
up faster and nearly fell. Now: small `i` steps along an S-curve from the firmware's `rest` pose (InstinctBittleESP.h: shoulders 75, knees -55) to the stand pose, 20 steps/s.
Tuned on G2 with the user watching: 1.6 s and 1.2 s were too slow, `kup` slightly too fast, 0.8 s right (heading change under 0.3 deg in 7 stand-ups, no beeping).

`G2_STAND_RAMP_S` sets the duration in seconds (default 0.8; 0 or `off` = the old single jump). Standing rule (user, 2026-10-10): every stand-up uses it, no exceptions. The start pose comes
from the link's last motion command: `d` or none yet (a fresh process) = the rest pose, `kbalance` / `kup` = the balance pose, an `i...` command = the angles in it; anything else (a firmware gait
mid-stride, a skill) is unknown and is left to the firmware. Two places apply it: the walk loops (`ramp_to_stand`, from any known pose to the policy stand) and `SerialLink.send` (`kup` / `kbalance`
sent from rest, so the voice "stand up", wake-up, get-up choreography and exploration all get it). A stop / freeze `kbalance` (from a stride, an emergency) is NOT a stand-up and stays immediate.
"""
from __future__ import annotations

import os
import time

REST_URDF_DEG = [75, -55] * 4        # the firmware `rest` skill pose, URDF order [shoulder, knee] per leg (servo degrees = URDF degrees, sign +1 / offset 0)
DEFAULT_RAMP_S = 0.8
STEPS_PER_S = 20


def ramp_seconds() -> float:
    v = os.environ.get("G2_STAND_RAMP_S", "").strip().lower()
    if v in ("off", "none", "false", "no"):
        return 0.0
    try:
        return max(0.0, float(v)) if v else DEFAULT_RAMP_S
    except ValueError:
        return DEFAULT_RAMP_S


def ramp_poses(start, end, seconds, steps_per_s=STEPS_PER_S):
    """S-curve (smoothstep) steps from `start` to `end` (8 URDF angles each), the last one exactly `end`."""
    n = max(1, int(round(seconds * steps_per_s)))
    out = []
    for i in range(1, n + 1):
        u = i / n
        k = u * u * (3 - 2 * u)
        out.append([s + (e - s) * k for s, e in zip(start, end)])
    return out


BALANCE_URDF_DEG = [30, 30] * 4      # the firmware `balance` / `up` skill pose (shoulders 30, knees 30)
SIT_URDF_DEG = [45.0, 45.0, 45.0, 45.0, 105.0, -45.0, 105.0, -45.0]      # the firmware `sit` pose, decoded from InstinctBittleESP.h (reference_gait/sit_ref.npy), URDF order
_URDF_TO_SERVO = [8, 12, 9, 13, 10, 14, 11, 15]       # same table as gait/deploy_map.py (a test checks they agree); kept here so the serial link needs no numpy


def move_cmd(deg) -> str:
    """8 URDF angles -> the `i` command (same as deploy_map.policy_deg_to_move_cmd, no numpy)."""
    return "i" + " ".join(f"{_URDF_TO_SERVO[k]} {max(-120, min(120, int(round(deg[k]))))}" for k in range(8))


def start_pose(last_motion_command):
    """The leg angles (URDF order) G2 is in after `last_motion_command`, or None if unknown."""
    c = (last_motion_command or "").strip()
    if c in ("", "d"):
        return list(REST_URDF_DEG)
    if c in ("kbalance", "kup"):
        return list(BALANCE_URDF_DEG)
    if c == "ksit":
        return list(SIT_URDF_DEG)
    if c.startswith("i"):
        try:
            nums = [int(x) for x in c[1:].split()]
            pairs = dict(zip(nums[0::2], nums[1::2]))
            return [float(pairs[_URDF_TO_SERVO[k]]) for k in range(8)]
        except (ValueError, KeyError):
            return None
    return None


def ramp_to_stand(send, make_cmd, stand_deg, sleep=time.sleep, last_motion_command=None, seconds=None) -> bool:
    """Ramp from where the last command left the legs to `stand_deg`. `send(cmd)` is the caller's fire-and-forget send, `make_cmd(deg_list)` builds the `i` command.
    Returns True if the ramp ran (the caller still sends the exact stand pose afterwards)."""
    secs = ramp_seconds() if seconds is None else seconds
    start = start_pose(last_motion_command)
    if secs <= 0 or start is None or max(abs(a - b) for a, b in zip(start, stand_deg)) < 3:
        return False
    for pose in ramp_poses(start, stand_deg, secs):
        send(make_cmd([int(round(x)) for x in pose]))
        sleep(1.0 / STEPS_PER_S)
    return True
