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
WALK_AIM_IN = 4.0              # a walk step is timed to leave the ball about this far from the camera (the ball is touched at about 3 in)
NUDGES_BEFORE_PUNT = 3      # camera to ball, measured 2026-10-25: the ball at 2.6 in is a good punt (the claw hits it first and it goes straight ahead); at 4.5 in it is too far to be hit
WALK_MAX_S = 3.0               # one walk step: then look again
SEARCH_STEP_DEG = 20.0          # (was 35: a wrong turn away from a ball that was only missed once cost 6 s and the ball)
SEARCH_WALK = False            # walk on blind after a full circle without the ball (off: only on a big floor, `--search-walk`)
AFTER_PUNT_SETTLE_S = 1.0      # after the punch, before the picture that says where the ball went
LOST_LOOKS = 3                 # real misses in a row before searching starts; a missing picture is not a miss
SEARCH_STEPS_PER_CIRCLE = 10
MAX_TURN_DEG = 35.0
MIN_MOVE_S = 1.2               # a gait started and stopped for less than this does not move him
CLOSE_IN_IN = 4.0              # after a punt that left the ball farther than this, step closer before the next one (2026-10-25: a punt from 4.5 to 7 in was too far, from 2.6 in it threw the ball 18 in)
STUCK_PUNTS = 3                # punts with the ball still in range before backing up
BACK_UP_S = 2.0
SAVE_EVERY_S = 2.0
BACK_BUDGET_S = 6.0            # the most backing up in one attempt (search moves, stuck punts and a vanished ball together): there is no edge detector, so keep it small on a desk (0 = never back up)
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
}
SEARCH_ORDER = "claw_scan"     # the claw look first: it sees the most for the least moving (user, 2026-10-31)
SEARCH_MOVE_MAX_S = 2.0        # the longest search turn before the next picture (user, 2026-11-01: a few steps, then look again)
SCAN_TURN_DEG = 60.0           # a turn step between two claw looks (a claw look covers about 2 x CLAW_PAN_DEG plus the camera's own view)

# The claw look: the arm's pan (joint 0) and lift (joint 1) point the camera; legs stay where they are. A positive lift swings the claw forward, out and up.
CLAW_PAN_DEG = 35.0
CLAW_LIFT_DEG = 15.0
CLAW_PAN_SIGN = "right"        # which way a positive pan turns the camera (NOT yet checked on G2: `python -m pi_pipeline.behavior.claw_look --calibrate` measures it with the ball)
CLAW_DEG_S = 60.0              # how fast the arm moves for a look (below the 80 deg/s cap on eased moves)
CLAW_STEPS_PER_S = 40
CLAW_SETTLE_S = 0.6            # still before the picture

# The walk is always the learned default gait policy (the attachment's saved gait: ARM1X with the arm), never switched (user, 2026-10-31). Its pace and the turn rates are measured by
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
ALIGN_PULSE_MAX_S = 1.6
ALIGN_TRIES = 3
WHEN_MISALIGNED = "punch"      # after ALIGN_TRIES pulses and still off: "punch" anyway or "back_up" and line up again


def claw_pan_body(pan: float) -> float:
    """The camera's direction, + = G2's right, for an arm pan of `pan` degrees."""
    return pan if CLAW_PAN_SIGN == "right" else -pan
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


