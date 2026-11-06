"""Chase the treat ball and punt it for the cat (user, 2026-10-25). Stop, look, step: a picture, one short move, a picture again, until someone says stop.

G2 cannot grab the 3 in ball (the claw opens to about 2.75 in); the punch (the lunge with the claw shut) throws it straight ahead, which is what the cat game needs. The loop:

  SEARCH   no ball in the picture: the search order (SEARCH_ORDER): claw looks (the arm points the camera, the legs stay), turn steps toward the side it was last seen on, back-ups
           (BACK_BUDGET_S caps them per attempt); a short walk after a full circle only with SEARCH_WALK (a big floor)
  TURN     the ball is more than 12 deg off straight: turn toward it
  WALK     it is straight ahead but farther than 7 in (measured from the camera): walk up to it, never more than 3 s at a time: look again
  ALIGN    within 7 in but more than PUNT_ALIGN_DEG off straight: a small turn pulse, a new picture, up to ALIGN_TRIES (user, 2026-10-31)
  PUNT     close and lined up: punch (never backs up for being too close); then look where it went, and step closer if it is still more than 4 in away
  BACK UP  it is still where it was after STUCK_PUNTS punts: back up, then line it up again

Pure logic in `ChasePlanner` (a reading in, an `Action` out) so it runs against a recorded picture series; `run_chase` is the loop around it with a robot, a camera, a stop flag and a picture saver
(every picture with the ball found goes to the training set, at most one per 2 s: user, 2026-10-25). Walks are always the learned default gait policy (user, 2026-10-31); turns and back-ups
are Petoi's firmware skills (`kwkL` / `kwkR`, `kbkF`), the link turns the gyro assist back off after each (fall recovery is off for the arm). Each walk and turn is timed from the pace and
turn rates G2 measures himself (behavior/chase_pace.py). The goals framework (pi_pipeline/goals) runs this as one attempt and tunes its settings between attempts.

    python -m pi_pipeline.behavior.ball_chase            # on the Pi, voice service stopped, G2 standing; Ctrl-C or `touch ~/.local/share/g2/ball_chase_stop` ends it
    python -m pi_pipeline.behavior.ball_chase --dry-run  # looks and says what it would do; sends no move
"""
from __future__ import annotations

import dataclasses
import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from ..vision.ball_finder import BallReading, find_ball

log = logging.getLogger("g2.ball_chase")

# The walking pace and the turn rates are measured by G2 himself (behavior/chase_pace.py; its defaults: Petoi's arm turn 30 deg in 4.8 s, 2026-10-25, the policy walk 4.2 in a second)
ALIGN_DEG = 12.0               # farther off straight than this: turn before walking
PUNT_ALIGN_DEG = 12.0          # ... and before a punt
PUNT_MIN_IN, PUNT_MAX_IN = 0.0, 4.0      # camera to ball: the lunge reaches about this far (2.6 in threw the ball 18 in; 4.5 to 5 in was just out of reach, 2026-10-25)
NUDGE_MAX_IN = 7.0             # between PUNT_MAX_IN and this: small steps closer, then punt anyway after NUDGES_BEFORE_PUNT of them
NUDGE_S = 0.9
NUDGE_GAIT = "scripted"      # how the small steps closer are walked (user, 2026-11-04): "scripted" = Petoi's own forward walk (kwkF) for NUDGE_S, which is steadier than the learned policy for dialing in the distance; "policy" = the learned gait
WALK_AIM_IN = 4.0              # a walk step is timed to leave the ball about this far from the camera (the ball is touched at about 3 in)
NUDGES_BEFORE_PUNT = 3      # camera to ball, measured 2026-10-25: the ball at 2.6 in is a good punt (the claw hits it first and it goes straight ahead); at 4.5 in it is too far to be hit
WALK_MAX_S = 3.0               # one walk step: then look again
SEARCH_STEP_DEG = 20.0          # (was 35: a wrong turn away from a ball that was only missed once cost 6 s and the ball)
SEARCH_WALK = False            # walk on blind after a full circle without the ball (off: only on a big floor, `--search-walk`)
AFTER_PUNT_SETTLE_S = 1.0      # after the punch, before the picture that says where the ball went
LOST_LOOKS = 3                 # real misses in a row before searching starts; a missing picture is not a miss
SEARCH_STEPS_PER_CIRCLE = 10
MAX_TURN_DEG = 20.0             # the most one turn toward the ball turns him (user, 2026-11-01: turns smaller in general; it was 35: a 31 deg turn took 5 s)
CHASE_WALL_TURN_MAX_DEG = 30.0  # the most a wall turn in the chase turns him (the exploration keeps its own: it was 52 deg, 8.6 s)
MIN_MOVE_S = 1.2               # a gait started and stopped for less than this does not move him
CLOSE_IN_IN = 4.0              # after a punt that left the ball farther than this, step closer before the next one (2026-10-25: a punt from 4.5 to 7 in was too far, from 2.6 in it threw the ball 18 in)
STUCK_PUNTS = 3                # punts with the ball still in range before backing up
BACK_UP_S = 1.0
SAVE_EVERY_S = 2.0
BACK_BUDGET_S = 3.0            # the most backing up in one attempt (search moves, stuck punts and a vanished ball together): there is no edge detector, so keep it small on a desk (0 = never back up)
WHEN_VANISHED = "punt"         # the ball vanished at close range: "punt" (it is at the claw) or "back_up" (back off a little and look again)
VANISH_BACK_S = 1.0

# Searching (goals plan, 2026-10-31): a search is a list of moves. The "once" moves play first, then the "cycle" moves repeat until the ball is seen. Moves: "claw" (look around with the
# arm: the camera is on the claw), "turn" (a turn step in place), "back" (back up to see more floor). Without the claw (a robot that cannot move it) "claw" is left out.
SEARCH_ORDERS = {
    "turn": ((), ("turn",)),
    "claw_then_turn": (("claw",), ("turn",)),
    "claw_scan": (("claw",), ("turn", "claw")),
    "back_claw_scan": (("back", "claw"), ("turn", "claw")),
    "claw_back_scan": (("claw", "back", "claw"), ("turn", "claw")),
    "back_turn": (("back",), ("turn",)),
    "back_and_turn": ((), ("back", "turn")),
    "three_point_turn": ((), ("three_point",)),                  # 3-point turn steps (user, 2026-11-01): back up while turning, then forward turning the other way
    "claw_three_point": (("claw",), ("three_point", "claw")),
    "full_circle": ((), ("circle",)),                            # a full-circle scan (user, 2026-11-02): turn steps that add up to one whole turn, counted; after each whole turn without the ball he backs up for a wider view
    "claw_full_circle": (("claw",), ("circle", "claw")),         # the same with a claw look between the turn steps
    "turn_180": ((), ("u_turn",)),                               # (user, 2026-11-03) search by turning half way round (U_TURN_DEG) in one go, look, and again: the ball behind him is found in one move
    "claw_turn_180": (("claw",), ("u_turn", "claw")),            # a claw look, then a half turn, a claw look, a half turn ...
}
U_TURN_DEG = 180.0             # the half turn of the "u_turn" search move
SEARCH_ORDER = "claw_scan"     # the claw look first: it sees the most for the least moving (user, 2026-10-31)
# The 3-point turn (user, 2026-11-01): back up while turning one way, then walk forward while turning the OPPOSITE way (as a car does), so he comes round in less room than a spot turn
# (a wall close ahead, or a search turn near things). Wall turns use it (user, 2026-11-01: the hardware test works); search turns use it when SEARCH_ORDER is three_point_turn or claw_three_point, which the goal can try.
THREE_POINT_BACK_S = 1.2       # the backing-up half
THREE_POINT_BACK_TOKEN = {"right": "kbkR", "left": "kbkL"}      # the firmware's backward-turning gaits; which way each rotates the body is what the test measures
NO_WALL_TURN_BALL_IN = 12.0    # the ball this close: a wall reading never turns him away (no 3-point turn, no plain turn), it only stops him walking closer (user, 2026-11-01:
                               # the false wall readings come with the ball close, low in the picture, and a big turn there loses the ball or runs into it)
WALL_THREE_POINT = True        # a wall ahead: a 3-point turn instead of a plain turn away (needs room to back up); works on G2 (user, 2026-11-01)
SEARCH_THREE_POINT = False     # a search turn step is a 3-point turn
SEARCH_MOVE_MAX_S = 2.0        # the longest search turn before the next picture (user, 2026-11-01: a few steps, then look again)
SCAN_TURN_DEG = 30.0           # a turn step between two claw looks (a claw look covers about 2 x CLAW_PAN_DEG plus the camera's own view)

# The claw look: the arm's pan (joint 0) and lift (joint 1) point the camera; legs stay where they are. A positive lift swings the claw forward, out and up.
CLAW_PAN_DEG = 35.0
CLAW_LIFT_DEG = 120.0         # (user, 2026-11-03) the look: attention pose, raise the claw to this (120 deg: +30 was seen to go up, 120 is near the top of the lift servo), pan left, picture, pan right, picture, centre, picture, lower, stand up
CLAW_RAISE_DEG = None          # the first move of a look from the attention pose: straight up this far; None = CLAW_LIFT_DEG (40 deg tipped him nose down from the attention pose twice on 2026-11-03, BEFORE it was known that positive lift is up and that the legs were straight: check he holds before trusting a high raise)
CLAW_RAISE_FIRST = True        # (user, 2026-11-02) from the attention pose the claw sits between the front legs and cannot pan there: raise it straight up first (lift CLAW_LIFT_DEG, pan 0), then
                               # pan left, picture, pan right, picture, back to the centre still raised, and lower it last
CLAW_LIFT_MAX_DEG = 120.0     # the most claw_pose will ask of the lift servo (the Pi's own limit for joint angles; the firmware takes up to 127)
CLAW_PAN_SIGN = "left"         # which way a positive arm pan turns the camera: LEFT on G2 (2026-11-01, pictures taken 1.3 s after each move: pan +35 put the ball 73 px to the right = camera 35 deg left, pan -35 about 39 deg right; the user saw the claw swing left); claw_look --calibrate can re-measure it
CLAW_DEG_S = 60.0              # how fast the arm moves for a look (below the 80 deg/s cap on eased moves)
CLAW_STEPS_PER_S = 40
CLAW_LOOK_POSE = "kcalib"      # the pose he holds for the claw look (user, 2026-11-01): the BiBoard's "attention" pose, the one the legs are calibrated in; "ksit" is the sit it replaced. He stands up normally afterwards (`kbalance`)
CLAW_FROM_SIT = True           # the claw look is done from a sit: sit, swing the arm left, picture, swing right, picture, arm back to centre, stand up slowly with the back legs (user, 2026-11-01)
CLAW_POSE_S = 2.0              # to settle into the attention pose
CLAW_LOOK_STANDING = False     # (user, 2026-11-03: tried standing, reverted the same day: the attention pose prevents most of the servo sag) True = the claw look is taken STANDING: no attention pose (CLAW_LOOK_POSE) and no stand-up afterwards; the arm pans over the standing legs. False = the
                               # old look from the attention pose. Not used with BETWEEN_MOVES "attention" (that flow waits in the attention pose by design).
SIT_STAND_FIRST_S = 2.5        # the stand-up before the sit of a claw look
BETWEEN_MOVES = "stand"        # the switch (user, 2026-11-02; the punt setting / goal knob `between_moves`): "stand", the original flow (the default: fluid, and the legs only let go after
                               # 7 to 10 s of standing still), or "attention":
                               # he never waits standing: after every move he goes into the attention pose (CLAW_LOOK_POSE, legs straight) and takes the straight-ahead
                               # picture there, once settled; only when the decision is a move does he stand up (back legs first, the link's stand_from_attention), and the move starts at once.
                               # The ball distance comes from its size, so it reads the same in either pose; the wall reading was calibrated on STANDING pictures and may read off from this
                               # pose until a wall calibration is taken in it. The legs went slack after 7 to 10 s of standing still (docs/STATUS.md open problem 14).
# Close to the ball (within the nudge range, NUDGE_MAX_IN / PUNT_MAX_IN as the goal set them for this attempt, at the look before the move) he is dialing in: nudges, line-up turns,
# a step closer after a punt. He stays standing between those small steps instead of going into the attention pose at each stop (user, 2026-11-02): `_dialing_in`.
SAG_CHECK_AFTER_S = 5.0        # (user, 2026-11-05) standing this long since the last move ended: before the next move the IMU tilt is checked for sagging legs, and if they have sagged he goes
                               # into the attention pose and stands up again (back legs first) before moving. Always on, in every flow (the standing flow included)
POSE_GATE = os.environ.get("G2_POSE_GATE", "1").strip().lower() not in ("0", "off", "false", "no")      # (user, 2026-11-06; UNPROVEN until the hardware A/B) before a walk or turn that follows a pose change, read the body's real state from the IMU and re-seat the legs if they lag
GATE_TILT_S = 0.25             # each of the two tilt readings the gate takes
GATE_DRIFT_DEG = 2.0           # the two readings differ by more than this: the legs are still settling, not yet a stance to move from
GATE_RESEATS = 2               # re-seats (attention pose and up) tried before going anyway
STOP_CALM = os.environ.get("G2_STOP_CALM", "1").strip().lower() not in ("0", "off", "false", "no")        # (UNPROVEN) a firmware move is ended on a calm moment, not at an arbitrary gait phase
CALM_MAX_S = 0.4               # the longest the stop waits for it
CALM_TILT_DEG = 4.0            # calm: the body within this of how it stands (the reference stand tilt, else level) ...
CALM_STEP_DEG = 1.5            # ... and the tilt moving less than this between samples
QUICK_MOVE_S = 3.0             # a move this soon after the last one ended goes without the pose read and the tilt check (he is standing as the last move left him): no added stillness
STILL_SAY_S = 4.0              # stood still longer than this before a move: said in the log (the still time of every move is in the trace)
ATTENTION_SETTLE_S = 1.0       # into the attention pose before anything else is sent
STAND_UP_WATCH_S = 1.0         # the stand-up out of the attention pose, watched for a fall
CLAW_SETTLE_S = 0.8            # after the arm move and before the picture: the arm and body settle; the old camera frame is dropped by _SnapshotCamera.look (the module answers with the previous request's picture, 2026-11-01)

# The walk is the learned default gait policy (the attachment's saved gait: ARM1X with the arm) (user, 2026-10-31); only the dialing-in steps close to the ball use Petoi's scripted walk instead (NUDGE_GAIT, user, 2026-11-04). Its pace and the turn rates are measured by
# G2 himself from the camera (behavior/chase_pace.py) and used to time each move; the defaults there stand in until he has measured them.
BACK_IN_S = 3.0                # a guess at the firmware back-up's pace (not measured: there is no reading before a back-up after a punt)

