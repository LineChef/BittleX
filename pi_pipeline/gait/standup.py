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


def _poses():
    """The fitted attachment's own stand-up poses (gait_profiles.json "poses"), or None for the stock build: the arm firmware shifts every pose (front shoulders -10, front knees +6) and its
    lift servo (joint 1) rests at 59 with the claw on the floor. {"rest_urdf_deg", "balance_urdf_deg" (URDF order), "arm_rest", "arm_walk", "stand_ease"}."""
    try:
        from pi_pipeline.attachments import current, load_profiles
        return (load_profiles().get(current()) or {}).get("poses") or None
    except Exception:  # noqa: BLE001 -- scripts run by path have no package; the stock poses are the safe answer
        return None


def rest_pose():
    p = _poses()
    return [float(x) for x in p["rest_urdf_deg"]] if p and p.get("rest_urdf_deg") else list(REST_URDF_DEG)


def balance_pose():
    p = _poses()
    return [float(x) for x in p["balance_urdf_deg"]] if p and p.get("balance_urdf_deg") else list(BALANCE_URDF_DEG)


def _easing_on() -> bool:
    """The fitted attachment's `easing` switch (the arm turns every ramp off for its first tests, user 2026-10-24); on when it cannot be read."""
    try:
        from pi_pipeline.attachments import flag_safe
    except ImportError:
        return True
    return flag_safe("easing")


def ramp_seconds() -> float:
    if not _easing_on():
        return 0.0
    v = os.environ.get("G2_STAND_RAMP_S", "").strip().lower()
    if v in ("off", "none", "false", "no"):
        return 0.0
    try:
        return max(0.0, float(v)) if v else DEFAULT_RAMP_S
    except ValueError:
        return DEFAULT_RAMP_S


SIT_TO_REST_S = 2.0          # a stand-up that starts from a sit first eases down to rest this long (SerialLink._stand_up; the front knee moves 100 deg, so 2.0 s keeps its peak near 75 deg/s), then stands up from rest


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
    if c in ("", "d", "krest", "kzz"):
        return rest_pose()
    if c in ("kbalance", "kup"):
        return balance_pose()
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
    if stand_sequenced(send, sleep, last_motion_command) or stand_via_firmware(send, sleep, last_motion_command):
        last_motion_command = "kbalance"
    secs = ramp_seconds() if seconds is None else seconds
    start = start_pose(last_motion_command)
    if secs <= 0 or start is None or max(abs(a - b) for a, b in zip(start, stand_deg)) < 3:
        return False
    for pose in ramp_poses(start, stand_deg, secs):
        send(make_cmd([int(round(x)) for x in pose]))
        sleep(1.0 / STEPS_PER_S)
    return True



SEQ_REAR_S, SEQ_FRONT_S = 1.0, 1.4           # the sequenced stand-up: the rear legs rise over this long, then the front legs
_REAR_URDF = (4, 5, 6, 7)                    # URDF order [FLs,FLk,FRs,FRk,BRs,BRk,BLs,BLk]: the rear legs ...
_FRONT_URDF = (0, 1, 2, 3)                   # ... and the front legs


def stand_sequenced(send, sleep=time.sleep, last_motion_command=None) -> bool:
    """The arm build's stand-up in order (profile "poses": {"stand_via": "sequenced"}; 2026-10-25: the firmware kbalance moves all eight leg joints at once and G2 fell front right
    when the nose rose with the claw out ahead). From rest: (1) the rear legs ease to the balance pose with the front paws and the claw on the floor, (2) the front legs follow, slower,
    (3) the firmware `kbalance` finishes, which only has the lift servo left to do (60 -> 0), the legs already being there. Returns True if it ran."""
    p = _poses()
    c = (last_motion_command or "").strip()
    if not p or p.get("stand_via") != "sequenced" or c not in ("", "d", "krest", "kzz"):
        return False
    start, goal = rest_pose(), balance_pose()
    now = list(start)
    for group, secs in ((_REAR_URDF, SEQ_REAR_S), (_FRONT_URDF, SEQ_FRONT_S)):
        for pose in ramp_poses([start[k] for k in group], [goal[k] for k in group], secs):
            for k, v in zip(group, pose):
                now[k] = v
            send(move_cmd(now))
            sleep(1.0 / STEPS_PER_S)
    send("kbalance")
    sleep(1.5)
    return True


def stand_via_firmware(send, sleep=time.sleep, last_motion_command=None) -> bool:
    """The arm build stands up with the plain firmware `kbalance` (profile "poses": {"stand_via": "kbalance"}), which also sets the lift servo to its walking angle (0). Used by the walk
    loops when they start from rest: the Pi never sets joint 1 itself, so a walk that began from `rest` walked with the claw reaching forward (lift 59, the claw on the floor).
    The Pi's own ramp of the lift (12 `i 1 N` at 20 per second) and an eased leg stand-up reset the BiBoard on G2 (2026-10-25), so neither is used. Returns True if it ran
    (the caller's stand command then follows, from the balance pose)."""
    p = _poses()
    c = (last_motion_command or "").strip()
    if not p or p.get("stand_via") != "kbalance" or c not in ("", "d", "krest", "kzz"):
        return False
    send("kbalance")
    sleep(2.0)
    return True


BLEND_S = 0.6


def blend_to_balance(send, make_cmd=move_cmd, sleep=time.sleep, last_motion_command=None, seconds=BLEND_S) -> bool:
    """Ease the legs from where the last command left them (often mid-stride, a foot in the air) to the balance pose before the `kbalance` token, instead of snapping there (user, 2026-10-10: exploration walks
    ended with one foot in the air and were unstable). Returns True if a blend ran; an unknown last pose (a firmware gait, a skill) is left to the firmware, as for the stand-up.
    No blend while the fitted attachment has easing off."""
    if not _easing_on():
        return False
    return ramp_to_stand(send, make_cmd, BALANCE_URDF_DEG, sleep=sleep, last_motion_command=last_motion_command, seconds=seconds)