@dataclass
class ChasePlanner:
    last_side: int = 0         # +1 the ball was last seen to the right, -1 to the left, 0 never
    lost: int = 0              # looks in a row without the ball
    search_steps: int = 0
    punts_in_range: int = 0
    after_punt: bool = False   # the last action was a punt
    nudges: int = 0            # small steps closer taken since the ball was last far or in reach
    last_dist: float | None = None   # how far the ball was when it was last seen (None once acted on)
    punt_log: list = field(default_factory=list)   # (distance in, bearing deg) of the ball at each punt the planner asked for (None: it had vanished at close range)
    walk_log: list = field(default_factory=list)   # (distance in, seconds) of each walk step
    log: list = field(default_factory=list)
    claw_ok: bool = True       # the robot can move the arm for a claw look (run_chase sets it from the robot)
    search_i: int = 0          # moves into the current search
    back_s: float = 0.0        # seconds backed up this attempt (BACK_BUDGET_S caps it)
    claw_side: int = 0         # which side the claw look starts on (the side the ball was last seen)
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
        if not self.claw_ok:
            once, cycle = tuple(m for m in once if m != "claw"), tuple(m for m in cycle if m != "claw")
        return once, (cycle or ("turn",))

    def _can_back(self, seconds: float) -> bool:
        return self.back_s + seconds <= BACK_BUDGET_S + 1e-9

    def _back(self, kind: str, seconds: float, why: str) -> Action:
        self.back_s += seconds
        return Action(kind, seconds, why=why)

    def _search_move(self) -> Action:
        once, cycle = self._order()
        for _ in range(len(once) + 2 * len(cycle) + 1):                # a move that cannot be made (no back-up left) is skipped
            i = self.search_i
            self.search_i += 1
            move = once[i] if i < len(once) else cycle[(i - len(once)) % len(cycle)]
            side = self.last_side or 1
            if move == "claw":
                self.claw_side = side
                return Action("claw_look", why=f"searching: a look around with the claw, {'right' if side > 0 else 'left'} first")
            if move == "back":
                if self._can_back(BACK_UP_S):
                    return self._back("search_back", BACK_UP_S, "searching: back up to see more of the floor")
                continue
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
            return Action("search_turn", secs, secs * rate * side, f"searching {'right' if side > 0 else 'left'}")
        return Action("look", 1.0, why="searching: nothing left to try this round, look again")

    def _wall_turn(self, wall: "WallSeen", why: str) -> Action:
        side = 1 if wall.turn == "right" else -1
        deg = wall_turn_deg() * side
        return Action("wall_turn", abs(deg) / self._turn_rate(side, False), deg, why)

    def decide(self, ball: BallReading | None, wall: "WallSeen | None" = None) -> Action:
        if ball is None:
            self.lost += 1
            self.punts_in_range = 0
            self.nudges = 0
            if self.last_dist is not None and self.last_dist <= NUDGE_MAX_IN:      # it was right there and now it is gone: at the claw, too close for the camera to see (user, 2026-10-25: right in front of the ball and no punt, then a turn away)
                self.last_dist = None
                self.lost = 0
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
        if wall is not None and wall.nearest_in is not None and ball.distance_in > NUDGE_MAX_IN:   # walls rank above the punt; but with the ball within a few inches lining up and punching
            # goes no closer to the wall, and the wall reading is not calibrated for the claw camera (user, 2026-11-01: he turned away from a ball right in front of him)
            behind = wall.near_ball_in
            if behind is not None and ball.distance_in < behind and behind - ball.distance_in < CHASE_WALL_IN - BALL_TOUCH_IN:
                self.by_wall += 1
                if self.by_wall >= WALL_GIVE_UP:
                    return Action("give_up", why=f"the ball is {behind - ball.distance_in:.0f} in from a wall: too close to reach without getting nearer than {CHASE_WALL_IN:.0f} in to the wall")
                return Action("look", 1.0, why=f"the ball looks {behind - ball.distance_in:.0f} in from a wall: look again")
            self.by_wall = 0
            if wall.nearest_in <= CHASE_WALL_IN:
                self.wall_turns += 1
                if self.wall_turns >= WALL_TURNS_GIVE_UP:
                    return Action("give_up", why=f"{self.wall_turns} turns away from walls with the ball in sight: walls keep me from it")
                return self._wall_turn(wall, f"a wall {wall.nearest_in:.0f} in ahead: turn away")
        else:
            self.by_wall = 0
        self.last_dist = ball.distance_in
        self.last_side = 1 if ball.bearing_deg >= 0 else -1
        near = ball.distance_in <= NUDGE_MAX_IN
        in_reach = ball.distance_in <= PUNT_MAX_IN
        if near and not in_reach and abs(ball.bearing_deg) <= PUNT_ALIGN_DEG and self.nudges < NUDGES_BEFORE_PUNT:
            self.nudges += 1
            self.after_punt = False
            return Action("walk", NUDGE_S, why=f"ball {ball.distance_in:.1f} in ahead, just out of reach: a small step closer ({self.nudges} of {NUDGES_BEFORE_PUNT})")
        if not near:
            self.align_turns = 0
        if near and abs(ball.bearing_deg) > PUNT_ALIGN_DEG:
            if self.align_turns < ALIGN_TRIES:                  # a small turn, then a new picture (the camera checks every pulse)
                self.align_turns += 1
                side = 1 if ball.bearing_deg > 0 else -1
                secs = max(ALIGN_PULSE_MIN_S, min(ALIGN_PULSE_MAX_S, abs(ball.bearing_deg) / self._turn_rate(side, True)))
                return Action("align", secs, float(ball.bearing_deg), f"ball {ball.bearing_deg:+.0f} deg off at {ball.distance_in:.0f} in: a small turn to line the claw up ({self.align_turns} of {ALIGN_TRIES})")
            if WHEN_MISALIGNED == "back_up" and self._can_back(BACK_UP_S):
                self.align_turns = 0
                return self._back("back", BACK_UP_S, f"still {ball.bearing_deg:+.0f} deg off after {ALIGN_TRIES} small turns: back up and line up again")
        elif abs(ball.bearing_deg) > (PUNT_ALIGN_DEG if near else ALIGN_DEG):
            deg = max(-MAX_TURN_DEG, min(MAX_TURN_DEG, ball.bearing_deg))
            side = 1 if deg > 0 else -1
            return Action("turn", max(MIN_MOVE_S, abs(deg) / self._turn_rate(side, False)), deg, f"ball {ball.bearing_deg:+.0f} deg off straight: turn")
        if near and self.after_punt and ball.distance_in > CLOSE_IN_IN:
            self.after_punt = False
            return Action("walk", 0.9, why=f"ball still {ball.distance_in:.0f} in away after the punt: step closer")
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
    def turn(self, degrees: float, seconds: float) -> str: ...
    def back(self, seconds: float) -> str: ...
    def punt(self) -> str: ...
    def battery_ok(self) -> bool: ...
    # optional: def claw_pose(self, pan: float, lift: float) -> str   (a robot without it never gets a claw look)


