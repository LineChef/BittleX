"""CarpetDetector -- notice when G2 is bogging down on carpet and recommend a fix.

The learned walk (`run20m_ppo`, residual on wkF) was tuned on hard flooring; on
carpet the feet snag and forward progress collapses to a fraction of the
commanded speed (the 2026-09-03 probe batch: "stalls on carpet"). OpenCat ships
a gait tuned for carpet (`carpetF`, decoded to `reference_gait/carpet_ref.npy`),
and a bigger speed command can also punch through moderate pile.

This is pure logic: feed it the commanded forward speed and the *measured*
forward speed each control tick; it tracks the efficiency (measured / commanded)
over a window and, on a sustained shortfall, recommends an action. Hysteresis on
both edges so it doesn't chatter at a rug's edge.

  NORMAL       efficiency ok -- keep the learned walk as-is
  BOOST_CMD    moderate slip -- raise the forward speed command by `boost` to
               fight the pile (the walk policy already tracks a speed command)
  CARPET_GAIT  bad, sustained slip -- hand off to the firmware `kcarpetF` gait
               (behaviour layer sends opencat.CARPET_WALK); the residual policy
               is paused like any other skill hand-off

Caller maps the recommendation. Switching the residual *base* to carpet_ref
mid-deploy is NOT recommended (the policy's residual is relative to wkF) -- that
would need a retrain (backlog H10).
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum


class CarpetAction(Enum):
    NORMAL = "normal"
    BOOST_CMD = "boost_cmd"
    CARPET_GAIT = "carpet_gait"


@dataclass
class CarpetConfig:
    window_s: float = 2.0             # efficiency is averaged over this
    min_cmd: float = 0.04            # ignore ticks below this commanded speed (stand / turn)
    boost_below: float = 0.72        # efficiency under this (sustained) -> BOOST_CMD
    carpet_below: float = 0.45       # efficiency under this (sustained) -> CARPET_GAIT
    enter_s: float = 1.5             # shortfall must persist this long before acting
    clear_s: float = 3.0            # efficiency back above `boost_below` this long -> NORMAL
    boost: float = 0.035            # m/s added to the forward command in BOOST_CMD


class CarpetDetector:
    def __init__(self, cfg: CarpetConfig | None = None, *, clock=time.monotonic):
        self.cfg = cfg or CarpetConfig()
        self._clock = clock
        self._samples: deque[tuple[float, float]] = deque()   # (t, efficiency)
        self._action = CarpetAction.NORMAL
        self._bad_since: float | None = None
        self._good_since: float | None = None
        self._reason = "init"

    @property
    def action(self) -> CarpetAction:
        return self._action

    @property
    def last_reason(self) -> str:
        return self._reason

    def reset(self) -> None:
        self.__init__(self.cfg, clock=self._clock)

    def update(self, cmd_speed: float, measured_speed: float,
               now: float | None = None) -> CarpetAction:
        now = self._clock() if now is None else now
        c = self.cfg

        if abs(cmd_speed) >= c.min_cmd:
            eff = max(0.0, measured_speed / abs(cmd_speed))
            self._samples.append((now, min(eff, 1.5)))
        while self._samples and now - self._samples[0][0] > c.window_s:
            self._samples.popleft()
        if not self._samples:
            self._reason = "no forward command"
            return self._action
        eff = sum(e for _, e in self._samples) / len(self._samples)

        bad = eff < c.boost_below
        self._bad_since = (self._bad_since or now) if bad else None
        self._good_since = None if bad else (self._good_since or now)

        if bad and now - self._bad_since >= c.enter_s:
            want = CarpetAction.CARPET_GAIT if eff < c.carpet_below else CarpetAction.BOOST_CMD
            if want is not self._action:
                self._action = want
                self._reason = f"efficiency {eff:.2f} for {now - self._bad_since:.1f}s -> {want.value}"
        elif not bad and self._action is not CarpetAction.NORMAL:
            if self._good_since and now - self._good_since >= c.clear_s:
                self._action = CarpetAction.NORMAL
                self._reason = f"efficiency {eff:.2f} recovered for {now - self._good_since:.1f}s -> normal"
        else:
            self._reason = f"efficiency {eff:.2f} ({self._action.value})"
        return self._action

    def cmd_with_boost(self, cmd_speed: float) -> float:
        """The forward command to actually send given the current recommendation."""
        if self._action is CarpetAction.BOOST_CMD and abs(cmd_speed) >= self.cfg.min_cmd:
            return cmd_speed + self.cfg.boost * (1.0 if cmd_speed >= 0 else -1.0)
        return cmd_speed