# Walls while chasing (the "turn away from walls" standing goal ranks above the punt: user, 2026-10-31). With a wall check (run_chase's `wall_check`: the camera's wall reading
# as it is, calibrated or not): he never walks closer than CHASE_WALL_IN to a wall, turns away when he is that close, and leaves a ball lying nearer the wall than
# CHASE_WALL_IN - BALL_TOUCH_IN alone (the attempt ends "ball_by_wall" after WALL_GIVE_UP looks agree). CHASE_WALL_IN is learned by the walls goal (goals/walls.py, never below 4 in).
CHASE_WALL_IN = 10.0
BALL_TOUCH_IN = 3.0            # he punches about this far from the ball
WALL_GIVE_UP = 2


@dataclass(frozen=True)
class WallSeen:
    nearest_in: float | None      # the nearest wall base ahead, inches (the ball's own columns left out)
    turn: str | None              # "left" / "right": the side with more room
    near_ball_in: float | None = None     # the nearest wall base in the columns right beside the ball (is the ball against a wall?); None: no ball, or nothing there
    # (a side wall elsewhere in the picture does not make a ball "by the wall")


WALL_MIN_READING_IN = 8.5      # the wall calibration's closest row (8 in): a reading at it says "8 in or nearer", and on the claw camera it came back almost every look (2026-11-01)
WALL_STUCK_LOOKS = 3           # this many looks in a row at that reading and the reading is not believed
WALL_BALL_CONE_DEG = 50.0      # a ball seen this close to straight ahead is seen THROUGH the space a wall would fill (user, 2026-11-01: was 35; a ball at +45 deg let a false 8 in wall turn him, and he fell)


def vet_wall(wall: "WallSeen | None", ball: BallReading | None, state: dict) -> tuple["WallSeen | None", str]:
    """Believe the wall reading only when it makes sense (user, 2026-11-01: he turned away from a ball right in front of him, three times in one run, and fell during one of the turns).
    Returns (the wall to use or None, why it was dropped or ""). Dropped when
      - a ball is in view within WALL_BALL_CONE_DEG (50) of straight ahead, the wall reads the closest row (the one that came back all the time) and the ball is more than 2 in beyond it:
        a wall that near, dead ahead, would hide the ball (a nearer side wall at a real distance is still believed);
      - the reading has sat at the calibration's closest row for WALL_STUCK_LOOKS looks in a row (state["stuck"] counts them; any other reading resets it).
    A bump (the IMU contact signal) still stops him whatever the camera says."""
    if wall is None or wall.nearest_in is None:
        state["stuck"] = 0
        return wall, ""
    state["stuck"] = state.get("stuck", 0) + 1 if wall.nearest_in <= WALL_MIN_READING_IN else 0
    if ball is not None and abs(ball.bearing_deg) <= WALL_BALL_CONE_DEG and wall.nearest_in <= WALL_MIN_READING_IN and wall.nearest_in + 2.0 < ball.distance_in:
        return WallSeen(None, wall.turn, None), f"a wall {wall.nearest_in:.0f} in ahead would hide the ball I see {ball.distance_in:.0f} in away"
    if state["stuck"] >= WALL_STUCK_LOOKS:
        return WallSeen(None, wall.turn, None), f"the wall reading has said {wall.nearest_in:.0f} in for {state['stuck']} looks in a row"
    return wall, ""


# A ball against a wall (owner, 2026-11-02): instead of leaving it, he steps WALL_SIDESTEP_IN sideways toward the side with more room (turn 90, walk, turn back), so the normal chase sees the ball
# at an angle and the punch banks off the wall and away (a punch straight into a wall comes straight back at him). Up to WALL_SIDESTEP_TRIES sidesteps an attempt, alternating sides after the
# first; 0 = leave the ball as before. Near a ball he may come to WALL_FLOOR_IN of a wall (the owner's floor, 5 in; the claw sticks out ahead of the body).
WALL_SIDESTEP_IN = 7.0
WALL_SIDESTEP_DEG = 25.0       # the turn toward the side with more room: enough to make the punch oblique; a 90 deg turn costs 15 s at G2's long-turn rate (about 6 deg/s) and used up the attempt (sim, 2026-11-02)
WALL_SIDESTEP_BALL_IN = 14.0   # only once the ball is this close: farther away he just walks on toward it
WALL_SIDESTEP_TRIES = 3
WALL_FLOOR_IN = 5.0
WALL_TURNS_GIVE_UP = 3         # turns away from walls with the ball in sight in one attempt before he leaves it (the ball sits where walls keep him from it)


def wall_turn_deg() -> float:
    """How far to turn away from a wall: the walls goal's `wall_turn_deg` (BehaviorDriver.WALL_TURN_RAD)."""
    try:
        from .driver import BehaviorDriver
        return math.degrees(BehaviorDriver.WALL_TURN_RAD)
    except Exception:  # noqa: BLE001
        return 50.0


# Fine alignment before the punch (user, 2026-10-31: small turns, checked with the camera after each one). Inside NUDGE_MAX_IN, a ball more than PUNT_ALIGN_DEG off straight gets a
# short turn pulse sized from his measured pulse turn rate, then a new picture; at most ALIGN_TRIES of them, then WHEN_MISALIGNED.
ALIGN_PULSE_MIN_S = 1.0        # the shortest pulse (shorter ones may not move him at all: the measured log shows it)
ALIGN_PULSE_MAX_S = 1.2        # (user, 2026-11-03: he over-turned; was 1.6)
ALIGN_GAIN = 0.4               # a line-up pulse turns only this share of the bearing: the pulse rate is a guess and an overshoot loses a ball 3 in away (user, 2026-11-03: smaller steps near the ball; 0.6 -> 0.4 on 2026-11-05: still overshooting)
SEARCH_SIDE_DEADBAND_DEG = 6.0 # a ball last seen less than this far off straight tells nothing about which way it went: the search side is chosen by chance
ALIGN_MAX_DEG = 6.0            # (user, 2026-11-03: still turning too much) one line-up pulse is sized to turn at most this many degrees, whatever the bearing; more pulses do the rest (ALIGN_TRIES)
ALIGN_MIN_DEG = 3.0            # the smallest line-up turn asked for (gyro-stopped turns, 2026-11-05)
ALIGN_STOP_LEAD_DEG = 1.5      # the gyro stop sends `kbalance` this many degrees early: the body keeps turning a moment after it
ALIGN_CAP_S = 2.5              # a gyro-stopped turn never runs longer than this (or twice its timed length), however slowly the yaw changes
ALIGN_CLOSE_IN = 5.0           # closer than this (camera to ball) the pulse is smaller still
ALIGN_CLOSE_GAIN = 0.7         # ... times this
ALIGN_TRIES = 4
WHEN_MISALIGNED = "punch"      # after ALIGN_TRIES pulses and still off: "punch" anyway or "back_up" and line up again


# How far the camera really turns for each side of the pan, as a share of the pan. Measured 2026-11-01 with the old frame dropped (ball 12 in ahead): pan +35 moved it 79 px right, pan -35 77 px left
# (the finder's 2.1 px per degree: 35 to 38 deg of camera), so about 1.0 on both sides. Earlier readings of "pan +35 barely turns" were the module's previous-request frame.
CLAW_PAN_SHARE = {"right": 1.0, "left": 1.0}


def claw_pan_body(pan: float) -> float:
    """The camera's direction, + = G2's right, for an arm pan of `pan` degrees: the commanded direction times the measured share for that side."""
    deg = pan if CLAW_PAN_SIGN == "right" else -pan
    return deg * CLAW_PAN_SHARE["right" if deg > 0 else "left"]
# The punch (user, 2026-10-25: "test the punch, not attempting to pick it up with the claw"): the lunge of Petoi's `pickF` (decoded from InstinctBittleESP.h: a crouch, then front legs folded and the arm swung out to 75)
# with the claw held CLOSED the whole time; `kpickF` opens the claw to 65 first and closes it on the way back, which is a grab attempt. Key poses are the skill's own angles (the arm firmware shifts the front
# shoulders -10 and front knees +6 for a skill with no Arm variant, added below); (seconds to get there, arm lift, shoulders FL FR BR BL, knees FL FR BR BL).
PUNCH_READY_S, PUNCH_CROUCH_S, PUNCH_LUNGE_S, PUNCH_HOLD_S = 0.50, 0.45, 0.12, 0.25      # seconds to get to each key pose (punt_settings.json: punch_lunge_s, punch_hold_s)


def punch_keys():
    """The punch's key poses with the current times: (seconds to get there, arm lift, shoulders FL FR BR BL, knees FL FR BR BL)."""
    return (
        (PUNCH_READY_S, -10, (16, 16, 30, 30), (30, 30, 30, 30)),      # get ready (pickF frame 0, the claw stays shut)
        (PUNCH_CROUCH_S, 10, (5, 5, 10, 10), (20, 20, 50, 50)),        # crouch (frame 2)
        (PUNCH_LUNGE_S, 75, (53, 53, 40, 40), (-28, -28, 35, 35)),     # the lunge: front legs fold forward, the arm swings out (frame 3)
        (PUNCH_HOLD_S, 75, (53, 53, 40, 40), (-28, -28, 35, 35)),      # hold it (the claw is not closed on anything: it is already closed)
    )


PUNCH_KEYS = punch_keys()
PUNCH_STEPS_PER_S = 40
PUNT_MIN_SWING_DEG = 6.0       # a real kpickF swings the pitch 15 to 20 deg
STOP_FILE = "~/.local/share/g2/ball_chase_stop"


@dataclass(frozen=True)
class Action:
    kind: str                  # "turn" | "align" | "walk" | "punt" | "back" | "look" | "search_turn" | "search_walk" | "search_back" | "claw_look"
    seconds: float = 0.0
    degrees: float = 0.0       # + = right, - = left
    why: str = ""
    degrees2: float = 0.0      # a sidestep's closing turn: from the heading after the step to facing the ball again (so he does not lose it: the camera sees about 47 deg either side)
    scripted: bool = False     # a walk: Petoi's scripted walk (kwkF) instead of the learned policy (the dialing-in steps, NUDGE_GAIT)
    stop_deg: float = 0.0      # a line-up turn: stop on the gyro once he has turned this many degrees (`seconds` is then only the fallback when no IMU frames arrive)