class Camera(Protocol):
    def look(self) -> bytes | None: ...


class SerialRobot:
    """The firmware skills over the serial link. Every move ends in a balanced stand (`kbalance`); the link sends `gb` after each skill. Each returns "ok" or "fell"."""

    def __init__(self, link, poll_imu=None, fall_deg: float = 45.0, sleep=time.sleep, clock=time.monotonic, use_pick: bool = False):
        self._lk, self._sleep, self._clock = link, sleep, clock
        self.use_pick = use_pick                          # True: `kpickF`, the pick skill (it opens and closes the claw); the default is the punch
        self._fall_rad = math.radians(fall_deg)
        self._pitch, self._roll = [], []
        self._claw = (0.0, 0.0)                           # (pan, lift) the arm was last sent to by a claw look; every walk, turn and punch starts from (0, 0)
        self._walker = None
        self.bumped = False                               # the last walk ended on a bump (the IMU contact signal)

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
            self._pitch.append(math.degrees(r[1]))
            self._roll.append(math.degrees(r[0]))
            if max(abs(r[0]), abs(r[1])) > self._fall_rad:
                return True
        return False

    def swing_deg(self) -> float:
        """How far the body tilted during the last skill (the larger of the pitch and roll ranges): 0 when it never moved."""
        rng = lambda v: (max(v) - min(v)) if len(v) > 1 else 0.0   # noqa: E731
        return max(rng(self._pitch), rng(self._roll))

    def _skill(self, token: str, seconds: float) -> str:
        self._pitch, self._roll = [], []
        self._tx("gP")
        self._tx(token)
        t0, state = self._clock(), "ok"
        while self._clock() - t0 < seconds:
            if self._fell():
                state = "fell"
                break
            self._sleep(0.05)
        if state == "ok":
            self._tx("kbalance")
            self._sleep(1.0)
        self._tx("gp")
        return state

    def walk(self, seconds: float) -> str:
        return self._policy_walk(seconds)                 # always the default gait policy (user, 2026-10-31)

    def _policy_walk(self, seconds: float) -> str:
        """The learned walk (the attachment's saved gait) for `seconds`, ending in a balanced stand. "fell" if it ended in a fall. A bump (the walk's IMU contact signal, the same one
        exploration uses) stops the walk at once and sets `bumped` (the walls goal counts it)."""
        from ..gait.policy_walker import PolicyWalker
        fell, hit = [], []
        if self._walker is None:
            self._walker = PolicyWalker(self._lk, hold_between_legs=True, on_fall=lambda: fell.append(1), on_contact=lambda ev=None: hit.append(ev))
        else:
            self._walker._on_fall = lambda: fell.append(1)
            self._walker._on_contact = lambda ev=None: hit.append(ev)
        self.bumped = False
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
        return "fell" if fell else "ok"

    def claw_pose(self, pan: float, lift: float) -> str:
        """Move the arm (pan joint 0, lift joint 1) to point the camera, at CLAW_DEG_S, watching the IMU. The legs are not sent. "ok" or "fell"."""
        pan = max(-45.0, min(45.0, float(pan)))
        lift = max(0.0, min(40.0, float(lift)))
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

    def turn(self, degrees: float, seconds: float) -> str:
        return self._skill("kwkR" if degrees > 0 else "kwkL", seconds)

    def back(self, seconds: float) -> str:
        return self._skill("kbkF", seconds)

    def _pose_cmd(self, lift, sh, kn) -> str:
        return f"i1 {int(round(lift))} 2 0 8 {int(round(sh[0]))} 9 {int(round(sh[1]))} 10 {int(round(sh[2]))} 11 {int(round(sh[3]))} 12 {int(round(kn[0]))} 13 {int(round(kn[1]))} 14 {int(round(kn[2]))} 15 {int(round(kn[3]))}"

    def punch(self) -> str:
        """The lunge with the claw shut (PUNCH_KEYS), played as `i` commands at 40 a second from the pose he stands in, then back to the balance pose. No firmware skill is sent."""
        from ..link import transitions
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
        return "ok"

    def punt(self) -> str:
        if not self.use_pick:
            state = self.punch()
            if state == "ok" and self.swing_deg() < PUNT_MIN_SWING_DEG:       # the lunge tilts the body 15 deg or more; if he barely moved it did not play: once more
                log.warning("the punch barely moved him (%.1f deg): once more", self.swing_deg())
                state = self.punch()
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
        name = time.strftime(f"greenball_{tag}_%H%M%S")
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


