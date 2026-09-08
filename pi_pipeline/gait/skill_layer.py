"""SkillLayer -- one object that runs the whole Phase E vision-skill stack on
top of the learned walk. Deployment glue (`run_gait.py`, the behaviour loop) or
a sim harness calls a single `.step()` per control tick.

    layer = SkillLayer(refs, cliff_guard=CliffGuard())     # cliff_guard optional
    ...
    rl_joint_deg = policy.step(quat, gyro)                 # the learned walk
    out_deg, info = layer.step(rl_joint_deg, gait_phase=policy.phase_frac(),
                               terrain=terrain_reading, edge=edge_reading,
                               stalled=stalled_flag)
    send_to_servos(out_deg)                                # + apply info.speed_scale to the fwd command

`terrain` is a `TerrainReading` (sim: `_scan_terrain`; hardware:
`detections_to_terrain_reading(frame)`). `edge` is an `EdgeReading` for the
cliff reflex, or None to skip it. Everything downstream is pure logic; no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..vision.cliff_guard import CliffAction, CliffGuard, EdgeReading
from ..vision.gait_selector import GaitSelector, TerrainReading
from .skill_switch import GaitMode, SkillRefs, SkillSwitch, SkillSwitchConfig, Source

# CliffGuard action -> forced GaitMode. TURN_AWAY / BACK_UP collapse to HALT
# unless a turn primitive exists (firmware, not here).
_CLIFF_TO_MODE = {
    CliffAction.NONE: None,
    CliffAction.SLOW: GaitMode.CAREFUL,
    CliffAction.STOP: GaitMode.HALT,
    CliffAction.BACK_UP: GaitMode.BACK_OUT,
    CliffAction.TURN_AWAY_LEFT: GaitMode.HALT,
    CliffAction.TURN_AWAY_RIGHT: GaitMode.HALT,
    CliffAction.FREEZE: GaitMode.HALT,
}


@dataclass
class StepInfo:
    mode: GaitMode
    source: Source
    speed_scale: float          # apply to the forward speed command (CAREFUL -> <1)
    cliff_action: CliffAction | None
    frozen: bool                 # CliffGuard gave up -- caller should stop + signal


class SkillLayer:
    def __init__(self, refs: SkillRefs,
                 switch_cfg: SkillSwitchConfig | None = None,
                 selector: GaitSelector | None = None,
                 cliff_guard: CliffGuard | None = None):
        self._switch = SkillSwitch(refs, switch_cfg)
        self._selector = selector or GaitSelector()
        self._cliff = cliff_guard

    @property
    def active_skill(self) -> GaitMode | None:
        return self._switch.active_skill

    @property
    def looking_down(self) -> bool:
        """True while an INSPECT crouch is held -- the caller sets the sensor's
        look-down flag from this so the near blind zone shrinks."""
        return self._switch.active_skill is GaitMode.INSPECT

    def reset(self) -> None:
        self._switch.reset()
        self._selector.reset()
        if self._cliff is not None:
            self._cliff.reset()

    def step(self, rl_joint_deg, *, gait_phase: float | None = None,
             terrain: TerrainReading | None = None,
             edge: EdgeReading | None = None,
             stalled: bool = False) -> tuple[np.ndarray, StepInfo]:
        mode = self._selector.update(terrain or TerrainReading(present=False), stalled=stalled)

        cliff_act = None
        frozen = False
        if self._cliff is not None and edge is not None:
            cliff_act = self._cliff.update(edge)
            forced = _CLIFF_TO_MODE.get(cliff_act)
            if forced is not None:
                mode = forced           # the cliff reflex preempts the terrain selector
            frozen = self._cliff.frozen

        joint_deg, src = self._switch.update(mode, rl_joint_deg, gait_phase=gait_phase)
        info = StepInfo(mode=mode, source=src, speed_scale=self._switch.speed_scale,
                        cliff_action=cliff_act, frozen=frozen)
        return joint_deg, info
