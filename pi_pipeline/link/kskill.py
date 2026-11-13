"""A stand-up the firmware plays by itself: a behavior skill sent as data with the `K` token (user, 2026-11-08).

Why: the firmware's own stand-up (`kbalance`) moves all eight leg joints at once and tipped him toward the side that rose later (stand-up test 2026-11-08: lean in every stand-up, one fall in four, front right leg folded in).
The Pi's own eased stand-ups stream `i` commands, and a dropped or garbled byte leaves a leg wrong. A `K` skill is ONE message: the board holds the whole sequence and plays it frame by frame itself, rear legs
first and both sides together, with no serial traffic during the rise.

Format (read from the public OpenCat source, src/skill.h and tools.h, 2026-11-08, and from the built-in arrays in InstinctBittleESP.h; NOT yet verified on this board):
  'K' + payload + '~'   (an uppercase token is a binary payload that ends at '~'; the buffer is 2507 bytes)
  payload = 7-byte header [-N frames, expected roll, expected pitch, angle ratio (1), loop first row, loop last row, loop count]
            + N frames of 20 int8: 16 joint angles (0-7 head / arm joints, 8-15 legs in Petoi order FLs FRs BRs BLs FLk FRk BRk BLk) + [speed, delay, trigger axis, trigger angle]
  speed = raw / 8 handed to the firmware's transform(); delay = raw x 50 ms after the frame; trigger axis 0 = none.
The frame values are int8 (-128..127); 126 is the terminator's byte and is never used.
"""
from __future__ import annotations

import math
import time

DOF = 16
FRAME_LEN = DOF + 4
BUFF_LEN = 2507
TERMINATOR = b"~"
URDF_TO_SERVO = [8, 12, 9, 13, 10, 14, 11, 15]          # URDF order [FLs,FLk,FRs,FRk,BRs,BRk,BLs,BLk] -> servo index (same table as gait/standup.py)


def _i8(v: float) -> int:
    return max(-125, min(125, int(round(v))))


