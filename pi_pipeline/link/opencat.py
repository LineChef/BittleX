"""OpenCat serial command vocabulary -- string builders only, no I/O.

The BiBoard runs OpenCatEsp32 firmware and takes newline-terminated ASCII
commands over serial. This module builds the command strings the pipeline needs
and gates the dangerous ones.

Confirmed against PetoiCamp/OpenCatEsp32 src (OpenCat.h T_* macros, 2026-09-07 --
see docs/research/petoi-firmware-reference.md) and the project's Phase 4 notes:
  k<skill>            perform a named skill        e.g. "kwkF", "ksit", "kbalance"
  m<idx> <deg> ...    move joint(s), chainable     e.g. "m0 30 8 -35"
  b<tone> <ms> ...    buzzer melody / beep         e.g. "b12 8 14 8"
  d                   rest: lie down, relax servos (used to end a looping gait)
  P                   print battery voltage        (T_POWER)
  j / j <idx>         return all joint angles / one joint   (T_JOINTS)
  f                   servo position feedback, if supported (T_SERVO_FEEDBACK)
  g                   gyro function toggle                  (T_GYRO)
  gU / gB / gc        gyro: force update / balance-on / calibrate IMU
  p                   pause                                 (T_PAUSE)
  t                   tilt command                          (T_TILT)
  XS                  enter Serial-2 working mode (BiBoard <-> Pi)  [Phase 4 note]

NOT a token: v / V is firmware version, NOT "print IMU" (earlier guess here was
wrong). To read orientation, use `gU` then read, or the firmware exception stream.

Not exposed (need a human / can damage the robot): c, cd (calibration), factory
resets.
"""
from __future__ import annotations

REST = "d"                       # lie down, servos relaxed
ENTER_SERIAL2_MODE = "XS"        # BiBoard: talk to the Pi over UART2
PRINT_VOLTAGE = "P"              # T_POWER -- battery voltage
READ_JOINTS = "j"                # T_JOINTS -- bare: all angles; "j <idx>": one
SERVO_FEEDBACK = "f"             # T_SERVO_FEEDBACK
GYRO_TOGGLE = "g"                # T_GYRO -- toggle gyro function
GYRO_UPDATE = "gU"              # force a gyro data update
GYRO_BALANCE_ON = "gB"          # enable gyro balancing
PAUSE_TOGGLE = "p"               # T_PAUSE
TILT = "t"                       # T_TILT
QUERY = "?"                      # help/status -- not seen in the partial OpenCat.h
                                 # fetch; verify against the firmware parser

# --- recovery / get-up ------------------------------------------------------
# Built-in OpenCat keyframe skills for getting back up after a fall. `rc` and
# `rl` are "Instinct" (firmware) skills; the firmware also auto-runs `rc` on an
# IMU-detected flip when gyro assist is on. Verified against
# PetoiCamp/OpenCat/src/InstinctBittle.h -- see docs/research/self-righting-research.md.
# Bittle has no roll-axis joint, so these scripted sequences (which lever the
# body over using the legs) are the recovery path -- not a learned policy.
RECOVER = "krc"                  # self-right / get-up from a side or forward fall
ROLL_OVER = "krl"               # roll from supine (on its back) toward prone
DROP_RECOVER = "kdropRec"       # last-ditch scripted flail-to-upright (firmware `dropRec`)
BALANCE = "kbalance"            # settle into a balanced stand (used after a get-up)
STAND = "kup"                   # neutral standing posture

# --- locomotion skills ----------------------------------------------------
# `wkR` is the firmware's L/R mirror of `wkL` -- the skill parser accepts an
# `R` suffix and mirrors. At near-zero forward these become a shuffling pivot
# (turn-ish). `kang <deg>` (IMU closed-loop) is the cleaner turn-in-place but
# needs on-hardware tuning -- see cliff_guard.py.
WALK_LEFT = "kwkL"              # curved walk left / near-zero-fwd pivot left
WALK_RIGHT = "kwkR"            # mirror of wkL
WALK_BACKWARD = "kbkF"          # walk backward

_BLOCKED_PREFIXES = ("c", "cd")  # calibration / factory -- never from the pipeline


def skill(token: str) -> str:
    """'wkF' -> 'kwkF'. `token` is the OpenCat skill token, not a friendly name."""
    token = token.strip()
    if not token:
        raise ValueError("empty skill token")
    return "k" + token


def move_joints(pairs: list[tuple[int, int]]) -> str:
    """[(0, 30), (8, -35)] -> 'm0 30 8 -35'."""
    if not pairs:
        raise ValueError("no joints given")
    flat = " ".join(f"{idx} {deg}" for idx, deg in pairs)
    return "m" + flat


def beep(notes: list[tuple[int, int]]) -> str:
    """[(12, 8), (14, 8)] -> 'b12 8 14 8'  (tone index, duration units)."""
    if not notes:
        raise ValueError("no notes given")
    return "b" + " ".join(f"{tone} {dur}" for tone, dur in notes)


def is_safe(command: str) -> bool:
    """False for calibration / factory-reset commands."""
    c = command.strip()
    return bool(c) and not any(
        c == p or c.startswith(p + " ") for p in _BLOCKED_PREFIXES
    )