def claw_scan(robot, camera, planner: ChasePlanner, *, saver=None, sleep=time.sleep, say: Callable[[str], None] = print, trace: list | None = None,
              stamp: Callable[[], float] | None = None, after_punt: bool = False) -> tuple[str, BallReading | None]:
    """One look around with the arm: the camera to one side, the other side, and (with the lift up) straight ahead, a picture at each; stops at the first sight of the ball. The arm goes back
    to (0, 0) at the end. Returns (state, the ball with its bearing turned into G2's own direction, or None). `stamp()` times the trace entries (the scorer needs when the ball was
    first seen); `after_punt` marks a look for where the ball went, which is not a search."""
    extra = {"after_punt": True} if after_punt else {}
    fresh = getattr(camera, "refresh_exposure", None)
    if callable(fresh):
        fresh()                                                                      # one exposure check before the whole look around (user, 2026-10-31), not one per picture
    side = planner.claw_side or planner.last_side or 1
    pans = [side * CLAW_PAN_DEG, -side * CLAW_PAN_DEG] + ([0.0] if CLAW_LIFT_DEG > 0 else [])
    found, state = None, "ok"
    for pan in pans:
        state = robot.claw_pose(pan, CLAW_LIFT_DEG)
        if state == "fell":
            break
        sleep(CLAW_SETTLE_S)
        jpeg = camera.look()
        ball = find_ball(jpeg) if jpeg else None
        if ball is not None:
            if saver is not None:
                saver.maybe_save(jpeg, ball, tag="claw")
            found = dataclasses.replace(ball, bearing_deg=ball.bearing_deg + claw_pan_body(pan))
            if trace is not None:
                trace.append({"kind": "claw_seen", "pan": pan, "lift": CLAW_LIFT_DEG, "cam_bearing": round(ball.bearing_deg, 1), "distance_in": round(ball.distance_in, 1),
                              **({"t": stamp()} if stamp else {}), **extra})
            say(f"   claw look at pan {pan:+.0f} lift {CLAW_LIFT_DEG:.0f}: ball {ball.distance_in:.0f} in, {found.bearing_deg:+.0f} deg from straight ahead")
            break
    if state != "fell":
        state = robot.claw_pose(0.0, 0.0)
    if trace is not None:
        trace.append({"kind": "claw_look", "found": found is not None, "state": state, **({"t": stamp()} if stamp else {}), **extra})
    return state, found


