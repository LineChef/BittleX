"""The movers for the basket line-up: turn the line-up's steps (inches, degrees) into the robot's timed moves (the basket goal, docs/plan-detail/basket-goal-plan.md).

`behavior/basket_lineup.py` decides; this module moves. A `BasketMover` wraps any robot that has the ball chase's `Robot` interface (`walk` / `walk_scripted`, `back`, `turn`), so every mode that can walk
uses the same paces and the same stops: the back-up is the ball goal's `kbkF` with the whole-cycle and eased stop, the turns are `Robot.turn` with a gyro-stopped line-up turn exactly as the ball goal's own line-up asks for it (the pivot cycles when the pivot gait is selected, the
arc pulse otherwise). Nothing here opens a serial port, calls an API or needs the camera.

Paces (hardwood, the arm fitted, the claw at its carry height):
- Back-up, MEASURED 2026-11-23 (nine runs, no falls, `docs/rl/real-walk-log.md`): a 1.0 s command moves him about 2.3 inches, 2.0 s about 9.3, 3.0 s about 15.3 (the first second covers little, each later second 6 to 7). He also drifts 1 to 5 inches to the right; the line-up looks again before every step and
  corrects that with a nudge, so the mover does not.
- Forward walk: 3.0 inches per commanded second, the median of 116 ball-goal walks that started 10 inches or more from the ball (it includes the walk's slow first second). NOT yet measured with a ruler: the line-up-alone test checks it.
- Turns: 28 degrees a second for a pivot or scan turn and 20.5 for a small pulse, the ball goal's own turn paces (`behavior/chase_pace.py`); the camera corrects whatever is left on the next look.
"""
from __future__ import annotations

from . import ball_chase as chase

BACK_POINTS = ((1.0, 2.3), (2.0, 9.3), (3.0, 15.3))     # (commanded seconds, inches moved): the measured back-up runs, means of three each
BACK_TAIL_IN_S = 6.0                                     # beyond the last measured run: the slope between the 2 s and 3 s runs
BACK_MIN_S = BACK_POINTS[0][0]                           # the shortest back-up measured (and the ball goal's own)
BACK_MAX_IN = 12.0                                       # a safety cap on one back-up step (the line-up asks for 6 at most)
FWD_IN_S, FWD_MIN_S, FWD_MAX_IN = 3.0, 0.9, 12.0
TURN_DEG_S, PULSE_DEG_S = 28.0, 20.5
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


def forward_seconds(inches: float) -> float:
    return max(FWD_MIN_S, min(max(inches, 0.0), FWD_MAX_IN) / FWD_IN_S)


class BasketMover:
    """scan(deg), pivot(deg), nudge(deg) (+ to the right), forward(inches), back(inches): each one step, then still. `state` is the robot's answer to the last step ("fell" ends the line-up)."""

    def __init__(self, robot, say=print):
        self.robot, self.say, self.state = robot, say, "ok"

    def _turn(self, degrees: float, pulse: bool) -> str:
        want = min(abs(degrees), TURN_MAX_DEG)
        if want <= 0:
            return self.state
        rate = PULSE_DEG_S if pulse else TURN_DEG_S
        signed = want if degrees > 0 else -want
        self.state = self.robot.turn(signed, max(chase.MIN_MOVE_S, want / rate), stop_deg=want)
        return self.state

    def scan(self, degrees: float) -> str:
        return self._turn(degrees, pulse=abs(degrees) < chase.PIVOT_MIN_DEG)

    pivot = scan

    def nudge(self, degrees: float) -> str:
        return self._turn(degrees, pulse=abs(degrees) < chase.PIVOT_MIN_DEG)

    def forward(self, inches: float) -> str:
        secs = forward_seconds(inches)
        walk = self.robot.walk_scripted if hasattr(self.robot, "walk_scripted") else self.robot.walk
        self.state = walk(secs)
        return self.state

    def back(self, inches: float) -> str:
        self.state = self.robot.back(back_seconds(inches))
        return self.state
