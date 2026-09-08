import numpy as np

from pi_pipeline.gait.skill_layer import SkillLayer, StepInfo
from pi_pipeline.gait.skill_switch import GaitMode, SkillRefs, Source
from pi_pipeline.vision.cliff_guard import CliffGuard, CliffGuardConfig, EdgeReading
from pi_pipeline.vision.gait_selector import (
    TerrainReading,
    detections_to_terrain_reading,
)

RL = np.full(8, 10.0)
STEP = np.tile(np.linspace(0.0, 0.4, 4)[:, None], (1, 8))
REFS = SkillRefs(step_over=STEP, inspect=np.full((2, 8), -0.5),
                 back_out=np.full((4, 8), 0.2))


class _Det:
    def __init__(self, cx, area, h_over_w=1.0, y=0.4, conf=0.9, label="box"):
        w = area ** 0.5
        self.label, self.confidence = label, conf
        self.w, self.h, self.y = w, w * h_over_w, y
        self.x = cx - w / 2

    @property
    def area(self):
        return self.w * self.h

    @property
    def center_x(self):
        return self.x + self.w / 2


# -- SkillLayer ---------------------------------------------------------

def test_clear_terrain_passes_rl_through():
    layer = SkillLayer(REFS)
    out, info = layer.step(RL, gait_phase=0.0, terrain=TerrainReading(present=False))
    assert info.mode is GaitMode.CRUISE and info.source is Source.RL
    assert np.allclose(out, RL)


def test_close_low_obstacle_drives_step_over():
    layer = SkillLayer(REFS)
    for _ in range(6):
        out, info = layer.step(RL, gait_phase=0.0,
                               terrain=TerrainReading(present=True, dist_norm=0.2))
    assert info.mode is GaitMode.STEP_OVER
    assert info.source in (Source.BLEND, Source.SCRIPTED)


def test_cliff_edge_preempts_the_selector():
    layer = SkillLayer(REFS, cliff_guard=CliffGuard(CliffGuardConfig(pivot_safe_dist=0.10)))
    # a low obstacle the selector would step over...
    terr = TerrainReading(present=True, dist_norm=0.2)
    # ...but an edge close ahead -> CliffGuard forces HALT
    edge = EdgeReading(present=True, dist_norm=0.15, bearing_norm=0.0)
    out, info = layer.step(RL, gait_phase=0.0, terrain=terr, edge=edge)
    assert info.mode is GaitMode.HALT
    assert info.cliff_action is not None


def test_careful_reports_speed_scale():
    layer = SkillLayer(REFS)
    out, info = layer.step(RL, gait_phase=0.0,
                           terrain=TerrainReading(present=True, dist_norm=0.55))
    assert info.mode is GaitMode.CAREFUL
    assert info.speed_scale < 1.0


def test_looking_down_true_only_during_inspect():
    layer = SkillLayer(REFS)
    assert layer.looking_down is False
    unres = TerrainReading(present=True, dist_norm=0.15, unresolved=True)
    for _ in range(3):                       # selector commits, switch phase-gates then begins
        layer.step(RL, gait_phase=0.0, terrain=unres)
    assert layer.active_skill is GaitMode.INSPECT
    assert layer.looking_down is True


def test_reset():
    layer = SkillLayer(REFS)
    for _ in range(4):
        layer.step(RL, gait_phase=0.0, terrain=TerrainReading(present=True, dist_norm=0.2))
    layer.reset()
    out, info = layer.step(RL, gait_phase=0.0, terrain=TerrainReading(present=False))
    assert info.mode is GaitMode.CRUISE and info.source is Source.RL


# -- detections_to_terrain_reading ------------------------------------

def test_no_detections_is_not_present():
    r = detections_to_terrain_reading([])
    assert r.present is False


def test_side_detection_ignored():
    r = detections_to_terrain_reading([_Det(cx=0.95, area=0.1)])
    assert r.present is False          # outside the ahead band


def test_nearest_box_wins_and_area_maps_to_distance():
    frame = [_Det(cx=0.5, area=0.02), _Det(cx=0.52, area=0.20)]
    r = detections_to_terrain_reading(frame)
    assert r.present and 0.0 <= r.dist_norm < 0.5     # the big (near) box
    assert abs(r.bearing_norm) < 0.1


def test_tall_box_sets_tall_flag():
    r = detections_to_terrain_reading([_Det(cx=0.5, area=0.1, h_over_w=1.8)])
    assert r.present and r.tall is True


def test_frame_filling_box_is_unresolved_not_tall():
    r = detections_to_terrain_reading([_Det(cx=0.5, area=0.5, h_over_w=2.0, y=0.02)])
    assert r.unresolved is True and r.tall is False