@dataclass
class ChasePlanner:
    last_side: int = 0         # +1 the ball was last seen to the right, -1 to the left, 0 never
    lost: int = 0              # looks in a row without the ball
    search_steps: int = 0
    punts_in_range: int = 0
    after_punt: bool = False   # the last action was a punt
    nudges: int = 0            # small steps closer taken since the ball was last far or in reach
    last_dist: float | None = None   # how far the ball was when it was last seen (None once acted on)
    considered: list = field(default_factory=list)   # options he looked at and passed over for this decision, with why (decision log; the loop clears it before each decision)
    sidesteps: int = 0         # sideways steps taken this attempt to get a ball off a wall
    punt_log: list = field(default_factory=list)   # (distance in, bearing deg) of the ball at each punt the planner asked for (None: it had vanished at close range)
    walk_log: list = field(default_factory=list)   # (distance in, seconds) of each walk step
    log: list = field(default_factory=list)
    claw_ok: bool = True       # the robot can move the arm for a claw look (run_chase sets it from the robot)
    align_before: float | None = None   # the ball's bearing when the last align turn was chosen: a swing to the other side afterwards is an overshoot
    turn_before: float | None = None   # the ball's bearing when the last approach turn toward it was chosen: a swing to the other side afterwards is an overshoot (user, 2026-11-05)
    prev_kind: str | None = None   # the kind of the last action he carried out (run_chase sets it): a ball gone after a small step forward means he pushed it
    seen_ball: bool = False    # the ball has been seen this attempt: from then on only straight pictures, never a claw look (user, 2026-11-01)
    search_i: int = 0          # moves into the current search
    circle_deg: float = 0.0    # degrees turned in the current full-circle scan
    circles: int = 0           # whole turns finished without the ball this search
    back_s: float = 0.0        # seconds backed up this attempt (BACK_BUDGET_S caps it)
    claw_side: int = 0         # which side the claw look starts on (the side the ball was last seen)
    last_bearing: float | None = None   # the ball's bearing when it was last seen (None: not this attempt)
    last_edge: bool = False    # ... and whether it touched the picture's edge (it was leaving the view that way)
    search_side: int = 0       # the side this search turns toward, chosen when it starts (0 = not chosen); cleared when the ball is seen again
    rng: object = field(default_factory=random.Random)   # the coin for a search with no hint (tests seed it)
    align_turns: int = 0       # fine-alignment pulses since the ball came within NUDGE_MAX_IN
    by_wall: int = 0           # looks in a row with the ball too close to a wall
    wall_turns: int = 0        # turns away from walls this attempt while the ball was in sight
    pace: object = None        # a chase_pace.PaceBook (None: its defaults)

    def _walk_pace(self) -> float:
        if self.pace is not None:
            return self.pace.walk_in_s()
        from .chase_pace import DEFAULTS
        return DEFAULTS["walk_in_s"]

    def _turn_rate(self, side: int, short: bool) -> float:
        if self.pace is not None:
            return self.pace.turn_deg_s(side, short)
        from .chase_pace import DEFAULTS
        return DEFAULTS["pulse_deg_s" if short else "turn_deg_s"]

    def _order(self) -> tuple[tuple, tuple]:
        once, cycle = SEARCH_ORDERS.get(SEARCH_ORDER, SEARCH_ORDERS["turn"])
        if not self.claw_ok or self.seen_ball:
            once, cycle = tuple(m for m in once if m != "claw"), tuple(m for m in cycle if m != "claw")
        if SEARCH_THREE_POINT:
            cycle = tuple("three_point" if m == "turn" else m for m in cycle)
        return once, (cycle or ("turn",))

    def _can_back(self, seconds: float) -> bool:
        return self.back_s + seconds <= BACK_BUDGET_S + 1e-9

    def _back(self, kind: str, seconds: float, why: str) -> Action:
        self.back_s += seconds
        return Action(kind, seconds, why=why)

    def _search_side(self) -> int:
        """Which way a search turns (+1 right, -1 left), chosen once per search (user, 2026-11-03: it always went right). The first hint that applies: an overshoot hint (set when the ball
        vanished after a line-up turn: it is on the other side of that turn); the side the ball was last seen on when it was clearly to one side (more than SEARCH_SIDE_DEADBAND_DEG off
        straight, or touching the picture's edge); otherwise a coin flip (no information: before, a ball last seen near straight ahead, bearing 0 or more, always read as "right")."""
        if self.search_side:
            return self.search_side
        b = self.last_bearing
        if b is not None and (abs(b) >= SEARCH_SIDE_DEADBAND_DEG or (self.last_edge and b != 0)):
            self.search_side = 1 if b > 0 else -1
            self.considered.append(f"search side: {'right' if self.search_side > 0 else 'left'}, the ball was last seen {b:+.0f} deg off")
        else:
            self.search_side = self.rng.choice((-1, 1))
            self.considered.append(f"search side: {'right' if self.search_side > 0 else 'left'} by chance, the ball was last seen {'nowhere' if b is None else f'{b:+.0f} deg'} (no clear side)")
        return self.search_side

    def _search_move(self) -> Action:
        once, cycle = self._order()
        for _ in range(len(once) + 2 * len(cycle) + 1):                # a move that cannot be made (no back-up left) is skipped
            i = self.search_i
            self.search_i += 1
            move = once[i] if i < len(once) else cycle[(i - len(once)) % len(cycle)]
            side = self._search_side()
            if move == "claw":
                self.claw_side = side
                return Action("claw_look", why=f"searching: a look around with the claw, {'right' if side > 0 else 'left'} first")
            if move == "three_point":
                if self._can_back(THREE_POINT_BACK_S):
                    deg = SCAN_TURN_DEG * side
                    return self._three_point("three_point", deg, f"searching {'right' if side > 0 else 'left'}: a 3-point turn")
                self.considered.append("3-point turn: skipped, no back-up budget left; a plain turn step instead")
                move = "turn"                                                   # no room to back up left: a plain turn step
            if move == "back":
                if self._can_back(BACK_UP_S):
                    return self._back("search_back", BACK_UP_S, "searching: back up to see more of the floor")
                self.considered.append(f"back up: skipped, {self.back_s:.1f} of {BACK_BUDGET_S:.1f} s of back-up used")
                continue
            if move == "u_turn":
                rate = self._turn_rate(side, False)
                return Action("search_turn", U_TURN_DEG / rate, U_TURN_DEG * side, f"searching {'right' if side > 0 else 'left'}: a {U_TURN_DEG:.0f} degree turn to look behind him")      # not capped by SEARCH_MOVE_MAX_S: the whole half turn is the move
            if move == "circle" and self.circle_deg >= 360.0 - 1e-9:
                self.circle_deg = 0.0
                self.circles += 1
                if self._can_back(BACK_UP_S):
                    return self._back("search_back", BACK_UP_S, f"a full circle without the ball ({self.circles}): back up for a wider view")
                self.considered.append(f"full circle done ({self.circles}): no back-up left for a wider view, turning on")
            self.search_steps += 1
            step = SCAN_TURN_DEG if "claw" in cycle else SEARCH_STEP_DEG
            per_circle = max(1, int(math.ceil(360.0 / max(abs(step), 1.0)))) if "claw" in cycle else SEARCH_STEPS_PER_CIRCLE
            if SEARCH_WALK and self.search_steps > per_circle:
                self.search_steps = 0
                return Action("search_walk", 2.0, why="a full circle without the ball: walk on and search again")
            if self.search_steps > per_circle:
                self.search_steps = 1                          # a desk or any small surface: never walk blind, keep turning in place (user, 2026-10-25: "the desk isn't very long")
            rate = self._turn_rate(side, False)
            secs = min(abs(step) / rate, SEARCH_MOVE_MAX_S)              # a few steps, then look again (user, 2026-11-01: a 60 deg step at 6 deg/s was 10 s of turning)
            if move == "circle":
                self.circle_deg += secs * rate
            return Action("search_turn", secs, secs * rate * side, f"searching {'right' if side > 0 else 'left'}" + (f": full circle, {min(self.circle_deg, 360.0):.0f} of 360 deg" if move == "circle" else ""))
        return Action("look", 1.0, why="searching: nothing left to try this round, look again")

    def _three_point(self, kind: str, deg: float, why: str) -> Action:
        """Back up while turning toward `deg`, then forward while turning the opposite way. `seconds` is the backing-up half; the forward half is sized from the turn rate."""
        self.back_s += THREE_POINT_BACK_S
        return Action(kind, THREE_POINT_BACK_S, deg, why)

    def _wall_turn(self, wall: "WallSeen", why: str) -> Action:
        side = 1 if wall.turn == "right" else -1
        deg = min(wall_turn_deg(), CHASE_WALL_TURN_MAX_DEG) * side
        if WALL_THREE_POINT and self._can_back(THREE_POINT_BACK_S):
            return self._three_point("three_point", deg, why + " (a 3-point turn: back up while turning, then forward turning the other way)")
        return Action("wall_turn", abs(deg) / self._turn_rate(side, False), deg, why)

    def decide(self, ball: BallReading | None, wall: "WallSeen | None" = None) -> Action:
        if ball is None:
            self.lost += 1
            self.punts_in_range = 0
            self.nudges = 0
            if self.last_dist is not None and self.last_dist <= NUDGE_MAX_IN:      # it was right there and now it is gone: at the claw, too close for the camera to see (user, 2026-10-25: right in front of the ball and no punt, then a turn away)
                pushed = self.prev_kind == "walk"                  # he stepped toward it and now it is gone: he bumped it and pushed it away, it is not at the claw (user, 2026-11-01)
                self.last_dist = None
                self.lost = 0
                if pushed:
                    self.lost = LOST_LOOKS                          # a look around first; if the ball is not found by it, the next empty picture starts the search
                    if self.claw_ok:
                        return Action("claw_look", why="the ball is gone after a small step: I probably pushed it away: a look around")
                    return Action("look", 1.0, why="the ball is gone after a small step: I probably pushed it away: look again")
                if self.prev_kind == "align":                       # (user, 2026-11-03) it vanished right after a line-up turn: he turned past it, it is not at the claw: back up, look, line up again
                    if self.align_before:
                        self.search_side = -1 if self.align_before > 0 else 1      # it is on the other side of the turn he made
                    self.align_before, self.align_turns = None, 0
                    if self._can_back(VANISH_BACK_S):
                        return self._back("back", VANISH_BACK_S, "the ball vanished after a line-up turn: I turned past it: back up and look again, then line up again")
                    self.lost = LOST_LOOKS
                    return Action("claw_look", why="the ball vanished after a line-up turn: I turned past it: a look around") if self.claw_ok else Action("look", 1.0, why="the ball vanished after a line-up turn: look again")
                if WHEN_VANISHED == "back_up" and self._can_back(VANISH_BACK_S):
                    return self._back("back", VANISH_BACK_S, "the ball vanished at close range: back off a little to see it")
                self.after_punt = True
                self.punt_log.append((None, None))
                return Action("punt", 0.0, why="the ball vanished at close range: it is at the claw: punt")
            if self.lost < LOST_LOOKS:
                return Action("look", 1.0, why=f"no ball ({self.lost} of {LOST_LOOKS}): look again before searching")
            return self._search_move()
        self.lost = 0
        self.search_steps = 0
        self.search_i = 0
        self.circle_deg = 0.0
        self.circles = 0
        self.seen_ball = True
        self.search_side = 0
        if wall is not None and wall.nearest_in is not None and ball.distance_in > NUDGE_MAX_IN:   # walls rank above the punt; but with the ball within a few inches lining up and punching
            # goes no closer to the wall, and the wall reading is not calibrated for the claw camera (user, 2026-11-01: he turned away from a ball right in front of him)
            behind = wall.near_ball_in
            if behind is not None and ball.distance_in < behind and behind - ball.distance_in < CHASE_WALL_IN - BALL_TOUCH_IN:
                self.by_wall += 1
                gap = behind - ball.distance_in
                if self.by_wall < WALL_GIVE_UP:
                    return Action("look", 1.0, why=f"the ball looks {gap:.0f} in from a wall: look again")
                if WALL_SIDESTEP_TRIES > 0 and ball.distance_in > WALL_SIDESTEP_BALL_IN:
                    self.considered.append(f"wall sidestep: not yet, the ball is {ball.distance_in:.0f} in away (sidestep inside {WALL_SIDESTEP_BALL_IN:.0f} in)")
                    pass                                                                    # still far: walk on toward it; the sidestep is decided near the ball
                elif self.sidesteps < WALL_SIDESTEP_TRIES:
                    self.sidesteps += 1
                    self.by_wall = 0
                    away = 1 if wall.turn == "right" else -1                              # the side with more room first, then the other side, and so on
                    side = away if self.sidesteps % 2 else -away
                    theta = math.radians(WALL_SIDESTEP_DEG * side)
                    step = max(1.0, min(WALL_SIDESTEP_IN, (ball.distance_in * math.cos(math.radians(ball.bearing_deg)) - BALL_TOUCH_IN) / max(0.3, math.cos(theta))))       # never past the ball
                    bx, by = ball.distance_in * math.sin(math.radians(ball.bearing_deg)), ball.distance_in * math.cos(math.radians(ball.bearing_deg))      # the ball: right, forward (inches)
                    px, py = step * math.sin(theta), step * math.cos(theta)                                                                                  # where the step ends
                    close = math.degrees(math.atan2(bx - px, by - py)) - WALL_SIDESTEP_DEG * side                                                          # the turn that faces the ball from there
                    return Action("sidestep", step / self._walk_pace(), WALL_SIDESTEP_DEG * side, f"the ball is {gap:.0f} in from a wall: turn {WALL_SIDESTEP_DEG:.0f} deg {'right' if side > 0 else 'left'}, step {WALL_SIDESTEP_IN:.0f} in and come at it from the side ({self.sidesteps} of {WALL_SIDESTEP_TRIES})", close)
                else:
                    return Action("give_up", why=f"the ball is {gap:.0f} in from a wall: too close to reach without getting nearer than {CHASE_WALL_IN:.0f} in to the wall")
            else:
                self.by_wall = 0
                if wall.nearest_in <= CHASE_WALL_IN and ball.distance_in > NO_WALL_TURN_BALL_IN:      # the ball within 12 in: no turn away (the walk is still capped by the loop)
                    self.wall_turns += 1
                    if self.wall_turns >= WALL_TURNS_GIVE_UP:
                        return Action("give_up", why=f"{self.wall_turns} turns away from walls with the ball in sight: walls keep me from it")
                    return self._wall_turn(wall, f"a wall {wall.nearest_in:.0f} in ahead: turn away")
        else:
            self.by_wall = 0
        self.last_dist = ball.distance_in
        self.last_side = 1 if ball.bearing_deg >= 0 else -1
        self.last_bearing, self.last_edge = float(ball.bearing_deg), bool(getattr(ball, "touches_edge", False))
        near = ball.distance_in <= NUDGE_MAX_IN
        in_reach = ball.distance_in <= PUNT_MAX_IN
        if (self.prev_kind == "turn" and self.turn_before is not None and ball.bearing_deg * self.turn_before < 0           # (user, 2026-11-05) he turned toward the ball and it is now on the OTHER side:
                and abs(ball.bearing_deg) > SEARCH_SIDE_DEADBAND_DEG and abs(self.turn_before) > SEARCH_SIDE_DEADBAND_DEG and self._can_back(BACK_UP_S)):      # he overshot: back up, look again, then line up again
            was, self.turn_before, self.align_before, self.align_turns = self.turn_before, None, None, 0
            return self._back("back", BACK_UP_S, f"overshot the turn: the ball swung from {was:+.0f} to {ball.bearing_deg:+.0f} deg: back up and look again, then line up again")
        if near and not in_reach and abs(ball.bearing_deg) <= PUNT_ALIGN_DEG and self.nudges < NUDGES_BEFORE_PUNT:
            self.nudges += 1
            self.after_punt = False
            return Action("walk", NUDGE_S, why=f"ball {ball.distance_in:.1f} in ahead, just out of reach: a small step closer ({self.nudges} of {NUDGES_BEFORE_PUNT})", scripted=NUDGE_GAIT == "scripted")
        if not near:
            self.align_turns = 0
        if near and abs(ball.bearing_deg) > PUNT_ALIGN_DEG:
            if self.prev_kind == "align" and self.align_before is not None and ball.bearing_deg * self.align_before < 0 and self._can_back(BACK_UP_S):
                was, self.align_before, self.align_turns = self.align_before, None, 0         # overshot (user, 2026-11-01): back up, look again, then line up again from the start
                return self._back("back", BACK_UP_S, f"overshot: the ball swung from {was:+.0f} to {ball.bearing_deg:+.0f} deg: back up and look again, then line up again")
            if self.align_turns < ALIGN_TRIES:                  # a small turn, then a new picture (the camera checks every pulse)
                self.align_turns += 1
                self.align_before = float(ball.bearing_deg)
                side = 1 if ball.bearing_deg > 0 else -1
                gain = ALIGN_GAIN * (ALIGN_CLOSE_GAIN if ball.distance_in <= ALIGN_CLOSE_IN else 1.0)
                want = max(ALIGN_MIN_DEG, min(gain * abs(ball.bearing_deg), ALIGN_MAX_DEG))
                secs = max(ALIGN_PULSE_MIN_S, min(ALIGN_PULSE_MAX_S, want / self._turn_rate(side, True)))
                return Action("align", secs, float(ball.bearing_deg), stop_deg=want, why=f"ball {ball.bearing_deg:+.0f} deg off at {ball.distance_in:.0f} in: a small turn to line the claw up ({self.align_turns} of {ALIGN_TRIES})")
            if WHEN_MISALIGNED == "back_up" and self._can_back(BACK_UP_S):
                self.align_turns = 0
                return self._back("back", BACK_UP_S, f"still {ball.bearing_deg:+.0f} deg off after {ALIGN_TRIES} small turns: back up and line up again")
        elif abs(ball.bearing_deg) > (PUNT_ALIGN_DEG if near else ALIGN_DEG):
            deg = max(-MAX_TURN_DEG, min(MAX_TURN_DEG, ball.bearing_deg))
            side = 1 if deg > 0 else -1
            self.turn_before = float(ball.bearing_deg)
            return Action("turn", max(MIN_MOVE_S, abs(deg) / self._turn_rate(side, False)), deg, f"ball {ball.bearing_deg:+.0f} deg off straight: turn")
        if near and self.after_punt and ball.distance_in > CLOSE_IN_IN:
            self.after_punt = False
            return Action("walk", 0.9, why=f"ball still {ball.distance_in:.0f} in away after the punt: step closer", scripted=NUDGE_GAIT == "scripted")
        if near:
            self.after_punt = True
            self.align_turns = 0
            self.punts_in_range += 1
            if self.punts_in_range > STUCK_PUNTS and self._can_back(BACK_UP_S):
                self.punts_in_range = 0
                return self._back("back", BACK_UP_S, f"{STUCK_PUNTS} punts and the ball has not left: back up")
            self.punt_log.append((round(ball.distance_in, 1), round(ball.bearing_deg, 1)))
            return Action("punt", 0.0, why=f"ball {ball.distance_in:.1f} in ahead, {ball.bearing_deg:+.0f} deg: punt")
        self.punts_in_range = 0
        self.after_punt = False
        self.nudges = 0
        from .chase_pace import WALK_START_S as start
        secs = min(WALK_MAX_S, max(MIN_MOVE_S, start + (ball.distance_in - WALK_AIM_IN) / self._walk_pace()))      # aim for WALK_AIM_IN: a gait needs a moment just to get moving, and the ball is touched at about 3 in
        self.walk_log.append((round(ball.distance_in, 1), round(secs, 1)))
        return Action("walk", secs, why=f"ball {ball.distance_in:.0f} in ahead: walk {secs:.1f} s")


