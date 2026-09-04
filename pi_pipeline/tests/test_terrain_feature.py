from pi_pipeline.vision.feed import Detection
from pi_pipeline.vision.terrain_feature import (
    FEATURE_DIM,
    FEATURE_LAYOUT,
    ZERO_FEATURE,
    TerrainFeatureConfig,
    TerrainFeatureExtractor,
    terrain_feature,
)


def det(area_side, bearing=0.5, conf=0.85, label="box", h=None):
    s = area_side
    hh = s if h is None else h
    return Detection(label, conf, bearing - s / 2, 0.5 - hh / 2, s, hh)


def test_layout_is_frozen():
    assert FEATURE_LAYOUT == ("present", "dist_norm", "bearing_norm", "tall_flag")
    assert FEATURE_DIM == 4 == len(ZERO_FEATURE)


def test_empty_frame_is_zero():
    assert terrain_feature([]) == ZERO_FEATURE


def test_specks_and_low_conf_ignored():
    assert terrain_feature([det(0.03)]) == ZERO_FEATURE            # below min_area
    assert terrain_feature([det(0.4, conf=0.1)]) == ZERO_FEATURE   # below min_conf


def test_present_and_distance_monotonic():
    far = terrain_feature([det(0.12)])
    near = terrain_feature([det(0.55)])
    assert far[0] == near[0] == 1.0
    assert far[1] > near[1]                       # smaller box => larger dist_norm
    assert 0.0 <= near[1] <= far[1] <= 1.0


def test_bearing_sign_and_range():
    left = terrain_feature([det(0.3, bearing=0.15)])
    ahead = terrain_feature([det(0.3, bearing=0.5)])
    right = terrain_feature([det(0.3, bearing=0.85)])
    assert left[2] < 0 < right[2]
    assert abs(ahead[2]) < 1e-9
    assert -1.0 <= left[2] and right[2] <= 1.0


def test_tall_flag_from_box_height():
    short = terrain_feature([det(0.3, h=0.15)])
    tall = terrain_feature([det(0.3, h=0.45)])
    assert short[3] == 0.0
    assert tall[3] == 1.0


def test_nearest_detection_wins():
    frame = [det(0.15, bearing=0.2), det(0.5, bearing=0.8)]
    feat = terrain_feature(frame)
    assert feat[2] > 0                            # picked the bigger (nearer) right-side box


def test_label_allow_list():
    cfg = TerrainFeatureConfig(labels=("step", "curb"))
    assert terrain_feature([det(0.4, label="cat")], cfg) == ZERO_FEATURE
    assert terrain_feature([det(0.4, label="step")], cfg)[0] == 1.0


def test_extractor_holds_between_frames_then_goes_stale():
    ex = TerrainFeatureExtractor(stale_after=3)
    ex.update([det(0.5)])
    held = ex.current
    assert held[0] == 1.0
    for _ in range(3):
        ex.tick()
        assert ex.current == held                 # still holding
    ex.tick()                                     # age now > stale_after
    assert ex.current == ZERO_FEATURE
