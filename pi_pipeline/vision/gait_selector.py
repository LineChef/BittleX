"""GaitSelector -- turn a forward terrain reading into a `GaitMode` for the
SkillSwitch. Phase E-1 of docs/rl-runs/vision-goal-locomotion-plan.md.

Pure logic, same shape as `avoidance.py` / `cliff_guard.py`. Input mirrors the
sim's `_scan_terrain()` output ([present, dist_norm, bearing_norm, tall]); on
hardware it comes from the camera detector. Output drives which motion the
SkillSwitch runs:

  nothing ahead            -> CRUISE
  obstacle, far            -> CRUISE
  obstacle, mid distance   -> CAREFUL   (learned walk, reduced speed)
  low obstacle, close      -> STEP_OVER (scripted keyframe skill)
  tall obstacle, close     -> HALT      (a wall -- can't step it; nav/turn layer takes over)
  detector unsure          -> CAREFUL

Switching INTO a skill is debounced (N consecutive frames) so a flickery
detector doesn't chatter the gait. HALT is NOT debounced -- one confident
tall-and-close read stops immediately. Returning to CRUISE needs M consecutive
clear frames (hysteresis).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..gait.skill_switch import GaitMode

log = logging.getLogger("g2.vision.gaitselect")


@dataclass
class TerrainReading:
    """One forward scan. Mirrors sim `_scan_terrain`:
    [present, dist_norm 0..1, bearing_norm -1..1, tall]."""
    present: bool
    dist_norm: float = 1.0
    bearing_norm: float = 0.0
    tall: bool = False
    confidence: float = 1.0


@dataclass
class GaitSelectorConfig:
    # dist_norm = obstacle distance / TERRAIN_RANGE (0.60 m). The detector scan is
    # stale between refreshes and the robot creeps ~0.1 m/s, so trigger EARLY:
    # a low obstacle needs the step-over committed well before a foot reaches it.
    far_dist: float = 0.62        # dist_norm >= this: obstacle in view but ignore it
    mid_dist: float = 0.50        # far..mid -> CAREFUL
    close_dist: float = 0.50      # < this -> act (STEP_OVER for low / HALT for tall)
    ahead_bearing: float = 0.55   # |bearing_norm| within this = in our path
    min_confidence: float = 0.60  # a not-present read below this -> CAREFUL (hedge)
    into_skill_debounce: int = 1  # consecutive frames before switching INTO STEP_OVER/CAREFUL
    clear_to_cruise: int = 3      # consecutive clear frames before returning to CRUISE
    backout_on_stall: bool = True    # stalled against something -> BACK_OUT to re-approach
    backout_cooldown: int = 40       # ticks after a BACK_OUT before it can fire again


class GaitSelector:
    def __init__(self, cfg: GaitSelectorConfig | None = None):
        self._cfg = cfg or GaitSelectorConfig()
        self._mode = GaitMode.CRUISE
        self._want = GaitMode.CRUISE      # candidate mode, pending debounce
        self._want_streak = 0
        self._clear_streak = 0
        self._backout_cd = 0             # cooldown ticks left after a BACK_OUT
        self._last_reason = ""

    @property
    def mode(self) -> GaitMode:
        return self._mode

    @property
    def last_reason(self) -> str:
        return self._last_reason

    def reset(self) -> None:
        self.__init__(self._cfg)

    def update(self, r: TerrainReading, stalled: bool = False) -> GaitMode:
        c = self._cfg
        cooling = self._backout_cd > 0
        if cooling:
            self._backout_cd -= 1
        raw = self._raw_mode(r)

        # stalled against something (no forward progress despite a move command)
        # -> BACK_OUT to re-approach, unless just backed out. Beats everything but
        # a fresh HALT (a wall/edge stop stays).
        if (c.backout_on_stall and stalled and not cooling
                and raw is not GaitMode.HALT):
            self._backout_cd = c.backout_cooldown
            self._commit(GaitMode.BACK_OUT, "stalled -- back out and re-approach")
            self._want, self._want_streak, self._clear_streak = GaitMode.BACK_OUT, 0, 0
            return self._mode

        # HALT is immediate, no debounce
        if raw is GaitMode.HALT:
            self._commit(GaitMode.HALT, "tall obstacle close ahead -- halt")
            self._want, self._want_streak, self._clear_streak = raw, 0, 0
            return self._mode

        # returning to CRUISE: require consecutive clear reads
        if raw is GaitMode.CRUISE:
            self._clear_streak += 1
            self._want, self._want_streak = GaitMode.CRUISE, 0
            if self._mode is GaitMode.CRUISE:
                return self._mode
            if self._clear_streak >= c.clear_to_cruise:
                self._commit(GaitMode.CRUISE, f"clear x{self._clear_streak} -- resume cruise")
            else:
                self._say(f"clearing ({self._clear_streak}/{c.clear_to_cruise}), hold {self._mode.value}")
            return self._mode

        # raw is CAREFUL or STEP_OVER -- debounce the switch in
        self._clear_streak = 0
        if raw is self._want:
            self._want_streak += 1
        else:
            self._want, self._want_streak = raw, 1
        if self._mode is raw:
            return self._mode
        if self._want_streak >= c.into_skill_debounce:
            self._commit(raw, f"{raw.value} confirmed (x{self._want_streak})")
        else:
            self._say(f"{raw.value} pending ({self._want_streak}/{c.into_skill_debounce})")
        return self._mode

    # -- helpers ----------------------------------------------------

    def _raw_mode(self, r: TerrainReading) -> GaitMode:
        c = self._cfg
        if (not r.present) and r.confidence < c.min_confidence:
            return GaitMode.CAREFUL                     # unsure -> hedge
        if not r.present:
            return GaitMode.CRUISE
        if abs(r.bearing_norm) > c.ahead_bearing:
            return GaitMode.CRUISE                      # off to the side, not in our path
        if r.dist_norm >= c.far_dist:
            return GaitMode.CRUISE
        if r.dist_norm >= c.mid_dist:
            return GaitMode.CAREFUL
        return GaitMode.HALT if r.tall else GaitMode.STEP_OVER

    def _commit(self, mode: GaitMode, reason: str) -> None:
        self._mode = mode
        self._say(reason)

    def _say(self, reason: str) -> None:
        self._last_reason = reason
        log.info("gaitselect: %s", reason)
