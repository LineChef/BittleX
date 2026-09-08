from pi_pipeline.gait.skill_switch import GaitMode
from pi_pipeline.vision.gait_selector import (
    GaitSelector,
    GaitSelectorConfig,
    TerrainReading,
)

CLEAR = TerrainReading(present=False)


def obst(dist, bearing=0.0, tall=False, conf=1.0):
    return TerrainReading(present=True, dist_norm=dist, bearing_norm=bearing,
                          tall=tall, confidence=conf)


def feed(sel, r, n):
    m = None
    for _ in range(n):
        m = sel.update(r)
    return m


def test_clear_is_cruise():
    sel = GaitSelector()
    for _ in range(5):
        assert sel.update(CLEAR) is GaitMode.CRUISE


def test_far_obstacle_ignored():
    sel = GaitSelector()
    assert feed(sel, obst(0.8), 3) is GaitMode.CRUISE


def test_obstacle_off_to_the_side_ignored():
    sel = GaitSelector()
    assert feed(sel, obst(0.2, bearing=0.9), 3) is GaitMode.CRUISE


def test_mid_distance_obstacle_is_careful_after_debounce():
    sel = GaitSelector(GaitSelectorConfig(into_skill_debounce=2))
    assert sel.update(obst(0.55)) is GaitMode.CRUISE     # frame 1: pending
    assert sel.update(obst(0.55)) is GaitMode.CAREFUL    # frame 2: confirmed


def test_low_close_obstacle_triggers_step_over():
    sel = GaitSelector(GaitSelectorConfig(into_skill_debounce=2))
    assert feed(sel, obst(0.15, tall=False), 2) is GaitMode.STEP_OVER


def test_tall_close_obstacle_halts_immediately_no_debounce():
    sel = GaitSelector(GaitSelectorConfig(into_skill_debounce=3))
    assert sel.update(obst(0.15, tall=True)) is GaitMode.HALT   # one frame, no debounce


def test_unsure_reading_is_careful():
    sel = GaitSelector(GaitSelectorConfig(min_confidence=0.6, into_skill_debounce=2))
    unsure = TerrainReading(present=False, confidence=0.3)
    assert feed(sel, unsure, 2) is GaitMode.CAREFUL


def test_return_to_cruise_needs_consecutive_clears():
    sel = GaitSelector(GaitSelectorConfig(into_skill_debounce=1, clear_to_cruise=3))
    assert sel.update(obst(0.15)) is GaitMode.STEP_OVER
    assert sel.update(CLEAR) is GaitMode.STEP_OVER       # clear 1/3 -- still stepping
    assert sel.update(CLEAR) is GaitMode.STEP_OVER       # 2/3
    assert sel.update(CLEAR) is GaitMode.CRUISE          # 3/3 -- resume


def test_clear_streak_resets_on_a_reappearing_obstacle():
    sel = GaitSelector(GaitSelectorConfig(into_skill_debounce=1, clear_to_cruise=3))
    sel.update(obst(0.15))
    sel.update(CLEAR)
    sel.update(CLEAR)
    assert sel.update(obst(0.15)) is GaitMode.STEP_OVER  # reappeared
    assert sel.update(CLEAR) is GaitMode.STEP_OVER       # back to clear 1/3


def test_debounce_resets_if_candidate_changes():
    sel = GaitSelector(GaitSelectorConfig(into_skill_debounce=3))
    sel.update(obst(0.55))                               # CAREFUL candidate, streak 1
    sel.update(obst(0.15))                               # STEP_OVER candidate, streak resets to 1
    assert sel.mode is GaitMode.CRUISE                   # neither confirmed yet
    sel.update(obst(0.15))                               # streak 2
    assert sel.update(obst(0.15)) is GaitMode.STEP_OVER  # streak 3 -- confirmed


def test_reset():
    sel = GaitSelector(GaitSelectorConfig(into_skill_debounce=1))
    sel.update(obst(0.15, tall=True))
    assert sel.mode is GaitMode.HALT
    sel.reset()
    assert sel.mode is GaitMode.CRUISE
    assert sel.update(CLEAR) is GaitMode.CRUISE
