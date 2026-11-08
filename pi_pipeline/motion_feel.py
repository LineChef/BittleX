"""HOW G2'S SLOW MOVES FEEL: the numbers you can change (owner, 2026-11-08: "show me the file where I can modify these settings myself").

Edit the numbers below and have them deployed (`g2deploy`, or ask), or, to try a value on the robot WITHOUT a deploy, write only the ones you want to change into
`~/.local/share/g2/motion_feel.json` on the Pi, for example {"STAND_SPEED": 18, "CLAW_DEG_S": 45}. That file wins over this one and survives deploys. The stand-up numbers are read at every stand-up; the claw numbers when the program starts (the voice service or a goal run), so restart it after changing those.
An environment variable of the same name with G2_ in front (G2_STAND_SPEED=18) wins over both, for one run.

THE STAND-UP FROM REST (played by the board as one `K` skill; pi_pipeline/link/kskill.py; turned on with G2_STAND_VIA=kskill until it is the default)
  STAND_STEPS   how many stages the rise is cut into. More = smoother but each stage takes time.        (8)
  STAND_SPEED   how fast each stage moves. The firmware's speed is this number / 8, so BIGGER = FASTER.   (20; 24 looked "good but a bit snappy" on 2026-11-08)
  STAND_SPEED_MID  a faster speed for the stages in the MIDDLE of the rise (0 = no, every stage at STAND_SPEED). The half-up pose is where he tips, so: slow at the start and end
                   (STAND_SPEED), fast through the middle (this).                                                                      (0)
  STAND_SLOW_STAGES  how many stages at the start and at the end stay at the slow STAND_SPEED when STAND_SPEED_MID is set.                (2)
  STAND_PAUSE   a pause after each stage, in 50 ms units. 0 = none. Any pause makes it stop-and-go.        (0)
  STAND_WAIT_S  how long the Pi waits for the rise to finish before the next command. Lower the speed, raise this.   (2.6)

THE CLAW RAISE / SWING IN A LOOK (the arm's two servos are sent a new position this many times a second)
  CLAW_DEG_S         how fast the arm moves, in degrees a second. SMALLER = SLOWER.                        (60)
  CLAW_STEPS_PER_S   position commands a second while it moves. More = finer steps.                        (40)
"""
from __future__ import annotations

import json
import os

STAND_STEPS = 8
STAND_SPEED = 20
STAND_SPEED_MID = 0
STAND_SLOW_STAGES = 2
STAND_PAUSE = 0
STAND_WAIT_S = 2.6

CLAW_DEG_S = 60.0
CLAW_STEPS_PER_S = 40

_OVERRIDE = "~/.local/share/g2/motion_feel.json"


def _override() -> dict:
    try:
        with open(os.path.expanduser(os.environ.get("G2_MOTION_FEEL", _OVERRIDE))) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def get(name: str) -> float:
    """The value of a setting: the environment (G2_<NAME>), else the override file, else the number in this file. A value that is not a number falls through to the next."""
    for raw in (os.environ.get("G2_" + name), _override().get(name), globals().get(name)):
        try:
            if raw is not None and str(raw).strip() != "":
                return float(raw)
        except (TypeError, ValueError):
            continue
    return float(globals()[name])
