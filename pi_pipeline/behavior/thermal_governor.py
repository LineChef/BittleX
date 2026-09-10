"""ThermalGovernor -- the behaviour-layer half of servo-thermal Layer 2.

`ThermalGuard` (`gait/thermal_guard.py`) estimates per-joint heat and tags each
joint GREEN / AMBER / RED (`ThermalTier`). This turns that into a behaviour
decision, the way `mode_controller` / `explore` turn state into intent:

  GREEN  -> nothing; full speed
  AMBER  -> throttle: cap the forward-speed command, soften the gait, and flag
            "avoid sustained uphill" for whatever plans paths
  RED    -> hold a low-torque COOLDOWN pose for `cooldown_min_s`, then only
            release once the guard reports back to <= AMBER

Pure logic + a clock. Hysteresis on de-escalation so it doesn't flap at a tier
boundary. Emits diag events through an injected `emit(subsystem, level, name,
**kv)` (default: best-effort `pi_pipeline.diag.event`).

The COOLDOWN pose is a folded, frame-supported stance (elbows/chassis carry the
weight, not the shoulder servos) -- keeps IMU + vision alive and resumes faster
than a full `d` REST. Expressed as target joint degrees (`COOLDOWN_POSE_DEG`);
caller sends them, or falls back to `opencat.SIT` / `opencat.REST` if the pose
can't be reached.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from ..gait.thermal_guard import ThermalTier
from ..link import opencat

# folded low-torque stance, URDF joint order [FLs,FLk,FRs,FRk,BRs,BRk,BLs,BLk].
# Shoulders near neutral, knees tucked so the elbows/frame bear the load.
# PLACEHOLDER -- confirm the real pose on the bench (servo-thermal.md).
COOLDOWN_POSE_DEG = (5.0, -75.0, 5.0, -75.0, 5.0, -75.0, 5.0, -75.0)


class GovernorState(Enum):
    NORMAL = "normal"
    THROTTLED = "throttled"     # AMBER -- reduced speed, softened gait
    COOLDOWN = "cooldown"       # RED -- holding the cooldown pose


@dataclass
class ThermalGovernorConfig:
    throttle_speed_scale: float = 0.55   # forward-cmd multiplier while THROTTLED
    cooldown_min_s: float = 25.0         # minimum time to hold the cooldown pose
    deescalate_s: float = 6.0            # tier must sit lower than the current state
                                        #   this long before stepping down
    cooldown_pose: tuple = COOLDOWN_POSE_DEG
    cooldown_fallback_token: str = opencat.SIT
    rest_fallback_token: str = opencat.REST


@dataclass
class GovernorDecision:
    state: GovernorState
    speed_scale: float           # multiply the forward command by this
    soften_gait: bool            # ask the gait layer to reduce aggressiveness
    avoid_uphill: bool           # hint for path planning
    hold_pose: tuple | None      # target joint degrees to hold, or None
    reason: str


def _default_emit(subsystem: str, level: str, name: str, **kv) -> None:
    try:
        from ..diag import event
        event(subsystem, level, name, **kv)
    except Exception:
        pass


class ThermalGovernor:
    def __init__(self, cfg: ThermalGovernorConfig | None = None, *,
                 emit=_default_emit, clock=time.monotonic):
        self.cfg = cfg or ThermalGovernorConfig()
        self._emit = emit
        self._clock = clock
        self._state = GovernorState.NORMAL
        self._entered = clock()
        self._cooler_since: float | None = None   # when the tier first dropped below the current state
        self._reason = "init"

    @property
    def state(self) -> GovernorState:
        return self._state

    @property
    def last_reason(self) -> str:
        return self._reason

    def reset(self) -> None:
        self.__init__(self.cfg, emit=self._emit, clock=self._clock)

    def _want_for(self, tier: ThermalTier) -> GovernorState:
        if tier >= ThermalTier.RED:
            return GovernorState.COOLDOWN
        if tier >= ThermalTier.AMBER:
            return GovernorState.THROTTLED
        return GovernorState.NORMAL

    def _decision(self) -> GovernorDecision:
        c = self.cfg
        if self._state is GovernorState.COOLDOWN:
            return GovernorDecision(self._state, 0.0, True, True, tuple(c.cooldown_pose), self._reason)
        if self._state is GovernorState.THROTTLED:
            return GovernorDecision(self._state, c.throttle_speed_scale, True, True, None, self._reason)
        return GovernorDecision(self._state, 1.0, False, False, None, self._reason)

    def update(self, hottest_tier: ThermalTier, now: float | None = None) -> GovernorDecision:
        now = self._clock() if now is None else now
        c = self.cfg
        want = self._want_for(hottest_tier)

        # escalation is immediate; de-escalation waits out `deescalate_s`,
        # and COOLDOWN additionally holds for `cooldown_min_s` -- measured from
        # the *last* tick the state was still warranted, so a re-spike extends it.
        if want.value == self._state.value:
            self._cooler_since = None
            self._entered = now
        elif self._is_hotter(want, self._state):
            self._enter(want, now, f"tier {hottest_tier.name} -> {want.value}")
        else:
            self._cooler_since = self._cooler_since or now
            held = now - self._entered
            cooled = now - self._cooler_since
            min_hold_ok = (self._state is not GovernorState.COOLDOWN
                           or held >= c.cooldown_min_s)
            if cooled >= c.deescalate_s and min_hold_ok:
                self._enter(want, now,
                            f"tier {hottest_tier.name} for {cooled:.0f}s -> {want.value}")
            else:
                blocked = "min cooldown hold" if not min_hold_ok else f"{cooled:.0f}/{c.deescalate_s:.0f}s"
                self._reason = f"cooling ({hottest_tier.name}), {self._state.value} held -- {blocked}"

        return self._decision()

    def _is_hotter(self, a: GovernorState, b: GovernorState) -> bool:
        order = {GovernorState.NORMAL: 0, GovernorState.THROTTLED: 1, GovernorState.COOLDOWN: 2}
        return order[a] > order[b]

    def _enter(self, state: GovernorState, now: float, reason: str) -> None:
        if state.value == self._state.value:
            return
        self._state = state
        self._entered = now
        self._cooler_since = None
        self._reason = reason
        lvl = {"normal": "INFO", "throttled": "WARN", "cooldown": "ERROR"}[state.value]
        self._emit("gait", lvl, f"thermal.governor_{state.value}", reason=reason)