class Robot(Protocol):
    def walk(self, seconds: float) -> str: ...
    # optional: def walk_scripted(self, seconds: float) -> str   (Petoi's kwkF walk; a robot without it walks the dialing-in steps with walk())
    def turn(self, degrees: float, seconds: float, stop_deg: float = 0.0) -> str: ...
    def back(self, seconds: float) -> str: ...
    def punt(self) -> str: ...
    def battery_ok(self) -> bool: ...
    # optional: def claw_pose(self, pan: float, lift: float) -> str   (a robot without it never gets a claw look)


class Camera(Protocol):
    def look(self) -> bytes | None: ...


SAG_TILT_DEG = 12.0            # standing, the body this far off the tilt measured right after his last good stand-up (or 20 deg off level before there is one): the legs have sagged
SAG_TILT_LEVEL_DEG = 20.0      # (2026-11-02: the board still read the stand while the back legs had let go and the body sat 33 deg nose-up; the next turn tipped him over)
ATTENTION_TRIES = 3            # kcalib sent this many times at most until the board reads the attention pose (2026-11-02: one sent 1 s after the stop at the end of a turn was ignored)
POSE_TOL_DEG = 12.0            # a leg pose read with `j` names a known pose when every leg joint is within this of it
POSE_WAIT_S = {"stand": 6.0, "attention": 3.0}      # the longest wait for a pose to read as reached after asking for it (the firmware stand-up from rest takes about 2 to 3 s)


def _known_poses() -> dict:
    """The leg poses G2 is ever left in, servo index -> commanded degrees: the stand (the attachment's balance pose), attention (`kcalib`, every leg joint 0), rest and sit."""
    from ..gait import standup
    to_servo = lambda urdf: {standup._URDF_TO_SERVO[k]: float(urdf[k]) for k in range(8)}         # noqa: E731
    return {"stand": to_servo(standup.balance_pose()), "attention": to_servo(standup.ATTENTION_URDF_DEG), "rest": to_servo(standup.rest_pose()),
            "sit": to_servo(standup.SIT_URDF_DEG)}


def classify_pose(joints) -> str:
    """"stand", "attention", "rest", "sit" or "unknown" from the 16 joint angles `j` reports (the angles the firmware last commanded: what it believes, not a measurement)."""
    if not joints or len(joints) < 16:
        return "unknown"
    best, err = "unknown", 1e9
    for name, pose in _known_poses().items():
        e = max(abs(joints[sv] - d) for sv, d in pose.items())
        if e < err:
            best, err = name, e
    return best if err <= POSE_TOL_DEG else "unknown"


def read_joints(link, timeout_s: float = 1.0, sleep=time.sleep, clock=time.monotonic) -> list[int] | None:
    """The 16 joint angles from the firmware's `j` (stops the IMU stream first: the read often failed while it ran), or None (no reply, a garbled one, or a link that cannot read)."""
    import re
    poll, other = getattr(link, "poll_imu", None), getattr(link, "pop_other", None)
    if not callable(poll) or not callable(other):
        return None
    try:
        link.send("gp", read_reply=False, settle=0.0)
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
                    if len(nums) >= 16 and nums[:16] != list(range(16)):        # (the index header row, if the firmware prints one, is skipped)
                        return nums[:16]
            sleep(0.05)
    except Exception as e:  # noqa: BLE001
        log.warning("pose read failed: %s", e)
    return None


def wait_for_pose(link, target: str, timeout_s: float | None = None, sleep=time.sleep, clock=time.monotonic, fallback_s: float = 3.0) -> str:
    """Read the pose until it is `target` or `timeout_s` (POSE_WAIT_S) runs out; returns the last pose read. A link that cannot read at all just waits `fallback_s`."""
    if not callable(getattr(link, "pop_other", None)):
        sleep(fallback_s)
        return "unknown"
    end = clock() + (timeout_s if timeout_s is not None else POSE_WAIT_S.get(target, 3.0))
    pose = "unknown"
    while True:
        pose = classify_pose(read_joints(link, sleep=sleep, clock=clock))
        if pose == target or clock() >= end:
            return pose
        sleep(0.2)


