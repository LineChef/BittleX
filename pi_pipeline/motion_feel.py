"""HOW G2'S SLOW MOVES FEEL: the numbers you can change (owner, 2026-11-08: "show me the file where I can modify these settings myself").

Edit the numbers below and have them deployed (`g2deploy`, or ask), or, to try a value on the robot WITHOUT a deploy, write only the ones you want to change into
`~/.local/share/g2/motion_feel.json` on the Pi, for example {"STAND_SPEED": 18, "CLAW_DEG_S": 45}. That file wins over this one and survives deploys. The stand-up numbers are read at every stand-up; the claw numbers when the program starts (the voice service or a goal run), so restart it after changing those.
An environment variable of the same name with G2_ in front (G2_STAND_SPEED=18) wins over both, for one run.
"""
from __future__ import annotations

import json
import os

# ---- THE STAND-UP (the ONLY stand-up on the arm build, from rest, sit, the attention pose or any pose the board reports: owner, 2026-11-08, a hard rule; played by the board as one `K` skill,
# pi_pipeline/link/kskill.py; 10 of 10 stood, roll within 2 deg). There is no switch to turn it off.
STAND_GYRO = 1             # 1 = the gyro balance is ON while the board plays the rise and off right after (never left on in the attention / sit poses). 0 = off throughout.
STAND_STEPS = 8            # how many stages the rise is cut into. More = smoother but each stage takes time.
STAND_SPEED = 12           # how fast each stage moves, at the first and last stages. The firmware's speed is this number / 8, so BIGGER = FASTER (24 uniform was "a bit snappy", 20 "still too fast", 14 uniform leaned more).
STAND_SPEED_MID = 20       # a faster speed for the stages in the MIDDLE of the rise (0 = no, every stage at STAND_SPEED). The half-up pose is where he tips, so: slow at the start and end, fast through the middle.
STAND_SLOW_STAGES = 2      # how many stages at the start and at the end stay at the slow STAND_SPEED when STAND_SPEED_MID is set.
STAND_PAUSE = 0            # a pause after each stage, in 50 ms units. 0 = none. Any pause makes it stop-and-go.
STAND_WAIT_S = 3.4         # how long the Pi waits for the rise to finish before the next command. Lower the speed, raise this.

# ---- THE STAND-UP OUT OF THE ATTENTION POSE: its own, slightly slower numbers (owner, 2026-11-08: "standups out of the attention position were getting close to falling"); the rest stand-up above is unchanged.
STAND_ATT_SPEED = 10       # slow speed at the first and last stages (the same idea as STAND_SPEED; the rest stand-up uses 12).
STAND_ATT_SPEED_MID = 22   # the faster middle stages (the rest stand-up uses STAND_SPEED_MID).
STAND_ATT_FRONT_START = 0.2    # when the front legs start to rise, as a fraction of the stand-up's time, for a stand-up out of the attention pose when STAND_ATT_VIA_REST is 0 (the same as the stand-up from rest). Making the back legs lead more tipped him further back on 2026-11-12 (45/65: pitch -34 to -38; 50/50 with a pause: -71).
STAND_ATT_REAR_END = 0.7       # when the back legs are done rising, as a fraction of the time (the same as the stand-up from rest).
STAND_ATT_REAR_HOLD = 0        # a pause after the stage in which the back legs arrive, in 50 ms units. 0 = none.
STAND_ATT_VIA_REST = 1         # 1 = a stand-up out of the attention pose first lies down in the rest position and then plays the normal stand-up from rest (owner, 2026-11-12: every stand-up out of the attention pose after a claw look fell over backwards; the stand-up from rest was level every time). 0 = the K stand-up straight out of the attention pose.
STAND_ATT_WAIT_S = 4.0     # the longest the Pi waits for the board to finish (it stops waiting as soon as the legs read as up).

# ---- THE CLAW LOOK (owner, 2026-11-13: one standard move, the ball chase's, that every mode calls: ball_chase.claw_look_sequence). In this order: he stands first, goes into the attention pose and settles
# (CLAW_POSE_S, 2 s, in ball_chase.py), the claw is raised straight up, swings to the left (settle, picture), to the right (settle, picture), back to the centre (settle, picture), the claw is lowered and
# he stands up (the STAND_* numbers above; out of the attention pose he lies down in rest first, STAND_ATT_VIA_REST). A number changed here changes the look in every mode.
# 1 the move into the attention pose (the eased skill; the look waits CLAW_POSE_S after it)
ATT_ENTRY_EASED = 1        # 1 = the move into the attention pose is an eased K skill. 0 = the firmware `kcalib`, which moves every joint at once at full speed (he "sat hard into the attention position").
ATT_ENTRY_STEPS = 6        # how many stages the move is cut into. More = smoother but longer.
ATT_ENTRY_SPEED = 10       # how fast each stage moves. BIGGER = faster. 10 is gentle.
ATT_ENTRY_WAIT_S = 7.0     # the longest the Pi waits for the legs to read as in the attention pose (3 s was too short: the wait ended with the move still playing).
ATT_ENTRY_SILENT_WAIT_S = 3.0  # the wait for the attention pose when the board does not answer pose reads (the move normally takes 2 to 5 s): no waiting out ATT_ENTRY_WAIT_S for a reply that never comes.

# 2 to 4 the claw raise and the swings (the arm's two servos are sent a new position this many times a second)
CLAW_DEG_S = 60.0          # how fast the claw moves, in degrees a second. SMALLER = SLOWER.
CLAW_STEPS_PER_S = 100     # position commands a second while the claw moves. More = finer steps (of 60/40, 40/40, 60/100 and 30/60 the owner picked 60 deg/s at 100 a second as smoothest, 2026-11-08).
# (the pan and lift angles, the settle before each picture CLAW_SETTLE_S 0.8 s and the attention-pose settle CLAW_POSE_S 2 s are at the top of ball_chase.py)

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
