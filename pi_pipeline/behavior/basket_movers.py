"""The movers for the basket line-up: turn the line-up's steps (inches, degrees) into the robot's timed moves (the basket goal, docs/plan-detail/basket-goal-plan.md).

`behavior/basket_lineup.py` decides; this module moves. A `BasketMover` wraps any robot that has the ball chase's `Robot` interface (`walk` / `walk_scripted`, `back`, `turn`), so every mode that can walk
uses the same paces and the same stops: the back-up is the ball goal's `kbkF` with the whole-cycle and eased stop, the turns are `Robot.turn` with a gyro-stopped line-up turn exactly as the ball goal's own line-up asks for it (the pivot cycles when the pivot gait is selected, the
arc pulse otherwise). Nothing here opens a serial port, calls an API or needs the camera.

Paces (hardwood, the arm fitted, the claw at its carry height):
- Back-up, MEASURED 2026-11-23 (nine runs, no falls, `docs/rl/real-walk-log.md`): a 1.0 s command moves him about 2.3 inches, 2.0 s about 9.3, 3.0 s about 15.3 (the first second covers little, each later second 6 to 7). He also drifts 1 to 5 inches to the right; the line-up looks again before every step and
  corrects that with a nudge, so the mover does not.
- Forward walk and turns: the ball goal's own pace book (`behavior/chase_pace.py`, self-measured per floor and hardware epoch): the walk covers nothing in its first WALK_START_S and then `walk_in_s` inches a second (a 2 s walk moved 10 inches on 2026-11-23 against 9.2 in/s of moving time in the book), and each turn side has its own rate for a long turn and a short pulse. Without a book the module uses the ball goal's defaults.
  The camera corrects whatever is left on the next look.
"""
from __future__ import annotations

from ..link import opencat
from . import ball_chase as chase
from . import chase_pace

BACK_POINTS = ((1.0, 2.3), (2.0, 9.3), (3.0, 15.3))     # (commanded seconds, inches moved): the measured back-up runs, means of three each
BACK_TAIL_IN_S = 6.0                                     # beyond the last measured run: the slope between the 2 s and 3 s runs
BACK_MIN_S = BACK_POINTS[0][0]                           # the shortest back-up measured (and the ball goal's own)
BACK_MAX_IN = 12.0                                       # a safety cap on one back-up step (the line-up asks for 6 at most)
FWD_MAX_IN = 12.0
TURN_FINISH_RETRIES, TURN_FINISH_BELOW, TURN_FINISH_MIN_DEG, TURN_FINISH_PROGRESS_DEG = 2, 0.6, 3.0, 0.5   # a turn that got under 60 percent of its ask (and left at least 3 degrees) is finished up to twice in the same move; a finish that moved under 0.5 degrees ends it
PIVOT_MIN_IN, PIVOT_MAX_IN, PIVOT_DISTANCE_IN = 8.0, 40.0, 20.0    # every basket-run turn is the in-place pivot: a distance outside 8 to 40 inches, or none at all (a scan with nothing in view), would pick the walking arc, which creeps forward (2026-11-23: a scan and a turn toward a puck 5.6 inches away walked him from 16 inches to 7 inches of the basket)
ARC_RATE_DEG_S = 9.5                                     # the walking arc's real turn rate, the same each way (measured 2026-11-24 with a ruler, five arcs of 90 degrees asked: about 90 degrees in 10 s)
ARC_MAX_DEG = 57.0                                       # a safety cap on one wide arc (the circling search asks for 45): 57 degrees is 6 s, the longest turn the robot runs
TURN_MAX_DEG = 60.0                                      # a safety cap on one turn step (the line-up asks for 54 at most: two pivot cycles)


def back_seconds(inches: float) -> float:
    """Commanded seconds for a back-up of `inches`, from the measured runs (never under the shortest measured run)."""
    inches = min(max(inches, 0.0), BACK_MAX_IN)
    (s0, d0), (s1, d1), (s2, d2) = BACK_POINTS
    if inches <= d0:
        return s0
    if inches <= d1:
        return s0 + (inches - d0) / (d1 - d0) * (s1 - s0)
    if inches <= d2:
        return s1 + (inches - d1) / (d2 - d1) * (s2 - s1)
    return s2 + (inches - d2) / BACK_TAIL_IN_S


def back_inches(seconds: float) -> float:
    """What a back-up of `seconds` moves him, the same table read the other way (for logging and the tests)."""
    (s0, d0), (s1, d1), (s2, d2) = BACK_POINTS
    if seconds <= s0:
        return d0
    if seconds <= s1:
        return d0 + (seconds - s0) / (s1 - s0) * (d1 - d0)
    if seconds <= s2:
        return d1 + (seconds - s1) / (s2 - s1) * (d2 - d1)
    return d2 + (seconds - s2) * BACK_TAIL_IN_S


def forward_seconds(inches: float, pace_in_s: float | None = None) -> float:
    """Commanded seconds for a forward walk of `inches`: the walk's slow start plus the inches at the pace book's walk pace (never under the shortest move that moves him)."""
    pace = pace_in_s or chase_pace.DEFAULTS["walk_in_s"]
    return max(chase.MIN_MOVE_S, chase_pace.WALK_START_S + min(max(inches, 0.0), FWD_MAX_IN) / pace)