class SerialRobot:
    """The firmware skills over the serial link. Every move ends in a balanced stand (`kbalance`); the link sends `gb` after each skill. Each returns "ok" or "fell"."""

    def __init__(self, link, poll_imu=None, fall_deg: float = 45.0, sleep=time.sleep, clock=time.monotonic, use_pick: bool = False):
        self._lk, self._sleep, self._clock = link, sleep, clock
        self.use_pick = use_pick                          # True: `kpickF`, the pick skill (it opens and closes the claw); the default is the punch
        self._fall_rad = math.radians(fall_deg)
        self._pitch, self._roll = [], []
        self._yaw: float | None = None                    # the last yaw frame (deg, accumulated by the firmware), for the gyro-stopped line-up turns
        self.last_turn_deg: float | None = None
        self.last_turn_s: float | None = None
        self._claw = (0.0, 0.0)                           # (pan, lift) the arm was last sent to by a claw look; every walk, turn and punch starts from (0, 0)
        self._walker = None
        self.bumped = False                               # the last walk ended on a bump (the IMU contact signal)
        self._moved_at: float | None = None              # when the last move (or stand-up) ended: a move soon after it needs no pose read (QUICK_MOVE_S)
        self._sag_checked_at: float | None = None         # the _moved_at the last sag check was made for
        self._stand_tilt: tuple | None = None             # (pitch, roll) right after the last good stand-up: the reference for the sag check
        self._posed_at: float | None = None               # when the legs last changed pose (attention, stand-up): the next move is checked once against the real tilt (_gate)
        self._gate_done_at: float | None = None
        self.last_leg_check: list = []                    # the legs the last leg_check found off their stand angle
        self.gate_reseats = 0                             # legs re-seated by the gate this session (the goal can report it)
        self.last_fall: dict | None = None                # the angles of the last fall the guard saw (pitch, roll, which way, the posture he was in)
        self.posture = "unknown"                          # "stand", "attention" or "unknown" (as the session found him: _stand_if_lying stood him up if he was lying)

    def _tx(self, c: str) -> None:
        self._lk.send(c, read_reply=False, settle=0.0)

    def _fell(self) -> bool:
        try:
            from ..gait.imu_parse import parse_imu_line
        except ImportError:
            from gait.imu_parse import parse_imu_line  # type: ignore
        for line in self._lk.poll_imu():
            r = parse_imu_line(line)
            if r is None:
                continue
            if len(r) > 2:
                self._yaw = math.degrees(r[2])
            self._pitch.append(math.degrees(r[1]))
            self._roll.append(math.degrees(r[0]))
            if max(abs(r[0]), abs(r[1])) > self._fall_rad:
                p, rl = math.degrees(r[1]), math.degrees(r[0])
                way = ("nose down" if p > 0 else "nose up") if abs(p) >= abs(rl) else ("onto the left side" if rl < 0 else "onto the right side")
                log.warning("fall: pitch %+.0f deg, roll %+.0f deg (%s), posture %s; tilt before it: pitch %s, roll %s", p, rl, way, self.posture,
                            [round(x) for x in self._pitch[-8:]], [round(x) for x in self._roll[-8:]])      # which way he went (2026-11-02: two falls with no angle on record)
                self.last_fall = {"pitch": round(p, 1), "roll": round(rl, 1), "way": way, "posture": self.posture}
                return True
        return False

    def swing_deg(self) -> float:
        """How far the body tilted during the last skill (the larger of the pitch and roll ranges): 0 when it never moved."""
        rng = lambda v: (max(v) - min(v)) if len(v) > 1 else 0.0   # noqa: E731
        return max(rng(self._pitch), rng(self._roll))

    def _gate(self) -> str:
        """Before a walk or turn that follows a pose change (user, 2026-11-06: falls come at transitions, and a servo that lags leaves the body in a state the commands do not show):
        the claw down first, then the body's real tilt twice, 0.25 s each. Off the last good stand, or still drifting: the legs are driven back (the attention pose and up again,
        `recover_sag`), twice at most, then he goes anyway (logged). Checked once per pose change. The pack is never a reason: sag is normal. "ok" or "fell"."""
        if not POSE_GATE or self._posed_at is None or self._gate_done_at == self._posed_at or self.posture != "stand":
            return "ok"
        if self._claw != (0.0, 0.0) and self.claw_pose(0.0, 0.0) == "fell":
            return "fell"                                 # a raised claw moves the weight forward: never start a leg move with it up
        for attempt in range(GATE_RESEATS + 1):
            a = self._tilt(GATE_TILT_S)
            b = self._tilt(GATE_TILT_S)
            if a is None or b is None:
                break                                     # no IMU: nothing to judge by
            drift = max(abs(a[0] - b[0]), abs(a[1] - b[1]))
            if not self._sagged(b) and drift <= GATE_DRIFT_DEG:
                log.info("pose gate: steady (pitch %+.0f roll %+.0f deg, drift %.1f)%s", b[0], b[1], drift, f" after {attempt} re-seat(s)" if attempt else "")
                break
            if attempt >= GATE_RESEATS:
                log.warning("pose gate: still off after %d re-seat(s) (pitch %+.0f roll %+.0f deg, drift %.1f): going anyway", attempt, b[0], b[1], drift)
                break
            log.warning("pose gate: not steady (pitch %+.0f roll %+.0f deg, drift %.1f): re-seating the legs", b[0], b[1], drift)
            self.gate_reseats += 1
            if self.recover_sag(b) == "fell":
                return "fell"
        self._gate_done_at = self._posed_at
        return "ok"

    def _calm_before_stop(self) -> str:
        """A firmware move ends with a stop; stopped at an arbitrary gait phase the legs are mid-stride and he can go over (13 of 18 logged falls were in turns). Wait up to CALM_MAX_S for
        a calm moment: the body near how it stands and the tilt barely changing between IMU samples. "ok" or "fell"; with no IMU frames it does not wait."""
        if not STOP_CALM:
            return "ok"
        if not callable(getattr(self._lk, "poll_imu", None)):
            return "ok"
        ref = self._stand_tilt or (0.0, 0.0)
        t0, waited, last = self._clock(), 0.0, None
        while True:
            n = len(self._roll)
            if self._fell():
                return "fell"
            if len(self._roll) == n and last is None:
                return "ok"                               # no frames came: nothing to judge by
            if self._roll:
                cur = (self._pitch[-1], self._roll[-1])
                step = 99.0 if last is None else max(abs(cur[0] - last[0]), abs(cur[1] - last[1]))
                last = cur
                if max(abs(cur[0] - ref[0]), abs(cur[1] - ref[1])) <= CALM_TILT_DEG and step <= CALM_STEP_DEG:
                    break
            waited = self._clock() - t0
            if waited >= CALM_MAX_S:
                break
            self._sleep(0.02)
        log.info("stop on a calm moment: waited %.2f s%s", waited, "" if waited < CALM_MAX_S else " (gave up waiting)")
        return "ok"

    def _skill(self, token: str, seconds: float, stop_yaw_deg: float | None = None) -> str:
        if self._gate() == "fell":
            return "fell"
        self._pitch, self._roll = [], []
        self._tx("gP")
        self.last_turn_deg, self.last_turn_s = None, None
        yaw0 = None
        if stop_yaw_deg is not None:
            self._sleep(0.15)                             # a few frames, so there is a yaw to count from
            self._yaw = None
            if self._fell():
                return "fell"
            yaw0 = self._yaw
        self._tx(token)
        t0, state = self._clock(), "ok"
        limit = seconds
        if yaw0 is not None:
            limit = max(ALIGN_CAP_S, 2.0 * seconds)
        while self._clock() - t0 < limit:
            if self._fell():
                state = "fell"
                break
            if yaw0 is not None and self._yaw is not None and abs(self._yaw - yaw0) >= max(0.0, stop_yaw_deg - ALIGN_STOP_LEAD_DEG):
                break
            self._sleep(0.02 if yaw0 is not None else 0.05)
        ran = self._clock() - t0
        if state != "fell" and yaw0 is None and self._calm_before_stop() == "fell":          # (a gyro-stopped line-up turn is ended on its yaw at once: waiting would turn it further)
            state = "fell"
        self.posture = "stand"
        self._tx("kbalance")                              # ALWAYS end the firmware move, a fall included (2026-11-02: a fall during a back-up skipped this and `kbkF` kept going
        self._sleep(1.0)                                  # for over a minute: the firmware runs a gait until it is told something else)
        if yaw0 is not None:
            self._fell()                                  # the last frames: where the yaw ended once the body had stopped
            if self._yaw is not None:
                self.last_turn_deg, self.last_turn_s = abs(self._yaw - yaw0), ran
                log.info("gyro-stopped turn: asked %.1f deg, got %.1f deg in %.2f s", stop_yaw_deg, self.last_turn_deg, ran)
        self._tx("gp")
        self._moved_at = self._clock()
        return state

    def relax(self) -> str:
        """Into the attention pose (CLAW_LOOK_POSE) to wait there instead of standing (BETWEEN_MOVES "attention", user 2026-11-02). Nothing when he is already in it."""
        if self.posture == "attention":
            return "ok"
        got = "unknown"
        for attempt in range(ATTENTION_TRIES):
            self._tx(CLAW_LOOK_POSE)
            self._claw = (0.0, 0.0)                       # the pose puts the arm at its calibration zero too
            self._sleep(0.5)
            got = wait_for_pose(self._lk, "attention", timeout_s=1.5 if attempt < ATTENTION_TRIES - 1 else None, sleep=self._sleep, clock=self._clock,
                                fallback_s=ATTENTION_SETTLE_S)                  # on only when the board says it is there
            if got in ("attention", "unknown"):
                break
            log.warning("asked for the attention pose, the board reads %s%s", got, ": asking again" if attempt < ATTENTION_TRIES - 1 else "")
        if got in ("attention", "unknown"):
            self.posture = "attention"
        else:                                             # it never took: say what he is in, so nothing after this assumes the attention pose
            self.posture = got if got in ("stand", "rest", "sit") else "stand"
            if hasattr(self._lk, "last_motion_command"):
                self._lk.last_motion_command = {"stand": "kbalance", "rest": "krest", "sit": "ksit"}.get(self.posture, "kbalance")
        self._sleep(0.5)                                  # the body settles before a picture
        self._posed_at = self._clock()
        return "ok"

    def _tilt(self, seconds: float = 0.5):
        """The body's (pitch, roll) in degrees, the median of the IMU lines over `seconds` (the stream is switched on for it and off again), or None."""
        import statistics
        try:
            from ..gait.imu_parse import parse_imu_line
        except ImportError:
            from gait.imu_parse import parse_imu_line  # type: ignore
        self._tx("gP")
        t0, pitch, roll = self._clock(), [], []
        while self._clock() - t0 < seconds:
            for line in self._lk.poll_imu():
                r = parse_imu_line(line)
                if r is not None:
                    roll.append(math.degrees(r[0]))
                    pitch.append(math.degrees(r[1]))
            self._sleep(0.05)
        self._tx("gp")
        return (statistics.median(pitch), statistics.median(roll)) if pitch else None

    def _sagged(self, tilt) -> bool:
        """Standing, but tilted away from how he stood after his last good stand-up: the legs have let go (the pose read cannot see it, it reports the commanded angles)."""
        if tilt is None:
            return False
        if self._stand_tilt is None:
            return max(abs(tilt[0]), abs(tilt[1])) > SAG_TILT_LEVEL_DEG
        return max(abs(tilt[0] - self._stand_tilt[0]), abs(tilt[1] - self._stand_tilt[1])) > SAG_TILT_DEG

    def read_pose(self) -> str:
        """What the board says his legs are in: "stand", "attention", "rest", "sit" or "unknown" (`j`, the commanded angles)."""
        j = read_joints(self._lk, sleep=self._sleep, clock=self._clock)
        pose = classify_pose(j)
        log.info("pose read: %s%s", pose, "" if j is None else f" (legs {j[8:16]})")
        return pose

    def stand_up(self) -> str:
        """Ready to move (user, 2026-11-02: check the pose before every move and decide from it). The pose is read (`j`): standing, nothing to do; the attention pose, the back-legs-
        first stand-up (the link's stand_from_attention); rest or a sit, the normal stand-up (the firmware `kbalance`; from a sit the link's slow back-legs stand-up). An unreadable
        pose falls back to the last one he was told to take (none yet: standing, as the session start left him). Then it waits until the board reads the stand,
        watching for a fall; "fell" if he went over. Standing, and the last move ended under QUICK_MOVE_S ago: nothing to check, he goes at once."""
        if self.posture in ("stand", "unknown") and self._moved_at is not None and self._sag_checked_at != self._moved_at and self._clock() - self._moved_at >= SAG_CHECK_AFTER_S:
            self._sag_checked_at = self._moved_at         # one check per stand: a clean one is not repeated until he has moved again
            tilt = self._tilt()
            if self._sagged(tilt):
                return self.recover_sag(tilt)
        if BETWEEN_MOVES != "attention":
            return "ok"                                   # the standing flow sends nothing before a move (what the code did before 2026-11-02): the pose read, the tilt check and the stand-up wait
                                                          # added serial traffic in front of every walk, and the walks that followed showed no board echoes (docs/STATUS.md item 14)
        if self.posture == "stand" and self._moved_at is not None and self._clock() - self._moved_at < QUICK_MOVE_S:
            return "ok"
        pose = self.read_pose()
        if pose == "unknown":
            pose = "attention" if self.posture == "attention" else "stand"      # never told anything yet: the session start (_stand_if_lying) stood him up
            log.info("pose unreadable: going by the last pose asked for (%s)", pose)
        if pose == "stand":
            self.posture = "stand"
            tilt = self._tilt()
            if not self._sagged(tilt):
                return "ok"
            log.warning("the board reads the stand but he is tilted pitch %+.0f roll %+.0f deg (stood at %s): the legs have sagged, driving them back to the stand pose",
                        tilt[0], tilt[1], "level" if self._stand_tilt is None else f"pitch {self._stand_tilt[0]:+.0f} roll {self._stand_tilt[1]:+.0f}")
            from ..gait import standup
            for _ in range(2):
                self._tx(standup.move_cmd(standup.balance_pose()))          # every leg joint told its stand angle again
                self._sleep(0.25)
            self._sleep(0.5)
            tilt = self._tilt()
            if not self._sagged(tilt):
                return "ok"
            log.warning("still tilted (pitch %+.0f roll %+.0f deg): down into the attention pose and up again, back legs first", tilt[0], tilt[1])
            self.posture = "stand"
            self.relax()
            pose = "attention" if self.posture == "attention" else self.read_pose()
            if pose in ("stand", "unknown"):
                return "ok"                                   # the attention pose did not take: go as he is (logged above)
        return self._stand_up_from(pose)

    def recover_sag(self, tilt=None) -> str:
        """The legs have sagged (the body is tilted away from how he stands when they hold): down into the attention pose, then up again, back legs first. Used by every flow:
        the goal sessions before a move (stand_up) and the voice service's stand guard while he stands idle."""
        log.warning("legs sagged%s: down into the attention pose and up again, back legs first", "" if tilt is None else f" (pitch {tilt[0]:+.0f} roll {tilt[1]:+.0f} deg)")
        self.posture = "stand"
        self.relax()
        if self.posture != "attention":
            log.warning("the attention pose did not take (%s): leaving him as he is", self.posture)
            self._moved_at = self._clock()
            return "ok"
        return self._stand_up_from("attention")

    def fallen(self) -> bool:
        """Whether the IMU says he has gone over (a fresh look at the stream). The tests and drills stop at once on it."""
        return self._fell()

    LEG_CHECK_TOL_DEG = 4.0        # a leg joint the board believes more than this off its stand angle is reported (the pose read's 12 deg tolerance hides one odd leg)

    def leg_check(self, source: str = "stand-up") -> list:
        """After a stand-up (user, 2026-11-06: "a random leg points at an odd angle on stand-up"): read the angles the board believes its leg joints hold (`j`) and compare each with the
        stand pose. This sees a joint command that was lost or garbled on the serial link (the board keeps the old angle); it cannot see a servo that was commanded right but lags (the
        Pi gets no servo feedback: `f` is echo-only over the UART), which only the IMU tilt shows. Logs every deviation, appends the result to ~/.local/share/g2/leg_check.jsonl, and returns
        [(servo, expected, got)]. It only reports (G2_LEG_CHECK=0 turns it off). Never raises."""
        if os.environ.get("G2_LEG_CHECK", "1").strip().lower() in ("0", "off", "false", "no"):
            return []
        try:
            joints = read_joints(self._lk, sleep=self._sleep, clock=self._clock)
            if not joints or len(joints) < 16:
                return []
            exp = _known_poses()["stand"]
            bad = [(sv, round(d), joints[sv]) for sv, d in sorted(exp.items()) if abs(joints[sv] - d) > self.LEG_CHECK_TOL_DEG]
            if bad:
                log.warning("leg check after the %s: %s", source, "; ".join(f"servo {sv} should be {d} deg, the board holds {g}" for sv, d, g in bad))
            else:
                log.info("leg check after the %s: all eight leg joints hold their stand angles", source)
            try:
                import json
                path = os.path.expanduser("~/.local/share/g2/leg_check.jsonl")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a") as f:
                    f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "source": source, "bad": bad, "tilt": self._stand_tilt}) + "\n")
            except OSError:
                pass
            self.last_leg_check = bad
            return bad
        except Exception:  # noqa: BLE001
            log.exception("leg check failed")
            return []

    def stand_up_from_attention(self) -> str:
        """The attention pose to the stand, back legs first (what a goal session does when a move follows a claw look). "ok" or "fell"."""
        return self._stand_up_from("attention")

    def _stand_up_from(self, pose: str) -> str:
        if hasattr(self._lk, "last_motion_command"):
            self._lk.last_motion_command = {"attention": "kcalib", "sit": "ksit"}.get(pose, "krest")      # the link picks its stand-up from this: make it the pose just read
        self._pitch, self._roll = [], []
        log.info("standing up from %s: %s", pose, "back legs first, then the front legs" if pose == "attention" else "the normal stand-up")
        self._tx("kbalance")                              # the link runs its own stand-up for it (attention, sit) or sends the firmware one (rest) ...
        self._tx("gP")                                    # ... and only then the IMU stream: the board is not printing while it takes the joint commands
        t0, state = self._clock(), "ok"
        watch = STAND_UP_WATCH_S if pose in ("attention", "sit") else STAND_UP_WATCH_S + 2.0      # the firmware stand-up from rest takes 2 to 3 s
        while self._clock() - t0 < watch:
            if self._fell():
                state = "fell"
                break
            self._sleep(0.05)
        self._tx("gp")
        self.posture = "stand"
        if state != "fell":
            got = wait_for_pose(self._lk, "stand", sleep=self._sleep, clock=self._clock, fallback_s=0.0)
            if got not in ("stand", "unknown"):
                log.warning("stood up from %s, but the board reads %s", pose, got)
            else:
                t = self._tilt(0.3)
                if t is not None:
                    self._stand_tilt = t                  # how he stands when the legs hold: the sag check compares with this
                self.leg_check(f"stand-up from {pose}")
        self._moved_at = self._clock()
        self._posed_at = self._moved_at
        return state

    def sit_down(self) -> str:
        """The claw look starts from the "attention" pose (user, 2026-11-01; it used to be a sit): stand first, then CLAW_LOOK_POSE, then still. No fall check in it. Already in the
        attention pose: the pose is sent again (it drives every leg joint again) and no stand-up first; just stood up: no second stand-up."""
        self._pitch, self._roll = [], []
        self._tx("gP")
        if BETWEEN_MOVES == "attention" and self.posture in ("attention", "stand"):          # (the standing flow always stands first, as it did before 2026-11-02)
            self._tx(CLAW_LOOK_POSE)
            self._claw = (0.0, 0.0)
            self.posture = "attention"
            self._sleep(CLAW_POSE_S)
            return "ok"
        if CLAW_LOOK_STANDING and BETWEEN_MOVES != "attention":      # (user, 2026-11-03) the look is taken standing: stand if he is not, then nothing else is sent to the legs
            if self.posture != "stand":
                self._tx("kbalance")
                self._sleep(SIT_STAND_FIRST_S)
            self._claw = (0.0, 0.0)
            self.posture = "stand"
            return "ok"
        self._tx("kbalance")                                # stand first, always (user, 2026-11-01: the look began with him lying in the rest pose and stayed there: after a Pi-sent stand-up the legs can go limp, and
        self._sleep(SIT_STAND_FIRST_S)                      # a sit asked of limp legs changes nothing). The firmware stand drives every leg joint to its balance angle again.
        self._tx(CLAW_LOOK_POSE)
        self._claw = (0.0, 0.0)
        self.posture = "attention"
        self._sleep(2.5 if CLAW_LOOK_POSE == "ksit" else CLAW_POSE_S)
        return "ok"

    def stand_from_sit(self) -> str:
        """Up again after the claw look: a normal stand-up (`kbalance`; from a sit the link stands him up slowly with the back legs first, gait/standup.py stand_from_sit), then still; "fell" if he went over.
        With BETWEEN_MOVES "attention" he stays in the attention pose: the next move stands him up (stand_up) right before it starts."""
        if BETWEEN_MOVES == "attention" and self.posture == "attention":
            return "ok"
        if CLAW_LOOK_STANDING and BETWEEN_MOVES != "attention" and self.posture == "stand":
            return "ok"                                     # he never left the stand: nothing to stand up from
        self._pitch, self._roll = [], []
        self._tx("kbalance")
        t0, state = self._clock(), "ok"
        while self._clock() - t0 < 1.0:
            if self._fell():
                state = "fell"
                break
            self._sleep(0.05)
        self._tx("gp")
        self.posture = "stand"
        self._moved_at = self._clock()
        return state

    def walk(self, seconds: float) -> str:
        if self.stand_up() == "fell":
            return "fell"
        self.posture = "stand"
        return self._policy_walk(seconds)                 # always the default gait policy (user, 2026-10-31)

    def walk_scripted(self, seconds: float) -> str:
        """Petoi's scripted forward walk (`kwkF`) for `seconds`, then the balance pose. The dialing-in steps use it (user, 2026-11-04): much steadier than the learned policy, so the distance to the
        ball can be set reliably. "ok" or "fell". The walk has no contact signal (no IMU stream is read), so a bump is not reported."""
        if self.stand_up() == "fell":
            return "fell"
        self.posture = "stand"
        self.bumped = False
        return self._skill("kwkF", seconds)

    def _policy_walk(self, seconds: float) -> str:
        """The learned walk (the attachment's saved gait) for `seconds`, ending in a balanced stand. "fell" if it ended in a fall. A bump (the walk's IMU contact signal, the same one
        exploration uses) stops the walk at once and sets `bumped` (the walls goal counts it)."""
        if self._gate() == "fell":
            return "fell"
        from ..gait.policy_walker import PolicyWalker
        fell, hit = [], []
        if self._walker is None:
            self._walker = PolicyWalker(self._lk, hold_between_legs=True, on_fall=lambda: fell.append(1), on_contact=lambda ev=None: hit.append(ev))
        else:
            self._walker._on_fall = lambda: fell.append(1)
            self._walker._on_contact = lambda ev=None: hit.append(ev)
        self.bumped = False
        self._walker.start_failure = None
        self._walker.walk(seconds)
        t0 = self._clock()
        self._sleep(0.2)
        while self._walker.busy and self._clock() - t0 < seconds + 10.0:
            if hit:
                self._walker.stop(rest=False)                 # he walked into something: stop now, the next look decides (a wall ahead: turn away)
                break
            self._sleep(0.05)
        if self._walker.busy:
            self._walker.stop(rest=False)
        self.bumped = bool(hit)
        self._moved_at = self._clock()
        if getattr(self._walker, "start_failure", None) and "IMU" in str(self._walker.start_failure):
            return "board_silent"                     # the board sends no IMU frames: the walk never started (it rested him); retrying only repeats rest, picture, stand-up
        return "fell" if fell else "ok"

    def claw_pose(self, pan: float, lift: float) -> str:
        """Move the arm (pan joint 0, lift joint 1) to point the camera, at CLAW_DEG_S, watching the IMU. The legs are not sent. "ok" or "fell"."""
        pan = max(-45.0, min(45.0, float(pan)))
        lift = max(0.0, min(CLAW_LIFT_MAX_DEG, float(lift)))
        p0, l0 = self._claw
        span = max(abs(pan - p0), abs(lift - l0))
        steps = max(1, int(math.ceil(span / CLAW_DEG_S * CLAW_STEPS_PER_S)))
        self._pitch, self._roll = [], []
        self._tx("gP")
        state = "ok"
        for i in range(1, steps + 1):
            u = i / steps
            k = u * u * (3 - 2 * u)
            self._tx(f"i0 {int(round(p0 + (pan - p0) * k))} 1 {int(round(l0 + (lift - l0) * k))}")
            self._sleep(1.0 / CLAW_STEPS_PER_S)
            if i % 5 == 0 and self._fell():
                state = "fell"
                break
        self._claw = (pan, lift)
        self._tx("gp")
        return state

    def turn(self, degrees: float, seconds: float, stop_deg: float = 0.0) -> str:
        """Turn by firmware skill for `seconds`. With `stop_deg` (the line-up turns) the turn ends on the gyro instead: once the yaw has changed by that much (less ALIGN_STOP_LEAD_DEG),
        or after ALIGN_CAP_S; with no yaw reading the timed `seconds` apply. `last_turn_deg` / `last_turn_s` say what he did."""
        if self.stand_up() == "fell":
            return "fell"
        return self._skill("kwkR" if degrees > 0 else "kwkL", seconds, stop_yaw_deg=stop_deg if stop_deg > 0 else None)

    def back(self, seconds: float) -> str:
        if self.stand_up() == "fell":
            return "fell"
        return self._skill("kbkF", seconds)

    def three_point_turn(self, degrees: float, back_s: float, forward_s: float) -> str:
        """Back up while turning one way, then walk forward turning the OPPOSITE way, and he ends up facing `degrees` (+ = right) round (user, 2026-11-01: the forward half is the one that
        takes him where he is going, so it turns toward `degrees` and the back-up turns the other way, like a car). The first real use turned him the wrong way: back right, forward left."""
        if self.stand_up() == "fell":
            return "fell"
        state = self._skill(THREE_POINT_BACK_TOKEN["left" if degrees > 0 else "right"], back_s)
        if state == "fell":
            return state
        return self._skill("kwkR" if degrees > 0 else "kwkL", forward_s)

    def _pose_cmd(self, lift, sh, kn) -> str:
        return f"i1 {int(round(lift))} 2 0 8 {int(round(sh[0]))} 9 {int(round(sh[1]))} 10 {int(round(sh[2]))} 11 {int(round(sh[3]))} 12 {int(round(kn[0]))} 13 {int(round(kn[1]))} 14 {int(round(kn[2]))} 15 {int(round(kn[3]))}"

    def punch(self) -> str:
        """The lunge with the claw shut (PUNCH_KEYS), played as `i` commands at 40 a second from the pose he stands in, then back to the balance pose. No firmware skill is sent."""
        if self.stand_up() == "fell":                                   # the lunge starts from the balance pose
            return "fell"
        return self._punch()

    def _punch(self) -> str:
        from ..link import transitions
        self.posture = "stand"
        self._pitch, self._roll = [], []
        self._tx("gP")
        bal = transitions.balance_pose()                              # Petoi order [FLs, FRs, BRs, BLs, FLk, FRk, BRk, BLk]
        cur = (0.0, list(bal[:4]), list(bal[4:]))
        keys = [(t, lift, [a + (-10 if i < 2 else 0) for i, a in enumerate(sh)], [b + (6 if i < 2 else 0) for i, b in enumerate(kn)]) for t, lift, sh, kn in punch_keys()]
        keys.append((0.40, 0, list(bal[:4]), list(bal[4:])))           # and back to the balance pose
        n = 0
        for t, lift, sh, kn in keys:
            steps = max(1, int(round(t * PUNCH_STEPS_PER_S)))
            for i in range(1, steps + 1):
                u = i / steps
                k = u * u * (3 - 2 * u)
                self._tx(self._pose_cmd(cur[0] + (lift - cur[0]) * k, [a + (b - a) * k for a, b in zip(cur[1], sh)], [a + (b - a) * k for a, b in zip(cur[2], kn)]))
                self._sleep(1.0 / PUNCH_STEPS_PER_S)
                n += 1
                if n % 5 == 0 and self._fell():
                    self._tx("gp")
                    return "fell"
            cur = (lift, sh, kn)
        self._sleep(0.3)
        self._fell()
        self._tx("gp")
        self._moved_at = self._clock()
        return "ok"

    def punt(self) -> str:
        if self.stand_up() == "fell":
            return "fell"
        if not self.use_pick:
            state = self._punch()
            if state == "ok" and self.swing_deg() < PUNT_MIN_SWING_DEG:       # the lunge tilts the body 15 deg or more; if he barely moved it did not play: once more
                log.warning("the punch barely moved him (%.1f deg): once more", self.swing_deg())
                state = self._punch()
            return state
        state = self._skill("kpickF", 2.0)
        if state == "ok" and self.swing_deg() < PUNT_MIN_SWING_DEG:       # the lunge tilts the body 15 deg or more; if he barely moved, it did not play (2026-10-25: a run said "punted" and he only lay down): send it again once
            log.warning("the punt barely moved him (%.1f deg): sending it again", self.swing_deg())
            state = self._skill("kpickF", 2.0)
        return state

    def battery_ok(self) -> bool:
        from ..power import battery
        ok, pct, volts = battery.motion_gate(self._lk)
        self.last_pct = pct
        if pct is None:
            log.warning("battery unreadable: %s", "continuing (testing; G2_BATTERY_STRICT=1 stops)" if ok else "stopping (fail safe)")
        else:
            log.info("battery %d%% (%.2f V)", pct, volts)
        return ok


