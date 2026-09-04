"""Forward terrain feature for the walking policy -- the Pi side of the
perception-in-the-loop gait (docs/project-plan.md Phase 8, "DECIDED
ARCHITECTURE").

The walk policy gets its OWN low-bandwidth terrain signal, fed straight into its
observation at control rate -- separate from the vision->command / vision->Claude
path. This module turns the AI Vision Camera's detection `Frame` into the exact
4-float vector the RL env appends to its observation:

    [ present, dist_norm, bearing_norm, tall_flag ]

    present      1.0 if an obstacle is seen in the forward cone, else 0.0
    dist_norm    distance / range, in [0, 1]     (0 = right in front, 1 = far)
    bearing_norm angle off heading / half-FOV, in [-1, 1]   (- left, + right)
    tall_flag    1.0 if the obstacle is tall enough to go around / stop for,
                 0.0 if low (the policy may step over / just slow)

The sim generator is `opencat_gym_env.OpenCatGymEnv._scan_terrain` (a forward ray
fan on the scene geometry). **This layout is frozen -- change both ends together.**

The camera reports normalised bounding boxes; there is no true depth. `dist_norm`
comes from box `area` (a 1/dist^2 closeness proxy) and `tall_flag` from box
height. The constants in `TerrainFeatureConfig` are first guesses -- calibrate
them on hardware against known obstacle distances/heights (see `run_gait.py`
bring-up), the same way `AvoiderConfig` thresholds get tuned.

The real detection feed is ~10-30 FPS; the gait loop runs ~48-80 Hz. Use
`TerrainFeatureExtractor`, which holds the last value between frames -- matching
the sim's `TERRAIN_REFRESH` stale-between-frames behaviour.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .feed import Detection, Frame

# Frozen: index -> meaning. Mirrors opencat_gym_env._scan_terrain's return.
FEATURE_LAYOUT = ("present", "dist_norm", "bearing_norm", "tall_flag")
FEATURE_DIM = 4
ZERO_FEATURE = (0.0, 0.0, 0.0, 0.0)


@dataclass
class TerrainFeatureConfig:
    # --- which detections count as "terrain in my path" ---
    labels: tuple[str, ...] = ()      # empty = accept every label; else an allow-list
    min_conf: float = 0.35            # ignore low-confidence boxes
    min_area: float = 0.004           # ignore specks (a 6%x6% box) -- detector noise / far clutter

    # --- box area -> dist_norm.  s = sqrt(area) is ~ apparent size ~ 1/dist. ---
    # s at the near limit (obstacle right in front) and at max reported range.
    s_near: float = 0.60             # sqrt(area) ~= 0.60  (area ~0.36) => dist_norm 0
    s_far: float = 0.09             # sqrt(area) ~= 0.09  (area ~0.008) => dist_norm 1

    # --- box centre_x -> bearing_norm ---
    # camera horizontal half-FOV vs the sim's forward-cone half-angle (35 deg).
    # 1.0 = they match; <1 if the camera sees wider than the cone.
    fov_scale: float = 1.0

    # --- box height -> tall_flag ---
    h_tall: float = 0.34             # normalised box height at/above which -> tall_flag = 1


def terrain_feature(frame: Frame, cfg: TerrainFeatureConfig | None = None
                    ) -> tuple[float, float, float, float]:
    """`Frame` (list of `Detection`) -> the 4-float terrain feature.

    Picks the NEAREST qualifying detection (largest box area). Returns
    `ZERO_FEATURE` when nothing qualifies."""
    cfg = cfg or TerrainFeatureConfig()
    best: Detection | None = None
    for d in frame:
        if d.confidence < cfg.min_conf:
            continue
        if cfg.labels and d.label not in cfg.labels:
            continue
        if d.area < cfg.min_area:
            continue
        if best is None or d.area > best.area:
            best = d
    if best is None:
        return ZERO_FEATURE

    s = math.sqrt(best.area)
    dist_norm = (cfg.s_near - s) / (cfg.s_near - cfg.s_far)
    dist_norm = min(1.0, max(0.0, dist_norm))

    bearing_norm = (best.center_x - 0.5) * 2.0 * cfg.fov_scale
    bearing_norm = min(1.0, max(-1.0, bearing_norm))

    tall_flag = 1.0 if best.h >= cfg.h_tall else 0.0
    return (1.0, dist_norm, bearing_norm, tall_flag)


class TerrainFeatureExtractor:
    """Stateful wrapper for the control loop. `update(frame)` on each new
    detection frame; read `.current` every gait tick (it holds the last value
    between frames). `age` counts ticks since the last real update -- the loop
    can zero the feature if the feed has stalled for too long."""

    def __init__(self, cfg: TerrainFeatureConfig | None = None,
                 stale_after: int = 12):
        self.cfg = cfg or TerrainFeatureConfig()
        self.stale_after = stale_after
        self._current: tuple[float, float, float, float] = ZERO_FEATURE
        self.age = 0

    def update(self, frame: Frame) -> tuple[float, float, float, float]:
        self._current = terrain_feature(frame, self.cfg)
        self.age = 0
        return self._current

    def tick(self) -> None:
        """Call once per gait control step that did NOT get a fresh frame."""
        self.age += 1

    @property
    def current(self) -> tuple[float, float, float, float]:
        if self.age > self.stale_after:
            return ZERO_FEATURE
        return self._current