TURN_CAUSE = {"wall_turn": "a wall ahead", "search_turn": "searching: no ball in sight", "align": "lining the claw up on a close ball", "turn": "the ball off to one side"}
TURN_LOG = "~/.local/share/g2/turn_log.jsonl"


def log_turn(act, ball, wall, state: str) -> None:
    """One line per turn in TURN_LOG (user, 2026-11-01: every turn and why, to debug him turning away from a ball): the cause, the reason in words, which way and how far,
    and what he saw (the ball and the wall reading) when he decided. Never raises."""
    try:
        path = os.path.expanduser(os.environ.get("G2_TURN_LOG", TURN_LOG))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": act.kind, "cause": TURN_CAUSE.get(act.kind, act.kind), "why": act.why,
               "direction": "right" if act.degrees > 0 else "left", "degrees": round(act.degrees, 1), "seconds": round(act.seconds, 2), "state": state,
               "ball": _ball_dict(ball), "wall_in": None if wall is None or wall.nearest_in is None else round(wall.nearest_in, 1)}
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _ball_dict(ball: BallReading | None):
    return None if ball is None else {"distance_in": round(ball.distance_in, 1), "bearing_deg": round(ball.bearing_deg, 1), "edge": ball.touches_edge}


def run_chase(robot: Robot, camera: Camera, stop: Callable[[], bool], *, planner: ChasePlanner | None = None, saver: PictureSaver | None = None, dry_run: bool = False, announce: Callable[[str], None] | None = None,
              settle_s: float = 1.0, sleep=time.sleep, max_steps: int | None = None, max_punts: int | None = None, max_seconds: float | None = None, clock=time.monotonic, say: Callable[[str], None] = print,
              trace: list | None = None, after_punt_look: bool = False, pace=None, wall_check=None) -> str:
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

    while not stop():
        if max_steps is not None and steps >= max_steps:
            return "steps"
        if max_seconds is not None and clock() - t_start >= max_seconds:
            say(f"time is up ({max_seconds:.0f} s): ending the attempt")
            return "time"
        steps += 1
        if steps % 15 == 1 and not dry_run and not robot.battery_ok():
            say("battery low or unreadable: stopping")
            return "battery"
        wall = None
        if pending is not None:
            ball, pending = pending, None
            last_move = None                              # a claw-look reading is from another camera pose: not a before / after pair
        else:
            sleep(settle_s)                                   # let the body stop swaying before the picture
            jpeg = camera.look()
            if not jpeg:                                      # the camera gave no picture: that says nothing about the ball (2026-10-25: counting it as a miss sent him turning away from a ball straight ahead)
                say(f"[{steps}] no picture from the camera: looking again")
                note(kind="no_picture")
                continue
            ball = find_ball(jpeg)
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
                    wall = wall_check(jpeg, ball)
                except Exception:  # noqa: BLE001
                    wall = None
        note(kind="look", ball=_ball_dict(ball), **({"wall_in": None if wall.nearest_in is None else round(wall.nearest_in, 1)} if wall is not None else {}))
        if announce is not None:                          # real-time signal of what he sees (user, 2026-10-25): "searching" when a search starts, "target acquired" when the ball is found again
            if ball is not None and (planner.lost > 0 or planner.search_steps > 0 or planner.search_i > 0 or not seen):
                announce("target acquired")
            elif ball is None and planner.lost + 1 == LOST_LOOKS:                       # the look that starts a search
                announce("searching")
        seen = seen or ball is not None
        act = planner.decide(ball, wall)
        if wall is not None and wall.nearest_in is not None and act.kind in ("walk", "search_walk"):      # never walk closer than CHASE_WALL_IN to a wall
            from .chase_pace import WALL_PACE_START_S
            room = wall.nearest_in - CHASE_WALL_IN
            if room <= 0.5:
                act = planner._wall_turn(wall, f"a wall {wall.nearest_in:.0f} in ahead: turn away instead of walking")
            else:
                cap = WALL_PACE_START_S + room / planner._walk_pace()
                if act.seconds > cap:
                    act = Action(act.kind, round(cap, 2), act.degrees, act.why + f" (cut short: a wall {wall.nearest_in:.0f} in ahead)")
        say(f"[{steps}] {'ball ' + format(ball.distance_in, '.0f') + ' in ' + format(ball.bearing_deg, '+.0f') + ' deg' if ball else 'no ball'} -> {act.kind}: {act.why}")
        if dry_run or act.kind == "look":
            note(kind="act", act=act.kind, why=act.why)
            if act.kind == "look":
                sleep(act.seconds)
            continue
        if act.kind == "give_up":
            note(kind="wall", event="ball_by_wall", wall_in=None if wall is None else wall.nearest_in, why=act.why)
            say(act.why)
            return "ball_by_wall"
        if act.kind == "claw_look":
            state, pending = claw_scan(robot, camera, planner, saver=saver, sleep=sleep, say=say, trace=trace, stamp=lambda: round(clock() - t_start, 2))
            note(kind="act", act="claw_look", why=act.why, state=state, found=pending is not None)
            if state == "fell":
                say("G2 fell: stopping (fall recovery is off)")
                return "fell"
            continue
        if act.kind == "wall_turn":
            note(kind="wall", event="steer", wall_in=None if wall is None else wall.nearest_in, why=act.why)
            state = robot.turn(act.degrees, act.seconds)
        elif act.kind in ("turn", "search_turn", "align"):
            state = robot.turn(act.degrees, act.seconds)
            if ball is not None:
                last_move = ("turn", act.seconds, act.degrees, ball)
        elif act.kind in ("walk", "search_walk"):
            state = robot.walk(act.seconds)
            if getattr(robot, "bumped", False):
                note(kind="wall", event="bump", wall_in=None if wall is None else wall.nearest_in, why="bumped into something while walking")
                say(f"[{steps}] bumped into something while walking: backing off")
                if state != "fell" and planner._can_back(VANISH_BACK_S):         # off the wall first (as exploration's hit sequence does); the next look decides the turn
                    planner.back_s += VANISH_BACK_S
                    state = robot.back(VANISH_BACK_S)
                last_move = None
                ball = None                                                       # no pace sample from a walk that ended on a bump
            if ball is not None and act.kind == "walk":
                last_move = ("walk", act.seconds, 0.0, ball)
        elif act.kind in ("back", "search_back"):
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
                    camera.look()
                    jpeg = camera.look()
                    after = find_ball(jpeg) if jpeg else None
                    note(kind="after_punt", ball=_ball_dict(after), picture=bool(jpeg))
                say(f"punted {punts}: done")
                say(f"ATTEMPT: punted at {planner.punt_log[-1] if planner.punt_log else '?'} (in, deg) after {steps} looks; walk steps (ball in, seconds): {planner.walk_log}")
                return "punted"
            if state == "fell":
                say("G2 fell: stopping (fall recovery is off)")
                return "fell"
            continue
        else:
            state = "ok"
        note(kind="act", act=act.kind, why=act.why, state=state, seconds=round(act.seconds, 2), degrees=round(act.degrees, 1))
        if act.kind in TURN_CAUSE:
            log_turn(act, ball, wall, state)
        if state == "fell":
            say("G2 fell: stopping (fall recovery is off)")
            return "fell"
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

    def look(self) -> bytes | None:
        snap = self._cam.snapshot()                      # exposure balancing stays on (user, 2026-10-25)
        return snap.jpeg if snap is not None else None


def _stand_if_lying(link, token: str = "kbalance") -> None:
    """If the legs read the rest pose, stand him up with `token` (the plain firmware stand-up is `kbalance`; `kup` is the firmware's neutral stand: claw_look --stand kup compares them,
    2026-11-01, when his legs went limp about 10 s after our stand-up and not after the board's own). Never raises."""
    import re
    try:
        s = link._ser
        s.reset_input_buffer()
        s.write(b"j\n")
        time.sleep(1.0)
        rows = [r for r in s.read(s.in_waiting or 1).decode("ascii", "ignore").splitlines() if r.count(",") >= 15]
        j = [int(x) for x in re.findall(r"-?\d+", rows[-1])] if rows else None
        if j is not None and not (j[8] < 40 and j[12] > 30):
            return
        # an unreadable pose (garbled serial reads, STATUS 15) counts as lying: a stand-up from standing changes nothing, a missed one leaves him lying while he "searches" (2026-11-01)
        print("lying down: standing up first" if j is not None else "could not read the pose: standing up first")
        link.send(token, read_reply=False, settle=0.0)
        time.sleep(3.0)
    except Exception as e:  # noqa: BLE001
        print("could not check the pose:", e)


def main() -> None:
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
    _stand_if_lying(link)
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