class PictureSaver:
    """Saves each picture with the ball found plus its box (JSON beside it), at most one per SAVE_EVERY_S. Training data for the "ball" class (user, 2026-10-25)."""

    def __init__(self, folder: str, clock=time.monotonic):
        self._dir, self._clock, self._last = Path(os.path.expanduser(folder)), clock, -1e9
        self.saved = 0

    def maybe_save(self, jpeg: bytes, ball: BallReading | None, tag: str = "chase") -> None:
        if ball is None or self._clock() - self._last < SAVE_EVERY_S:
            return
        self._last = self._clock()
        self._dir.mkdir(parents=True, exist_ok=True)
        name = time.strftime(f"greenball_{tag}_%Y%m%d_%H%M%S")              # the date too: the review page sorts by file name, and a time alone mixed nights together
        (self._dir / f"{name}.jpg").write_bytes(jpeg)
        mean = None
        try:                                                  # the sidecar format of the exploration pictures, so the review page (g2pics) lists them with the others
            import io

            import numpy as np
            from PIL import Image
            mean = round(float(np.asarray(Image.open(io.BytesIO(jpeg)).convert("L")).mean()), 1)
        except Exception:  # noqa: BLE001
            pass
        (self._dir / f"{name}.json").write_text(json.dumps({
            "file": f"{name}.jpg", "kind": "name:greenball", "pose": "named", "name": "greenball", "time": time.strftime("%Y-%m-%d %H:%M:%S"), "width": 240, "height": 240,
            "detections": [], "exposure": {"mean": mean}, "named_by": "ball_chase",
            "box_xywh": [round(ball.x - ball.width / 2), round(ball.y - ball.height / 2), ball.width, ball.height],
            "distance_in": round(ball.distance_in, 1), "bearing_deg": round(ball.bearing_deg, 1), "edge": ball.touches_edge}, indent=1))
        self.saved += 1


CONFIRM_DIM_S = 1.2            # the wait before the second picture that confirms a ball only the loose "dim" pass found (the camera's frames are about 1 s old)
CONFIRM_BEARING_DEG = 15.0     # the second picture must show it within this many degrees of where the first did


def confirm_ball(camera, ball: BallReading | None, sleep=time.sleep, trace: list | None = None) -> BallReading | None:
    """A ball only the loose "dim" pass found (it also takes round green things on the floor, 2026-11-01) counts only when the next picture shows it again, within CONFIRM_BEARING_DEG.
    Any other reading is returned as it is."""
    if ball is None or getattr(ball, "via", "normal") != "dim":
        return ball
    sleep(CONFIRM_DIM_S)
    jpeg = camera.look()
    again = find_ball(jpeg) if jpeg else None
    ok = again is not None and abs(again.bearing_deg - ball.bearing_deg) <= CONFIRM_BEARING_DEG
    if trace is not None:
        trace.append({"kind": "dim_confirm", "ok": ok, "first": _ball_dict(ball), "second": _ball_dict(again)})
    return again if ok else None


def claw_scan(robot, camera, planner: ChasePlanner, *, saver=None, sleep=time.sleep, say: Callable[[str], None] = print, trace: list | None = None,
              stamp: Callable[[], float] | None = None, after_punt: bool = False) -> tuple[str, BallReading | None]:
    """One look around with the arm: the camera to one side, then the other, then the centre, a picture at each (user, 2026-11-03: left, right, centre; from a sit all three are always taken); stops at the first sight of the ball. The arm goes back
    to (0, 0) at the end. Returns (state, the ball with its bearing turned into G2's own direction, or None). `stamp()` times the trace entries (the scorer needs when the ball was
    first seen); `after_punt` marks a look for where the ball went, which is not a search."""
    extra = {"after_punt": True} if after_punt else {}
    fresh = getattr(camera, "refresh_exposure", None)
    if callable(fresh):
        fresh()                                                                      # one exposure check before the whole look around (user, 2026-10-31), not one per picture
    from_sit = CLAW_FROM_SIT and not after_punt and hasattr(robot, "sit_down") and hasattr(robot, "stand_from_sit")
    if from_sit:
        left = CLAW_PAN_DEG if CLAW_PAN_SIGN == "left" else -CLAW_PAN_DEG            # the pan that points the camera to G2's left
        pans = [left, -left, 0.0]                                                     # always left first, then right (user, 2026-11-01), then the centre, claw still raised (user, 2026-11-03)
        if robot.sit_down() == "fell":
            return "fell", None
    else:
        side = planner.claw_side or planner.last_side or 1
        pans = [side * CLAW_PAN_DEG, -side * CLAW_PAN_DEG]
    found, state = None, "ok"
    seen = []                                                                         # [(pan, reading)]
    raise_first = CLAW_RAISE_FIRST and (BETWEEN_MOVES == "attention" or (from_sit and not CLAW_LOOK_STANDING))      # only from the attention pose, where the claw sits between the legs (user, 2026-11-03: attention pose, raise the claw, pan left, picture, pan right, picture, centre, lower, stand up)
    if raise_first:
        state = robot.claw_pose(0.0, CLAW_LIFT_DEG if CLAW_RAISE_DEG is None else CLAW_RAISE_DEG)                                 # up first, straight ahead and well clear of the legs before any pan (the pictures come down to CLAW_LIFT_DEG)
    for pan in (pans if state != "fell" else []):
        state = robot.claw_pose(pan, CLAW_LIFT_DEG)
        if state == "fell":
            break
        sleep(CLAW_SETTLE_S)
        jpeg = camera.look()
        ball = confirm_ball(camera, find_ball(jpeg) if jpeg else None, sleep, trace)
        if ball is not None:
            if saver is not None:
                saver.maybe_save(jpeg, ball, tag="claw")
            seen.append((pan, ball))
            if not from_sit:
                break                                                                  # from a sit both pictures are always taken (the arm goes back to centre and he stands up next)
    if seen:
        pan, ball = seen[0]
        kept = [seen[0]]
        for pan_i, b_i in seen[1:]:
            pan_p, b_p = kept[-1]
            if abs(b_i.bearing_deg - b_p.bearing_deg) < 4.0 and abs(b_i.distance_in - b_p.distance_in) < 1.0 and abs(pan_i - pan_p) > 30.0:
                say(f"   the claw picture at pan {pan_i:+.0f} matches the one before although the arm moved: an old frame, ignored")      # the arm moved, the picture did not
                continue
            kept.append((pan_i, b_i))
        for pan_i, b_i in kept[1:]:
            if abs(b_i.bearing_deg) < abs(ball.bearing_deg) - 3.0:        # the sighting nearer the middle of its picture is the better one (user, 2026-11-01: the last was used, +77 deg)
                pan, ball = pan_i, b_i
        found = dataclasses.replace(ball, bearing_deg=ball.bearing_deg + claw_pan_body(pan))
        if trace is not None:
            trace.append({"kind": "claw_seen", "pan": pan, "lift": CLAW_LIFT_DEG, "cam_bearing": round(ball.bearing_deg, 1), "distance_in": round(ball.distance_in, 1),
                          **({"t": stamp()} if stamp else {}), **extra})
        say(f"   claw look at pan {pan:+.0f} lift {CLAW_LIFT_DEG:.0f}: ball {ball.distance_in:.0f} in, {found.bearing_deg:+.0f} deg from straight ahead")
    if state != "fell" and raise_first and (not pans or pans[-1] != 0.0):
        state = robot.claw_pose(0.0, CLAW_LIFT_DEG)                                  # back to the centre still raised (a look that ends on the centre picture is there already) ...
    if state != "fell":
        state = robot.claw_pose(0.0, 0.0)                                            # ... then lowered
    if from_sit and state != "fell":
        state = robot.stand_from_sit()
    if trace is not None:
        trace.append({"kind": "claw_look", "found": found is not None, "state": state, **({"t": stamp()} if stamp else {}), **extra})
    return state, found


TURN_CAUSE = {"three_point": "a 3-point turn (back up while turning, then forward)", "wall_turn": "a wall ahead", "search_turn": "searching: no ball in sight", "align": "lining the claw up on a close ball", "turn": "the ball off to one side"}
TURN_LOG = "~/.local/share/g2/turn_log.jsonl"
LOG_MAX_BYTES = 50 * 1024 * 1024          # a chase log stops growing at this size (2026-11-02: a sim run once wrote 42 GB to the turn log); the daily cleanup rotates old lines out


def _log_full(path: str) -> bool:
    try:
        return os.path.getsize(path) >= LOG_MAX_BYTES
    except OSError:
        return False
DECISION_LOG = "~/.local/share/g2/decision_log.jsonl"