def _smooth(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def behavior_payload(frames: list, speeds: list, delays: list) -> bytes:
    """The `K` payload (without the 'K' and the '~') for a behavior skill: `frames` are lists of 16 angles; `speeds` and `delays` the raw timing values, one per frame."""
    n = len(frames)
    if n < 1 or n * FRAME_LEN + 7 + 2 > BUFF_LEN:
        raise ValueError(f"{n} frames do not fit the board's {BUFF_LEN}-byte buffer")
    out = [-n, 0, 0, 1, 0, 0, 0]                          # period, expected roll / pitch, angle ratio, loop (none)
    for f, sp, dl in zip(frames, speeds, delays):
        if len(f) != DOF:
            raise ValueError("a frame has 16 joint angles")
        out += [_i8(a) for a in f] + [_i8(sp), _i8(dl), 0, 0]
    return bytes(b & 0xFF for b in out)


def stand_frames(start_urdf, goal_urdf, lift0=None, lift1=None, steps: int = 18, front_start: float = 0.2, rear_end: float = 0.7) -> list:
    """The frames of the stand-up from `start_urdf` to `goal_urdf` (8 leg angles each, URDF order): the rear legs rise first over the first `rear_end` of the time, the front legs follow from `front_start` to the end,
    left and right together, each along a smooth curve; the lift servo (joint 1) eases `lift0` -> `lift1` over the whole time when both are given (the arm's rest 59 -> walking 0)."""
    frames = []
    rear, front = (4, 5, 6, 7), (0, 1, 2, 3)
    for k in range(1, steps + 1):
        u = k / steps
        f = [0.0] * DOF
        for idx in range(8):
            if idx in rear:
                w = _smooth(u / rear_end)
            else:
                w = _smooth((u - front_start) / (1.0 - front_start))
            f[URDF_TO_SERVO[idx]] = start_urdf[idx] + (goal_urdf[idx] - start_urdf[idx]) * w
        if lift0 is not None and lift1 is not None:
            f[1] = lift0 + (lift1 - lift0) * _smooth(u)
        frames.append(f)
    return frames


def tuning(from_attention: bool = False) -> dict:
    """The stand-up's timing, from pi_pipeline/motion_feel.py (that file, the owner's override file on the Pi, or G2_<NAME> for one run). `from_attention` uses the attention pose's own, slightly slower
    numbers (STAND_ATT_*). 2026-11-08 on the board: 18 frames, speed 12, a pause after each was symmetric (roll -2..+2) but "way too slow and jerky"; 8 frames, speed 24, no pause "looked good", a bit snappy;
    the stand-up out of the attention pose was then "getting close to falling" and is a little slower."""
    from .. import motion_feel as mf
    steps = max(2, int(mf.get("STAND_STEPS")))
    if from_attention:
        speed, mid, wait = max(1, int(mf.get("STAND_ATT_SPEED"))), int(mf.get("STAND_ATT_SPEED_MID")), mf.get("STAND_ATT_WAIT_S")
    else:
        speed, mid, wait = max(1, int(mf.get("STAND_SPEED"))), int(mf.get("STAND_SPEED_MID")), mf.get("STAND_WAIT_S")
    slow_n = max(0, int(mf.get("STAND_SLOW_STAGES")))
    speeds = [speed] * steps
    if mid > 0:                                           # slow at the start and the end, fast through the middle (owner, 2026-11-08: the half-up pose is where he tips)
        for k in range(slow_n, steps - slow_n):
            speeds[k] = max(1, mid)
    out = {"steps": steps, "speed": speed, "speeds": speeds, "delay": max(0, int(mf.get("STAND_PAUSE"))), "wait_s": max(0.5, wait), "front_start": 0.2, "rear_end": 0.7, "rear_hold": 0}
    if from_attention:                                    # the back legs finish rising before the front legs get going (owner, 2026-11-12)
        out["front_start"], out["rear_end"], out["rear_hold"] = float(mf.get("STAND_ATT_FRONT_START")), float(mf.get("STAND_ATT_REAR_END")), max(0, int(mf.get("STAND_ATT_REAR_HOLD")))
    return out


def stand_payload(start_urdf, goal_urdf, lift0=None, lift1=None, *, steps: int = 8, speed_raw: int = 24, delay_raw: int = 0, speeds: list | None = None, front_start: float = 0.2, rear_end: float = 0.7, rear_hold: int = 0) -> bytes:
    """The stand-up skill: `steps` frames, each a move at `speed_raw` / 8 (or its own entry of `speeds`) followed by a pause of `delay_raw` x 50 ms."""
    frames = stand_frames(start_urdf, goal_urdf, lift0, lift1, steps, front_start, rear_end)
    sp = list(speeds) if speeds is not None and len(speeds) == len(frames) else [speed_raw] * len(frames)
    delays = [delay_raw] * len(frames)
    if rear_hold > 0:                                     # a pause after the stage in which the back legs arrive: the front legs wait until they have settled
        import math as _m
        k = min(len(frames), max(1, _m.ceil(rear_end * len(frames) - 1e-9))) - 1
        delays[k] = max(delays[k], int(rear_hold))
    return behavior_payload(frames, sp, delays)


def lie_down_payload(start_urdf, goal_urdf, lift0, lift1, *, steps: int = 6, speed_raw: int = 12) -> bytes:
    """The lie-down as one eased K skill: all four legs together from `start_urdf` to `goal_urdf` and the lift servo (joint 1: the claw) from `lift0` to `lift1` along the same smooth curve, so the claw
    comes down with the legs instead of snapping to the rest pose (owner, 2026-11-12)."""
    frames = stand_frames(start_urdf, goal_urdf, lift0, lift1, steps, 0.0, 1.0)
    return behavior_payload(frames, [speed_raw] * len(frames), [0] * len(frames))


def message(payload: bytes) -> bytes:
    """What goes on the wire: 'K', the payload, '~'."""
    if TERMINATOR in payload:
        raise ValueError("a payload byte equals the terminator")
    return b"K" + payload + TERMINATOR


def play_seconds(seconds: float, steps: int) -> float:
    """How long to wait for the skill to finish (kept for callers that know the nominal time)."""
    return seconds + 0.6 + 0.05 * steps


# ---------------------------------------------------------------------------------------------------- knowing when the board has finished the skill (2026-11-08: the Pi moved on after a fixed wait while the board was still rising)
CHUNK_BYTES = 24            # the K message goes out in short pieces: the board's serial input holds about 128 bytes and a long burst can overflow it while it is busy (a lost byte shifts every later angle)
CHUNK_GAP_S = 0.006
REACHED_TOL_DEG = 6.0
POLL_S = 0.4
MIN_WAIT_S = 1.5


def write_chunked(write, data: bytes, sleep=time.sleep) -> None:
    """Send `data` in CHUNK_BYTES pieces with a short gap."""
    for i in range(0, len(data), CHUNK_BYTES):
        write(data[i:i + CHUNK_BYTES])
        sleep(CHUNK_GAP_S)


def read_joints(link, timeout_s: float = 0.8, sleep=time.sleep, clock=time.monotonic):
    """The 16 joint angles the board reports (`j`), or None. Stops the IMU stream first, as behavior/ball_chase.read_joints does (the read often failed while it ran)."""
    import re
    poll, other = getattr(link, "poll_imu", None), getattr(link, "pop_other", None)
    if not callable(poll) or not callable(other):
        return None
    from . import imu_print
    try:
        with imu_print.paused(link):                      # the print goes back on after the read if it was on
            sleep(0.1)
            poll()
            other()
            link.send("j", read_reply=False, settle=0.0)
            end = clock() + timeout_s
            while clock() < end:
                poll()
                for ln in other():
                    if ln.count(",") >= 15:
                        nums = [int(x) for x in re.findall(r"-?\d+", ln)]
                        if len(nums) >= 16 and nums[:16] != list(range(16)):
                            return nums[:16]
                sleep(0.05)
    except Exception:  # noqa: BLE001
        pass
    return None


POSE_TOL_DEG = 12.0            # a leg pose read with `j` names a known pose when every leg joint is within this of it (the same number as behavior/ball_chase.py)


def classify_start(joints, standup) -> str:
    """"rest", "sit", "attention", "stand" or "unknown" from the 16 joint angles `j` reports (what the firmware last commanded). The poses a stand-up may start from; anything else is "unknown"."""
    if not joints or len(joints) < 16:
        return "unknown"
    poses = {"rest": standup.rest_pose(), "sit": standup.SIT_URDF_DEG, "attention": standup.ATTENTION_URDF_DEG, "stand": standup.balance_pose()}
    best, err = "unknown", 1e9
    for name, pose in poses.items():
        e = max(abs(joints[URDF_TO_SERVO[k]] - float(pose[k])) for k in range(8))
        if e < err:
            best, err = name, e
    return best if err <= POSE_TOL_DEG else "unknown"


def legs_reached(joints, goal_urdf, tol: float = REACHED_TOL_DEG) -> bool:
    """True when every leg joint the board reports is within `tol` degrees of the goal pose (URDF order)."""
    if not joints or len(joints) < 16:
        return False
    return all(abs(joints[URDF_TO_SERVO[k]] - goal_urdf[k]) <= tol for k in range(8))


def entry_frames(start_urdf, goal_urdf, steps: int = 6) -> list:
    """The frames of an eased move between two leg poses (8 angles each, URDF order), all four legs together along one smooth curve. The arm joints (0-7) stay at 0: the claw is down."""
    frames = []
    for k in range(1, steps + 1):
        w = _smooth(k / steps)
        f = [0.0] * DOF
        for idx in range(8):
            f[URDF_TO_SERVO[idx]] = start_urdf[idx] + (goal_urdf[idx] - start_urdf[idx]) * w
        frames.append(f)
    return frames


def entry_payload(start_urdf, goal_urdf, *, steps: int = 6, speed_raw: int = 10) -> bytes:
    """The `K` payload for an eased move into the attention pose (or any leg pose): `steps` frames at one speed, no pauses."""
    frames = entry_frames(start_urdf, goal_urdf, steps)
    return behavior_payload(frames, [speed_raw] * len(frames), [0] * len(frames))