class BasketMover:
    """scan(deg), pivot(deg), nudge(deg) (+ to the right), forward(inches), back(inches): each one step, then still. `state` is the robot's answer to the last step ("fell" ends the line-up)."""

    def __init__(self, robot, say=print, book=None):
        self.robot, self.say, self.state, self.book = robot, say, "ok", book           # book: the ball goal's PaceBook (chase_pace.book_for_now()); None = the ball goal's defaults

    def set_distance(self, inches: float | None) -> None:
        """How far the target was at the decision the next turn belongs to. The ball goal's run loop sets `robot.lineup_ball_in` before every line-up turn; without it `opencat.lineup_tokens` has no distance and always picks the walking arc turn (`kwkR` / `kwkL`), which creeps FORWARD while it turns: 2026-11-23 the line-up's "pivots" all moved him toward the basket and it never aligned. With a distance of 8 to 40 inches the turn is the in-place pivot."""
        self.robot.lineup_ball_in = PIVOT_DISTANCE_IN if inches is None else min(max(float(inches), PIVOT_MIN_IN), PIVOT_MAX_IN)

    def _rate(self, degrees: float, pulse: bool) -> float:
        side = 1 if degrees > 0 else -1
        if self.book is not None:
            return self.book.turn_deg_s(side, pulse)
        return chase_pace.DEFAULTS["pulse_deg_s" if pulse else "turn_deg_s"]

    def _turn(self, degrees: float, pulse: bool) -> str:
        want = min(abs(degrees), TURN_MAX_DEG)
        if want <= 0:
            return self.state
        rate = self._rate(degrees, pulse)
        signed = want if degrees > 0 else -want
        self.state = self._gyro_turn(signed, want, rate)
        for _ in range(TURN_FINISH_RETRIES):                       # a gyro-stopped turn that ended on its time cap having turned far less than asked (2026-11-27 drill: 12.9 asked, 0.2 got; 16.1 asked, 0.3 got; 19 of 41 turns got under 60 percent) is finished now from where it stopped, not after a new picture and a second decision (about 6 seconds standing each)
            got = getattr(self.robot, "last_turn_deg", None)
            if self.state == "fell" or got is None or got >= TURN_FINISH_BELOW * want or want - got < TURN_FINISH_MIN_DEG:
                break
            want -= got
            signed = want if degrees > 0 else -want
            self.state = self._gyro_turn(signed, want, rate)
            if (getattr(self.robot, "last_turn_deg", None) or 0.0) < TURN_FINISH_PROGRESS_DEG:
                break                                                # it is not moving: leave it to the next look
        return self.state

    def _gyro_turn(self, signed: float, want: float, rate: float) -> str:
        try:
            self.robot.last_turn_deg = None                          # so a turn that is not gyro-stopped is never read as the last one's result
        except AttributeError:
            pass
        return self.robot.turn(signed, max(chase.MIN_MOVE_S, want / rate), stop_deg=want)

    def scan(self, degrees: float) -> str:
        return self._turn(degrees, pulse=abs(degrees) < chase.PIVOT_MIN_DEG)

    pivot = scan

    def nudge(self, degrees: float) -> str:
        return self._turn(degrees, pulse=abs(degrees) < chase.PIVOT_MIN_DEG)

    def arc(self, degrees: float) -> str:
        """A wide turn: the firmware's walking arc (`kwkL` / `kwkR`), TIMED, not gyro-stopped (the circling search, owner 2026-11-24). Measured the same day with a ruler (g2turncal, two 90 degree arcs a run): the arc turns about ARC_RATE_DEG_S degrees a second on a radius near 15 inches and about 2.5 inches a second,
        the same to the right and to the left, while the gyro counted 0.13 to 0.16 of a real right turn and 1.8 times a real left turn, so a gyro stop never fired on the right and cut the left short. The arc runs `degrees / ARC_RATE_DEG_S` seconds (the whole-cycle stop may add a little), with the firmware walking-turn skills forced
        (never the pivot). `last_arc_deg` is what was ASKED (the lap is counted from it), `last_arc_s` the commanded seconds, `last_arc_gyro_deg` what the gyro said (logged, not used)."""
        want = min(abs(degrees), ARC_MAX_DEG)
        if want <= 0:
            return self.state
        self.robot.lineup_ball_in = None
        signed = want if degrees > 0 else -want
        secs = want / ARC_RATE_DEG_S
        saved = getattr(self.robot, "turn_tokens", None)
        if saved is not None:
            self.robot.turn_tokens = tuple(opencat.ARCS)                  # (right, left): the firmware arcs, whatever G2_TURN_GAIT says
        try:
            self.state = self.robot.turn(signed, secs, stop_deg=0.0)
        finally:
            if saved is not None:
                self.robot.turn_tokens = saved
        done = getattr(self.robot, "last_turn_deg", None)
        self.last_arc_gyro_deg = None if not done else abs(float(done))
        self.last_arc_deg, self.last_arc_s = want, round(secs, 2)
        return self.state

    def forward(self, inches: float) -> str:
        secs = forward_seconds(inches, self.book.walk_in_s() if self.book is not None else None)
        walk = self.robot.walk_scripted if hasattr(self.robot, "walk_scripted") else self.robot.walk
        self.state = walk(secs)
        return self.state

    def back(self, inches: float) -> str:
        self.state = self.robot.back(back_seconds(inches))
        return self.state