def log_decision(step: int, act, ball, wall, planner, t: float) -> None:
    """One line per decision in DECISION_LOG (user, 2026-11-02: every choice and why, to debug bad behaviour): the move chosen and the reason in words, what he saw (ball, wall),
    the planner's state when it chose (looks without the ball, search move, circle, back-up used, sidesteps, nudges ...), and the options it looked at and passed over. Never raises."""
    try:
        path = os.path.expanduser(os.environ.get("G2_DECISION_LOG", DECISION_LOG))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "t": round(t, 1), "step": step, "kind": act.kind, "why": act.why, "degrees": round(act.degrees, 1), "seconds": round(act.seconds, 2),
               "ball": _ball_dict(ball), "wall_in": None if wall is None or wall.nearest_in is None else round(wall.nearest_in, 1),
               "state": {"lost": planner.lost, "search_i": planner.search_i, "search_steps": planner.search_steps, "circle_deg": round(planner.circle_deg), "circles": planner.circles,
                         "back_s": round(planner.back_s, 1), "sidesteps": planner.sidesteps, "by_wall": planner.by_wall, "nudges": planner.nudges, "align_turns": planner.align_turns,
                         "punts_in_range": planner.punts_in_range, "last_side": planner.last_side, "seen_ball": planner.seen_ball, "search_order": SEARCH_ORDER},
               "passed_over": list(planner.considered)}
        if _log_full(path):
            return
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001
        pass


def log_turn(act, ball, wall, state: str) -> None:
    """One line per turn in TURN_LOG (user, 2026-11-01: every turn and why, to debug him turning away from a ball): the cause, the reason in words, which way and how far,
    and what he saw (the ball and the wall reading) when he decided. Never raises."""
    try:
        path = os.path.expanduser(os.environ.get("G2_TURN_LOG", TURN_LOG))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": act.kind, "cause": TURN_CAUSE.get(act.kind, act.kind), "why": act.why,
               "direction": "right" if act.degrees > 0 else "left", "degrees": round(act.degrees, 1), "seconds": round(act.seconds, 2), "state": state,
               "ball": _ball_dict(ball), "wall_in": None if wall is None or wall.nearest_in is None else round(wall.nearest_in, 1)}
        if _log_full(path):
            return
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _ball_dict(ball: BallReading | None):
    return None if ball is None else {"distance_in": round(ball.distance_in, 1), "bearing_deg": round(ball.bearing_deg, 1), "edge": ball.touches_edge}


def _premeter(camera) -> None:
    """Just before a move: start metering the light in the background so the next picture does not do it while he stands waiting. A camera without it (a test double) is left alone."""
    fn = getattr(camera, "premeter", None)
    if callable(fn):
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.debug("premeter failed", exc_info=True)


def _relax(robot) -> None:
    """Wait in the attention pose, not standing (BETWEEN_MOVES "attention"); a robot without the pose (a test double) is left alone."""
    fn = getattr(robot, "relax", None)
    if BETWEEN_MOVES == "attention" and callable(fn):
        fn()


def _dialing_in(ball: BallReading | None) -> bool:
    """The ball is close enough that the moves are small steps to line the claw up: no attention pose between them (read at each call: the goal sets the ranges per attempt)."""
    return ball is not None and ball.distance_in <= max(NUDGE_MAX_IN, PUNT_MAX_IN)


def run_chase(robot: Robot, camera: Camera, stop: Callable[[], bool], **kw) -> str:
    """Look, decide, move, until `stop()` or a fall or a low battery (`_chase_loop` has the details and the keyword arguments). He starts and ends in the attention pose
    (BETWEEN_MOVES "attention"), unless he fell; each move stands him up first when it has to (the robot's own move methods do it)."""
    if not kw.get("dry_run"):
        _relax(robot)                                     # the first picture is taken in the attention pose too
    ended = _chase_loop(robot, camera, stop, **kw)
    if ended != "fell" and not kw.get("dry_run"):
        _relax(robot)
    return ended


def _chase_loop(robot: Robot, camera: Camera, stop: Callable[[], bool], *, planner: ChasePlanner | None = None, saver: PictureSaver | None = None, dry_run: bool = False, announce: Callable[[str], None] | None = None,
              settle_s: float = 1.0, sleep=time.sleep, max_steps: int | None = None, max_punts: int | None = None, max_seconds: float | None = None, clock=time.monotonic, say: Callable[[str], None] = print,
              trace: list | None = None, after_punt_look: bool = False, pace=None, wall_check=None, battery_checked: bool = False) -> str:
    """Look, decide, move, until `stop()` or a fall or a low battery. Returns "stopped", "fell", "battery", "steps" or (with `max_punts`: one attempt = walk up and punt that many times) "punted".
    Never gives up on its own. `trace` (a list) collects what happened, for the goals' scorer (pi_pipeline/goals). `after_punt_look`: one more look after the last punt, to see where the ball went.
    `pace` (a chase_pace.PaceBook): times the walks and turns, and is updated from the reading before and after each one. `wall_check(jpeg, ball) -> WallSeen | None`: the wall
    reading for each straight-ahead picture (goals/walls.py makes one only with a wall calibration from the current hardware); with it he keeps CHASE_WALL_IN from walls."""
    planner = planner or ChasePlanner()
    planner.claw_ok = callable(getattr(robot, "claw_pose", None))
    if pace is not None:
        planner.pace = pace
    last_move = None                                      # (kind, seconds, degrees, the ball before it): measured against the next reading
    steps = 0
    punts = 0
    seen = False
    pending: BallReading | None = None                    # the ball a claw look just found (the camera is back at straight ahead, so it would not see it now)
    t_start = clock()

    def note(**kw):
        if trace is not None:
            trace.append({"t": round(clock() - t_start, 2), **kw})

    wall_state: dict = {}
    still_from = clock()                                  # when he last stopped moving: the still time before each move is logged (the legs let go after 7 to 10 s)
    still_step = 0                                        # the step he last moved in: pictures taken since = steps - still_step
    parts: dict = {}                                      # where that still time went since the last move: {"settle": s, "camera": s, ...} (logged with it, 2026-11-02)

    def timed(name, fn, *a, **kw):
        t0 = clock()
        try:
            return fn(*a, **kw)
        finally:
            parts[name] = round(parts.get(name, 0.0) + clock() - t0, 2)
    while not stop():
        if max_steps is not None and steps >= max_steps:
            return "steps"
        if max_seconds is not None and clock() - t_start >= max_seconds:
            say(f"time is up ({max_seconds:.0f} s): ending the attempt")
            return "time"
        steps += 1
        if steps % 15 == 1 and not (battery_checked and steps == 1) and not dry_run and not timed("battery", robot.battery_ok):          # (the goal runner has just read the pack: not twice)
            say("battery low or unreadable: stopping")
            return "battery"
        wall = None
        if pending is not None:
            ball, pending = pending, None
            last_move = None                              # a claw-look reading is from another camera pose: not a before / after pair
        else:
            timed("settle", sleep, settle_s)                  # let the body stop swaying before the picture (in the attention pose, or standing while he dials in close to the ball)
            jpeg = timed("camera", camera.look)
            if not jpeg:                                      # the camera gave no picture: that says nothing about the ball (2026-10-25: counting it as a miss sent him turning away from a ball straight ahead)
                say(f"[{steps}] no picture from the camera: looking again")
                note(kind="no_picture")
                continue
            ball = timed("confirm", confirm_ball, camera, timed("find", find_ball, jpeg), sleep, trace)         # a ball only the loose pass found needs a second picture (user, 2026-11-01: false balls)
            if saver is not None:
                saver.maybe_save(jpeg, ball)
            if last_move is not None and planner.pace is not None and not dry_run:
                kind, secs, degs, before = last_move
                got = planner.pace.record_walk(before, ball, secs) if kind == "walk" else planner.pace.record_turn(before, ball, degs, secs)
                if got is not None:
                    note(kind="measured", what=kind, seconds=round(secs, 2), value=round(got, 2))
            last_move = None
            if wall_check is not None:
                try:
                    wall = timed("wall", wall_check, jpeg, ball)
                except Exception:  # noqa: BLE001
                    wall = None
                wall, dropped = vet_wall(wall, ball, wall_state)
                if dropped:
                    say(f"[{steps}] wall reading ignored: {dropped}")
                    note(kind="wall", event="ignored", why=dropped)
        note(kind="look", ball=_ball_dict(ball), **({"wall_in": None if wall.nearest_in is None else round(wall.nearest_in, 1)} if wall is not None else {}))
        if announce is not None:                          # real-time signal of what he sees (user, 2026-10-25): "searching" when a search starts, "target acquired" when the ball is found again
            if ball is not None and (planner.lost > 0 or planner.search_steps > 0 or planner.search_i > 0 or not seen):
                announce("target acquired")
            elif ball is None and planner.lost + 1 == LOST_LOOKS:                       # the look that starts a search
                announce("searching")
        seen = seen or ball is not None
        planner.considered = []
        act = planner.decide(ball, wall)
        if wall is not None and wall.nearest_in is not None and act.kind in ("walk", "search_walk"):      # never walk closer than CHASE_WALL_IN to a wall
            from .chase_pace import WALL_PACE_START_S
            room = wall.nearest_in - (min(CHASE_WALL_IN, WALL_FLOOR_IN) if ball is not None and ball.distance_in <= 14.0 else CHASE_WALL_IN)         # near the ball: the owner's 5 in floor
            if room <= 0.5 and ball is not None and ball.distance_in <= NO_WALL_TURN_BALL_IN:
                act = Action("look", 1.0, why=f"a wall {wall.nearest_in:.0f} in ahead and the ball {ball.distance_in:.0f} in away: no turn away, no step closer; look again")
            elif room <= 0.5:
                act = planner._wall_turn(wall, f"a wall {wall.nearest_in:.0f} in ahead: turn away instead of walking")
            else:
                cap = WALL_PACE_START_S + room / planner._walk_pace()
                if act.seconds > cap:
                    act = Action(act.kind, round(cap, 2), act.degrees, act.why + f" (cut short: a wall {wall.nearest_in:.0f} in ahead)")
        planner.prev_kind = act.kind
        log_decision(steps, act, ball, wall, planner, clock() - t_start)
        say(f"[{steps}] {'ball ' + format(ball.distance_in, '.0f') + ' in ' + format(ball.bearing_deg, '+.0f') + ' deg' if ball else 'no ball'} -> {act.kind}: {act.why}")
        if dry_run or act.kind == "look":
            note(kind="act", act=act.kind, why=act.why)
            if act.kind == "look":
                if not dry_run and not _dialing_in(ball):
                    _relax(robot)                         # not moving: wait in the attention pose
                timed("look_again_wait", sleep, act.seconds)
            continue
        if act.kind == "give_up":
            note(kind="wall", event="ball_by_wall", wall_in=None if wall is None else wall.nearest_in, why=act.why)
            say(act.why)
            return "ball_by_wall"
        if act.kind != "claw_look":
            still = round(clock() - still_from, 1)
            note(kind="still", seconds=still, before=act.kind, parts=dict(parts), looks=steps - still_step)
            if still > STILL_SAY_S:
                say(f"[{steps}] stood still {still:.1f} s before this {act.kind}: " + ", ".join(f"{k} {v:.1f}" for k, v in sorted(parts.items(), key=lambda kv: -kv[1])[:4]) + f" ({steps - still_step} picture(s))")
        if act.kind == "claw_look":
            state, pending = claw_scan(robot, camera, planner, saver=saver, sleep=sleep, say=say, trace=trace, stamp=lambda: round(clock() - t_start, 2))
            note(kind="act", act="claw_look", why=act.why, state=state, found=pending is not None)
            if state == "fell":
                say("G2 fell: stopping (fall recovery is off)")
                return "fell"
            if CLAW_FROM_SIT and pending is not None:        # seen from a sit: the camera is lower and tilted, so only the DIRECTION is trusted. Turn toward it, then look again standing.
                b = pending.bearing_deg
                pending = None
                planner.last_side = 1 if b >= 0 else -1
                planner.last_bearing, planner.last_edge = float(b), False
                if abs(b) > 8.0:
                    side = 1 if b > 0 else -1
                    state = robot.turn(b, max(MIN_MOVE_S, abs(min(abs(b), MAX_TURN_DEG)) / planner._turn_rate(side, False)))
                    note(kind="act", act="turn", why=f"the ball was {b:+.0f} deg off in the claw look from the sit: turn toward it", state=state, degrees=round(b, 1))
                    if state == "fell":
                        say("G2 fell: stopping (fall recovery is off)")
                        return "fell"
            _relax(robot)                                    # stays in (or goes back to) the attention pose until the next look stands him up
            still_from, still_step = clock(), steps
            parts.clear()
            continue
        if act.kind in ("wall_turn", "turn", "search_turn", "align", "walk", "search_walk", "back", "search_back", "three_point", "sidestep"):
            _premeter(camera)                                 # meter the light while he moves, not while he stands waiting for the picture
        if act.kind == "wall_turn":
            note(kind="wall", event="steer", wall_in=None if wall is None else wall.nearest_in, why=act.why)
            state = robot.turn(act.degrees, act.seconds)
        elif act.kind in ("turn", "search_turn", "align"):
            state = robot.turn(act.degrees, act.seconds, stop_deg=act.stop_deg) if act.stop_deg > 0 else robot.turn(act.degrees, act.seconds)
            if ball is not None:
                last_move = ("turn", getattr(robot, "last_turn_s", None) or act.seconds, act.degrees, ball)      # a gyro-stopped turn ran for its own time, not the timed fallback
        elif act.kind == "sidestep":
            side = 1 if act.degrees > 0 else -1
            state = robot.turn(act.degrees, abs(act.degrees) / planner._turn_rate(side, False))
            if state not in ("fell", "board_silent"):
                state = robot.walk(act.seconds)
            if state not in ("fell", "board_silent") and abs(act.degrees2) >= 3.0:
                state = robot.turn(act.degrees2, abs(act.degrees2) / planner._turn_rate(1 if act.degrees2 > 0 else -1, False))       # face the ball again: it would be outside the camera's view
            last_move = None
        elif act.kind in ("walk", "search_walk"):
            state = robot.walk_scripted(act.seconds) if act.scripted and hasattr(robot, "walk_scripted") else robot.walk(act.seconds)
            if state == "board_silent":
                say("the BiBoard is not sending anything back (no IMU frames): power-cycle it (switch it off and on), then try again")
                note(kind="act", act=act.kind, why=act.why, state=state)
                return "board_silent"
            if getattr(robot, "bumped", False):
                note(kind="wall", event="bump", wall_in=None if wall is None else wall.nearest_in, why="bumped into something while walking")
                say(f"[{steps}] bumped into something while walking: backing off")
                if state != "fell" and planner._can_back(VANISH_BACK_S):         # off the wall first (as exploration's hit sequence does); the next look decides the turn
                    planner.back_s += VANISH_BACK_S
                    state = robot.back(VANISH_BACK_S)
                last_move = None
                ball = None                                                       # no pace sample from a walk that ended on a bump
            if ball is not None and act.kind == "walk" and not act.scripted:         # (the pace book measures the learned walk; a scripted step must not pull it)
                last_move = ("walk", act.seconds, 0.0, ball)
        elif act.kind == "three_point":
            if announce is not None:
                announce("backing up")
            side = 1 if act.degrees > 0 else -1
            state = robot.three_point_turn(act.degrees, act.seconds, abs(act.degrees) / planner._turn_rate(side, False))
        elif act.kind in ("back", "search_back"):
            if announce is not None:
                announce("backing up")                    # he says it when he picks the back-up (user, 2026-11-01)
            state = robot.back(act.seconds)
        elif act.kind == "punt":
            if announce is not None:
                announce("punting")                       # he says it right before the lunge (user, 2026-10-25)
            state = robot.punt()
            punts += 1
            note(kind="act", act="punt", why=act.why, state=state, at=planner.punt_log[-1] if planner.punt_log else None)
            sleep(1.5)                                    # the ball is rolling: look after it stops
            if state != "fell" and max_punts is not None and punts >= max_punts:
                if after_punt_look:
                    # One straight picture after the punch decides it (user, 2026-11-01): the ball gone from in front of the claw, or farther away, means it was punted. No claw look
                    # or back-up here: if it is gone, the next attempt looks, then searches. Let him settle and drop one frame first (it can be from before the punch).
                    sleep(AFTER_PUNT_SETTLE_S)
                    jpeg = camera.look()                       # (_SnapshotCamera.look already drops the old frame)
                    after = find_ball(jpeg) if jpeg else None
                    note(kind="after_punt", ball=_ball_dict(after), picture=bool(jpeg))
                say(f"punted {punts}: done")
                say(f"ATTEMPT: punted at {planner.punt_log[-1] if planner.punt_log else '?'} (in, deg) after {steps} looks; walk steps (ball in, seconds): {planner.walk_log}")
                return "punted"
            if state == "fell":
                say("G2 fell: stopping (fall recovery is off)")
                return "fell"
            if not _dialing_in(ball):                     # another punt or a step closer is next when the ball is still at the claw: stay up
                _relax(robot)
            still_from, still_step = clock(), steps
            parts.clear()
            continue
        else:
            state = "ok"
        note(kind="act", act=act.kind, why=act.why, state=state, seconds=round(act.seconds, 2), degrees=round(act.degrees, 1))
        if act.kind in TURN_CAUSE:
            log_turn(act, ball, wall, state)
        if state == "fell":
            say("G2 fell: stopping (fall recovery is off)")
            return "fell"
        if not _dialing_in(ball):
            _relax(robot)                                 # the move is over: wait in the attention pose, not standing (close to the ball he stays up between the small steps)
        still_from, still_step = clock(), steps
        parts.clear()
    return "stopped"


