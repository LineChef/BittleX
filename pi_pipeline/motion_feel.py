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

# ---- THE CLAW LOOK (owner, 2026-11-12). The look is: the move into the attention pose, the claw raised, a swing left, a swing right, back to the centre with a picture at each, then G2 lies down in the rest
# position (legs and claw together, one eased skill) and stands up from rest (the STAND_* numbers above). By default these are separate moves with the waits they always had (LOOK_ONE_SKILL = 0).
# LOOK_ONE_SKILL = 1 tries the same look as ONE `K` message the board plays by itself with no pause between the parts; the Pi then takes the pictures at times it works out from the frames. It ran three times in a
# drill without a fall, then fell 5 s into its first roam look (2026-11-12) and its timing was not right, so it is off. A speed here is the firmware's speed x 8: BIGGER = FASTER (and harder on the servos).
LOOK_ONE_SKILL = 0         # 0 = the separate moves with their waits (the default). 1 = the look as one skill with no pause between the parts (the LOOK_* numbers below then apply).

# 1 the move into the attention pose
ATT_ENTRY_EASED = 1        # 1 = the move into the attention pose is an eased K skill. 0 = the firmware `kcalib`, which moves every joint at once at full speed (he "sat hard into the attention position").
ATT_ENTRY_STEPS = 6        # how many stages the move is cut into. More = smoother but longer.
ATT_ENTRY_SPEED = 10       # how fast each stage moves. BIGGER = faster. 10 is gentle.

# 2 to 5 the claw raise, the swings and the holds (LOOK_ONE_SKILL = 1 only)
LOOK_RAISE_STEPS = 4       # stages of the claw raise (the lift servo from its walking value up to the look's lift, 120). More = smoother and slower.
LOOK_PAN_STEPS = 2         # stages of a swing from the centre to one side (the swing across to the other side uses twice as many). More = smoother and slower.
LOOK_CLAW_SPEED = 10       # how fast the claw moves in the raise and the swings. BIGGER = faster. The arm is heavy: too fast shakes the body.
LOOK_HOLD_S = 2.0          # how long the claw holds still at each of the three picture poses, in seconds. The claw camera's pictures are about a second old, so under about 1.5 s the picture shows the claw still moving.
LOOK_PIC_AT_S = 1.1        # how many seconds into a hold the picture is asked for. About 1 s of delay in the camera plus the time the claw takes to stop: raise it if the pictures show the previous pose, never past LOOK_HOLD_S.

# 6 the lie-down at the end (legs and claw together, so the claw comes down smoothly instead of snapping)
LIE_STEPS = 6              # stages of the lie-down. More = smoother and slower.
LIE_SPEED = 12             # how fast each stage moves. BIGGER = faster.

# The pictures are timed from an estimate of how long the board takes; nothing else depends on it (LOOK_ONE_SKILL = 1 only).
LOOK_STEP_S = 0.024        # seconds the board takes for one step of a move (a frame of D degrees at speed S takes D / (S / 8) steps). Fitted to a stand-up from rest that reads as done after about 2 s. SMALLER if the whole look ends sooner than the Pi waits (G2 stands idle at the end), BIGGER if the pictures come too early.

# Only when LOOK_ONE_SKILL = 0, or the board does not answer pose reads (the Pi then waits only the time a move normally takes, so nothing waits for a reply that never comes):
ATT_ENTRY_WAIT_S = 7.0     # the longest the Pi waits for the legs to read as in the attention pose (3 s was too short: the wait ended with the move still playing).
ATT_ENTRY_SILENT_WAIT_S = 3.0  # the wait for the attention pose when the board does not answer reads (the move normally takes 2 to 5 s).
LIE_WAIT_S = 4.0           # the longest the Pi waits for the legs to read as rest after a lie-down played by the Pi.
LIE_SILENT_WAIT_S = 2.5    # the wait for the lie-down when the board does not answer reads (the move normally takes 2 to 3 s).
CLAW_DEG_S = 60.0          # (LOOK_ONE_SKILL = 0 only) how fast the claw moves, in degrees a second. SMALLER = SLOWER.
CLAW_STEPS_PER_S = 100     # (LOOK_ONE_SKILL = 0 only) position commands a second while the claw moves. More = finer steps (of 60/40, 40/40, 60/100 and 30/60 the owner picked 60 deg/s at 100 a second as smoothest, 2026-11-08).

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
