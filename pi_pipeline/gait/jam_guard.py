"""JamGuard -- the vision-free "I'm pushing on something" reflex (behaviour-ideas B9a).

G2's Roomba bump sensor with no bump switch: the servos are the sensor. When a
front foot is pressed against something immovable while walking forward, that
servo strains at full torque but can't reach its commanded angle, so the
tracking error (commanded minus servo-reported actual) stays wide open. Sustained
divergence on the forward-driving front-leg joints == "jammed, not moving."

Pure logic, same shape as `CarpetDetector` (`gait/carpet.py`) and `CliffGuard`
(`vision/cliff_guard.py`): feed it commanded + feedback joint angles each control
tick plus whether a forward walk is commanded; it returns a `JamAction`. No I/O.
One proprioceptive level below carpet mode -- carpet compares commanded vs actual
forward *speed*; this compares commanded vs actual *joint angle*.

The reflex is a fixed "bump and turn" sequence (B9a): on a confirmed jam,
BACK_OFF for a burst, then TURN_AWAY to a new heading, then release. It always
turns -- backing off without turning just walks straight back into the same
obstacle. If it re-jams right after releasing, the sequence restarts.

  NONE       tracking fine, or not walking forward -- carry on
  BACK_OFF   confirmed front-leg jam -- stop and step back
             (caller: opencat.WALK_BACKWARD for `backoff_s`)
  TURN_AWAY  back-off done -- turn to a new heading
             (caller: `turn_token(...)` for `turn_s`), then the guard returns NONE

Catches: front feet jammed against a solid obstacle while walking forward.
Does NOT catch: drop-offs (a foot finds *no* floor -- opposite signal, that's
CliffGuard's job), soft obstacles, anything off to the side, anything not yet
touched. Purely reactive -- fires after contact.

HARDWARE-GATED. Every constant in `JamGuardConfig` is a placeholder: the
divergence threshold can't be set without the real robot (normal carpet load, a
leg brushing another leg, stepping a small bump, and working into a slope all
produce divergence too, and Bittle is light + slow so the strain signal may be
weak). Also unconfirmed until the bench: which servos report feedback and at
what rate (`opencat.SERVO_FEEDBACK` / `readAllFeedbackFast()` -- "if supported",
see docs/hardware/specs.md "Servo position feedback"). Unit-testable now
against synthetic cmd/feedback traces; the numbers wait for the bench.

Wiring (later, on hardware) -- in `gait/run_gait.py`, alongside the thermal
guard: poll `f` for the servo feedback vector each tick (or every few ticks),
call `jam.update(cmd_deg, fbk_deg, forward_active=cmd_fwd > MIN)`, and on a
non-NONE action preempt the policy for a scripted burst the way CliffGuard's
turn/back-up hand-off works. Emit `diag.event(*jam.diag_event()[0],
**jam.diag_event()[1])` on a phase change.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum

from ..link import opencat


class JamAction(Enum):
    NONE = "none"
    BACK_OFF = "back_off"
    TURN_AWAY = "turn_away"


@dataclass
class JamGuardConfig:
    # URDF leg-joint order is [FLs, FLk, FRs, FRk, BRs, BRk, BLs, BLk]; the front
    # legs are the first four. Caller can pass a different slice if its joint
    # vector is ordered differently.
    front_idx: tuple[int, ...] = (0, 1, 2, 3)

    window_s: float = 0.6          # tracking error is averaged over this
    jam_deg: float = 12.0         # sustained mean front-joint |cmd - fbk| above this -> jammed
    min_jammed_joints: int = 2    # this many front joints must exceed jam_deg on the latest read
                                  #   (one strained joint alone could be leg-on-leg contact)
    enter_s: float = 0.4          # divergence must persist this long before BACK_OFF
    backoff_s: float = 0.8        # hold BACK_OFF this long (the back-up burst)
    turn_s: float = 1.0           # hold TURN_AWAY this long (the heading change)
    min_forward_cmd: float = 0.04  # |forward command| below this -> not "walking forward"

    back_off_token: str = opencat.WALK_BACKWARD
    turn_left_token: str = opencat.WALK_LEFT
    turn_right_token: str = opencat.WALK_RIGHT


class JamGuard:
    def __init__(self, cfg: JamGuardConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or JamGuardConfig()
        self._clock = clock
        self._samples: deque[tuple[float, float, int]] = deque()  # (t, mean_err_deg, n_over)
        self._action = JamAction.NONE
        self._jam_since: float | None = None
        self._phase_until: float = 0.0        # when the current BACK_OFF / TURN_AWAY ends
        self._reason = "init"                 # sticky: cause of the current action
        self._status = "init"                 # per-tick detail

    @property
    def action(self) -> JamAction:
        return self._action

    @property
    def last_reason(self) -> str:
        """Why the guard is in its current action -- sticky, set at the last
        transition (fire / turn / release), not every tick."""
        return self._reason

    @property
    def status(self) -> str:
        """Per-tick detail (windowed error, phase countdown) -- for verbose logs."""
        return self._status

    def reset(self) -> None:
        self.__init__(self.cfg, clock=self._clock)

    def diag_event(self) -> tuple[tuple[str, str, str], dict]:
        """`(args, kwargs)` for the current fire -- `diag.event(*a, **kw)`."""
        return (("gait", "WARN", "jam.detected"),
                {"action": self._action.value, "reason": self._reason})

    def turn_token(self, prefer_left: bool = True) -> str:
        """Which turn token to send for a TURN_AWAY. Caller picks the side from
        whatever heading info it has; default left."""
        return self.cfg.turn_left_token if prefer_left else self.cfg.turn_right_token

    def update(self, cmd_deg, fbk_deg, *, forward_active: bool,
               now: float | None = None) -> JamAction:
        now = self._clock() if now is None else now
        c = self.cfg

        # not walking forward -> jam is meaningless; abandon any running maneuver
        if not forward_active:
            self._samples.clear()
            self._jam_since = None
            self._status = "no forward command"
            if self._action is not JamAction.NONE:
                self._action = JamAction.NONE
                self._reason = "no forward command -> released"
            return self._action

        # --- run an in-progress maneuver on its timers ------------------------
        if self._action is JamAction.BACK_OFF:
            if now >= self._phase_until:
                self._action = JamAction.TURN_AWAY
                self._phase_until = now + c.turn_s
                self._reason = "backed off -> turning to a new heading"
            self._status = f"{self._action.value} ({max(0.0, self._phase_until - now):.1f}s left)"
            return self._action
        if self._action is JamAction.TURN_AWAY:
            if now >= self._phase_until:
                self._action = JamAction.NONE
                self._jam_since = None
                self._samples.clear()
                self._reason = "turn complete -> resume"
            self._status = (f"turn_away ({max(0.0, self._phase_until - now):.1f}s left)"
                            if self._action is JamAction.TURN_AWAY else self._reason)
            return self._action

        # --- idle: watch for a jam -----------------------------------------
        errs = [abs(float(cmd_deg[i]) - float(fbk_deg[i])) for i in c.front_idx]
        mean_err = sum(errs) / len(errs)
        n_over = sum(e >= c.jam_deg for e in errs)
        self._samples.append((now, mean_err, n_over))
        while self._samples and now - self._samples[0][0] > c.window_s:
            self._samples.popleft()

        w_mean = sum(m for _, m, _ in self._samples) / len(self._samples)
        w_over = self._samples[-1][2]                   # jammed-joint count on the latest read

        jammed = w_mean >= c.jam_deg and w_over >= c.min_jammed_joints
        self._jam_since = (self._jam_since or now) if jammed else None

        if jammed and now - self._jam_since >= c.enter_s:
            self._action = JamAction.BACK_OFF
            self._phase_until = now + c.backoff_s
            self._reason = (f"front-leg divergence {w_mean:.1f}deg on {w_over} joints "
                            f"for {now - self._jam_since:.1f}s -> back off")
            self._status = self._reason
            return self._action

        self._status = f"tracking ok (err {w_mean:.1f}deg, {w_over} joints over)"
        if self._reason == "init":
            self._reason = "tracking ok"
        return self._action