def _book():
    from .chase_pace import book_for_now
    b = book_for_now()
    print(f"pace ({b.key}): walk {b.walk_in_s():.1f} in/s; turns {b.turn_deg_s(-1, False):.1f} / {b.turn_deg_s(1, False):.1f} deg/s (left / right), pulses {b.turn_deg_s(-1, True):.1f} / {b.turn_deg_s(1, True):.1f}")
    return b


def stop_requested() -> bool:
    return os.path.exists(os.path.expanduser(STOP_FILE))


class _SnapshotCamera:
    def __init__(self, cam):
        self._cam = cam

    def refresh_exposure(self) -> None:
        """Make the next picture meter the light afresh (exposure balancing stays ON): the snapshot keeps a picture as it is when the light matches the last one, but a claw that has
        turned to another direction sees different light (user, 2026-10-31: adjust the exposure before taking pictures with the claw)."""
        try:
            self._cam._metered_at = float("-inf")
            self._cam._settled = None
        except Exception:  # noqa: BLE001
            pass

    def premeter(self, force: bool = False) -> None:
        """Meter the light in a background thread (one at a time) while G2 moves: the picture after the move then needs no metering while he stands still (CameraSnapshotter.premeter)."""
        fn = getattr(self._cam, "premeter", None)
        t = getattr(self, "_pre_thread", None)
        if not callable(fn) or (t is not None and t.is_alive()):
            return
        import threading
        self._pre_thread = threading.Thread(target=fn, kwargs={"force": force}, name="premeter", daemon=True)
        self._pre_thread.start()

    def look(self) -> bytes | None:
        drop = getattr(self._cam, "discard_one", None)
        if callable(drop):
            drop()                                       # the module returns the picture of the previous request: ask once and drop it, the second one is the scene now
        snap = self._cam.snapshot()                      # exposure balancing stays on (user, 2026-10-25)
        return snap.jpeg if snap is not None else None


CAMERA_WAIT_S = 30.0


def _wait_for_camera(port: str, wait_s: float | None = None, sleep=time.sleep, exists=os.path.exists, can_open=lambda p: os.access(p, os.R_OK | os.W_OK)) -> bool:
    """Whether the camera's serial port is there and can be opened, waiting up to `wait_s`. 2026-11-01: after a power-cycle the port was missing and then refused (permission) for over a minute,
    and the whole first attempt went to "no picture from the camera"."""
    end = time.monotonic() + (CAMERA_WAIT_S if wait_s is None else wait_s)
    while True:
        if exists(port) and can_open(port):
            return True
        if time.monotonic() >= end:
            return False
        sleep(1.0)


def _stand_if_lying(link, token: str = "kbalance") -> bool:
    """At the start of a session: read the pose once (`j`) and stand him up the way it needs: standing, nothing; the attention pose, `token` with the link set up to run the
    back-legs-first stand-up (the plain firmware stand-up out of it flipped him over, 2026-11-02); rest or a sit, `token` (the plain firmware stand-up is `kbalance`; `kup` is the
    firmware's neutral stand, claw_look --stand kup). An unreadable pose counts as lying (a stand-up from standing changes nothing; a missed one leaves him lying while he "searches",
    2026-11-01). Then a fixed wait, as before 2026-11-02: only the attention flow polls the board until it reads the stand. Never raises. Returns whether the pose could be read."""
    import re
    try:
        s = link._ser
        s.reset_input_buffer()
        s.write(b"j\n")
        time.sleep(1.0)
        rows = [r for r in s.read(s.in_waiting or 1).decode("ascii", "ignore").splitlines() if r.count(",") >= 15]
        j = [int(x) for x in re.findall(r"-?\d+", rows[-1])] if rows else None
        pose = classify_pose(j[:16] if j else None)
        if pose == "stand":                                   # (the old test, j[8] < 40 and j[12] > 30, read the REST pose as standing; it only worked because the raw read usually failed)
            return True
        # an unreadable pose (garbled serial reads, STATUS 15) counts as lying: a stand-up from standing changes nothing, a missed one leaves him lying while he "searches" (2026-11-01)
        print({"attention": "in the attention pose: standing up back legs first", "unknown": "could not read the pose: standing up first"}.get(pose, "lying down: standing up first"))
        if hasattr(link, "last_motion_command"):
            link.last_motion_command = {"attention": "kcalib", "sit": "ksit"}.get(pose, "krest")      # the link picks its stand-up from this: make it the pose just read
        link.send(token, read_reply=False, settle=0.0)
        if BETWEEN_MOVES == "attention":
            got = wait_for_pose(link, "stand")
            if got not in ("stand", "unknown"):
                print(f"stood up, but the board reads {got}")
        else:
            time.sleep(3.0)
        return j is not None
    except Exception as e:  # noqa: BLE001
        print("could not check the pose:", e)
        return False


def main() -> None:
    """The chase from the command line, inside a task scope (util/task_scope.py): what the settings file and the command line changed is put back when it ends."""
    from ..util.task_scope import task_scope
    with task_scope("ball chase"):
        _main()


def _main() -> None:
    global PUNT_MAX_IN, NUDGE_MAX_IN, NUDGES_BEFORE_PUNT, SEARCH_WALK
    import argparse
    ap = argparse.ArgumentParser(description="Chase the green ball and punt it until stopped.")
    ap.add_argument("--dry-run", action="store_true", help="look and report what it would do; send no move")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--max-seconds", type=float, default=None, help="end the attempt after this many seconds (he rests): a short test")
    ap.add_argument("--search-walk", action="store_true", help="after a full circle without the ball, walk on blind and search again (a big floor only; the default never walks without seeing the ball)")
    ap.add_argument("--use-pick", action="store_true", help="punt with Petoi's pick skill (it opens and closes the claw) instead of the punch (claw shut)")
    ap.add_argument("--punt-max", type=float, default=None, help="punt when the ball is this close (inches from the camera); default %s" % PUNT_MAX_IN)
    ap.add_argument("--nudge-max", type=float, default=None, help="between --punt-max and this: small steps closer first; default %s" % NUDGE_MAX_IN)
    ap.add_argument("--nudges", type=int, default=None, help="small steps closer before punting from out of range anyway; default %s" % NUDGES_BEFORE_PUNT)
    ap.add_argument("--punts", type=int, default=None, help="stop after this many punts (one attempt: walk up to the ball and punt it); default: until stopped")
    ap.add_argument("--save-to", default="~/.local/share/g2/explore_pictures/named/greenball", help="folder for the pictures with the ball found (where g2pics reads them)")
    args = ap.parse_args()
    try:
        from ..diag import memlog
        memlog.start("ball chase start")
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    import sys as _sys
    from . import punt_settings as _ps
    _self = _sys.modules[__name__]                           # this module as it is running (as __main__ too), so the settings land in the constants this run uses
    _eff, _problems = _ps.effective(_self)                  # the settings file (behavior/punt_settings.py) first: the command line below overrides it
    for _p in _problems:
        print("PUNT SETTINGS PROBLEM:", _p)
    if args.max_seconds is None:
        args.max_seconds = _eff["max_seconds"]
    if args.punt_max is not None:
        PUNT_MAX_IN = args.punt_max
    if args.nudge_max is not None:
        NUDGE_MAX_IN = args.nudge_max
    if args.nudges is not None:
        NUDGES_BEFORE_PUNT = args.nudges
    SEARCH_WALK = bool(args.search_walk) or SEARCH_WALK
    print(f"punt settings: punch at {PUNT_MAX_IN} in or closer, small steps ({NUDGE_S} s) from there out to {NUDGE_MAX_IN} in ({NUDGES_BEFORE_PUNT} of them before punching anyway), "
          f"walk steps aim for {WALK_AIM_IN} in, punch within {PUNT_ALIGN_DEG} deg of straight, lunge {PUNCH_LUNGE_S} s hold {PUNCH_HOLD_S} s, attempt limit {args.max_seconds:.0f} s, search walk {SEARCH_WALK}")
    from ..config import settings
    from ..link.serial_link import SerialLink
    from ..vision.snapshot import CameraSnapshotter
    p = Path(os.path.expanduser(STOP_FILE))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    link = SerialLink("/dev/serial0")
    link.connect()
    announce = None
    try:                                                 # the voice for "searching" / "target acquired"
        from ..voice.tts import make_tts
        _tts = make_tts("piper", piper_model_path=settings.piper_model_path, style=settings.voice_style)
        announce = lambda text: _tts.speak(text)         # noqa: E731
    except Exception as e:  # noqa: BLE001
        print("no voice (", e, "): the cues are printed only")
    if not _wait_for_camera(settings.vision_serial_port):
        print(f"THE CAMERA IS NOT THERE: {settings.vision_serial_port} did not appear or could not be opened within {CAMERA_WAIT_S:.0f} s. Check its USB plug. Nothing was moved.")
        raise SystemExit(4)
    pose_read = _stand_if_lying(link)
    if not pose_read and not args.dry_run:                # no pose AND no pack reading: the BiBoard is not answering (hung or off), and he would "search" for the whole attempt without moving (2026-11-01, three times)
        from ..power import battery as _battery
        _ok, _pct, _v = _battery.motion_gate(link)
        if _pct is None:
            print("THE BIBOARD IS NOT ANSWERING: no pose and no battery reading. It needs a power-cycle (switch it off, wait, switch it on). Nothing was moved.")
            raise SystemExit(3)
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump)
    trace: list = []
    robot = SerialRobot(link, use_pick=args.use_pick)
    walls_used, wall_check = None, None
    try:                                                                 # the walls goal ranks above the punt: its settings and (with a wall calibration from this hardware) the wall check
        from ..goals.standing import apply as _apply_standing
        from ..goals.walls import make_wall_check
        walls_used = _apply_standing("walls")
        if walls_used and "chase_wall_in" in walls_used:
            _self.CHASE_WALL_IN = float(walls_used["chase_wall_in"])      # run as a program this module is __main__, not the copy the walls goal set
        wall_check = make_wall_check()
        print("wall check:", "on" if wall_check else "off (no wall calibration at all, or walls do not rank above the punt)")
    except Exception as e:  # noqa: BLE001
        print("wall check off:", e)
    used = dict(_ps.defaults(_self), max_seconds=args.max_seconds)          # the settings this run uses (the file and the command line applied)
    t0 = time.monotonic()
    try:
        why = run_chase(robot, _SnapshotCamera(cam), stop_requested, saver=PictureSaver(args.save_to), dry_run=args.dry_run, max_steps=args.max_steps, max_punts=args.punts, max_seconds=args.max_seconds, announce=announce,
                        pace=None if args.dry_run else _book(), trace=trace, after_punt_look=bool(args.punts) and not args.dry_run, wall_check=wall_check)
        print("ended:", why)
        if not args.dry_run:
            try:
                from ..goals.standing import learn as _learn_standing
                from ..goals.walls import events_from_trace
                _learn_standing("walls", events_from_trace(trace), "ball chase", used=walls_used)
            except Exception:  # noqa: BLE001
                pass
        if args.punts == 1 and not args.dry_run:                         # one plain attempt teaches the ball-punt goal too (nothing is changed: goals/observe.py)
            from ..goals.observe import plain_punt
            said = plain_punt(trace, why, time.monotonic() - t0, used, getattr(robot, "last_pct", None))
            if said:
                print("counted for the ball goal:", said)
    except KeyboardInterrupt:
        print("ended: stopped")
    finally:
        cam.close()
        if not args.dry_run:                              # rest after each attempt (user, 2026-10-25); the next one stands him up first
            link.send("krest", read_reply=False, settle=0.0)
            time.sleep(2.5)


if __name__ == "__main__":
    main()
