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

Lag-tolerant comparison (2026-09-22). The servo is NOT expected to sit on the
Pi's latest command: the firmware executes each `i` command as an eased move at
~2 deg per 8 ms, reads the next command only when that finishes, and drops a
backlog (oldest waiting command wins) -- in sim that's ~55 ms behind and ~9 deg
off the latest command on a perfectly healthy leg
(rl_training/opencat-gym/firmware_model.py, resilience_joint_cmd.py). Comparing
against the latest command would read every fast swing as a jam. So each front
joint's error is the distance from its feedback angle to the RANGE its commands
swept over the last `lag_window_s` -- 0 while the servo is anywhere on the
recently commanded path, growing only when it's stuck outside it.

Feedback reads are sparse and costly: `f` makes the firmware re-attach each pin,
send a request pulse and time the reply (espServo.h readFeedback, tens of ms for
a full set), and the firmware loop executes no joint command meanwhile. Call
`update()` every control tick with `fbk_deg=None` on ticks without a fresh read
(the command history still records), and read feedback no faster than
`JamGuardConfig.feedback_hz`.

Sim check (2026-09-22, run20m_ppo through the `i` firmware model, sim joint
angles as 5 Hz feedback): 0 false fires in 18 episodes on flat / 20 mm
obstacles / rough ground -- where the old latest-command comparison would
have averaged ~13 deg of "error" on plain walking. But walking into a wall
did NOT fire either (0/6): the body stops (~0.11 m) while the legs keep
tracking their commanded path -- feet tap the wall and slide. The sim couldn't
show the strain signal this reflex assumes; whether a real P1S pinned on an
obstacle shows it is the bench question. If it doesn't, the jam cue has to
come from "walking commanded, not advancing" instead (needs a speed source).

HARDWARE-GATED. Every constant in `JamGuardConfig` is a placeholder: the
divergence threshold can't be set without the real robot (normal carpet load, a
leg brushing another leg, stepping a small bump, and working into a slope all
produce divergence too, and Bittle is light + slow so the strain signal may be
weak). Also unconfirmed until the bench: which servos report feedback and at
what rate (`opencat.SERVO_FEEDBACK` / `readAllFeedbackFast()` -- "if supported",
see docs/hardware/specs.md "Servo position feedback"). Unit-testable now
against synthetic cmd/feedback traces; the numbers wait for the bench.

Wiring (later, on hardware) -- in `gait/run_gait.py`, alongside the thermal
guard: poll `f` for the servo feedback vector at `feedback_hz` (not every tick),
call `jam.update(cmd_deg, fbk_deg or None, forward_active=cmd_fwd > MIN)` every tick, and on a
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
    lag_window_s: float = 0.12     # a joint is on-track if its feedback lies within the range its
                                  #   commands swept over this long (firmware `i` lag ~55 ms in sim)
    feedback_hz: float = 5.0       # suggested max feedback read rate (each read stalls the firmware loop)
    jam_deg: float = 12.0         # sustained mean front-joint |cmd - fbk| above this -> jammed
    min_jammed_joints: int = 2    # this many front joints must average over jam_deg across the window
                                  #   (one strained joint alone could be leg-on-leg contact). Windowed,
                                  #   not latest-read: a leg pinned mid-walk only diverges on the part
                                  #   of the stride that pushes into the obstacle.
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
        self._samples: deque[tuple[float, tuple]] = deque()       # (t, per-front-joint error deg)
        self._cmds: deque[tuple[float, tuple]] = deque()          # (t, front-joint commands)
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

    def _track_err(self, j: int, k: int, fbk: float) -> float:
        """Distance from feedback to the span joint j's commands covered lately."""
        vals = [cmds[k] for _, cmds in self._cmds]
        lo, hi = min(vals), max(vals)
        return lo - fbk if fbk < lo else (fbk - hi if fbk > hi else 0.0)

    def update(self, cmd_deg, fbk_deg, *, forward_active: bool,
               now: float | None = None) -> JamAction:
        """`fbk_deg=None` on ticks without a fresh feedback read: the command is
        recorded, the jam decision waits for the next read."""
        now = self._clock() if now is None else now
        c = self.cfg
        self._cmds.append((now, tuple(float(cmd_deg[i]) for i in c.front_idx)))
        while self._cmds and now - self._cmds[0][0] > c.lag_window_s:
            self._cmds.popleft()

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
        if fbk_deg is None:
            self._status = "waiting for a feedback read"
            return self._action
        errs = [self._track_err(i, k, float(fbk_deg[i])) for k, i in enumerate(c.front_idx)]
        self._samples.append((now, tuple(errs)))
        while self._samples and now - self._samples[0][0] > c.window_s:
            self._samples.popleft()

        n = len(self._samples)
        per_joint = [sum(e[k] for _, e in self._samples) / n for k in range(len(errs))]
        over = [m for m in per_joint if m >= c.jam_deg]
        w_over = len(over)
        w_mean = sum(over) / w_over if over else max(per_joint)

        jammed = w_over >= c.min_jammed_joints
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
