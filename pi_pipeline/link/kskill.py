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


def stand_payload(start_urdf, goal_urdf, lift0=None, lift1=None, *, seconds: float = 1.8, steps: int = 18, speed_raw: int = 12) -> bytes:
    """The stand-up skill: `steps` frames spread over about `seconds`; each frame waits `seconds / steps` (in 50 ms units, at least 1) after a quick move to it."""
    frames = stand_frames(start_urdf, goal_urdf, lift0, lift1, steps)
    delay_raw = max(1, int(round(seconds / steps / 0.05)))
    return behavior_payload(frames, [speed_raw] * len(frames), [delay_raw] * len(frames))


def message(payload: bytes) -> bytes:
    """What goes on the wire: 'K', the payload, '~'."""
    if TERMINATOR in payload:
        raise ValueError("a payload byte equals the terminator")
    return b"K" + payload + TERMINATOR


def play_seconds(seconds: float, steps: int) -> float:
    """How long to wait for the skill to finish: its delays plus a margin for the moves."""
    return seconds + 0.6 + 0.05 * steps
