from pi_pipeline.link import opencat
from pi_pipeline.vision.cliff_guard import (
    ACTION_SPEED_SCALE,
    CliffAction,
    CliffGuard,
    CliffGuardConfig,
    EdgeReading,
    MockEdgeFeed,
    action_commands,
)

CLEAR = EdgeReading(present=False, dist_norm=1.0, bearing_norm=0.0, confidence=1.0)


def edge(dist, bearing=0.0, conf=1.0):
    return EdgeReading(present=True, dist_norm=dist, bearing_norm=bearing, confidence=conf)


def test_clear_floor_is_none():
    g = CliffGuard()
    for _ in range(10):
        assert g.update(CLEAR) is CliffAction.NONE
    assert not g.holding


def test_far_edge_creeps():
    g = CliffGuard()
    assert g.update(edge(0.7)) is CliffAction.SLOW
    assert g.holding


def test_near_edge_stops_immediately_no_debounce():
    g = CliffGuard()
    assert g.update(edge(0.4)) is CliffAction.STOP   # one read, no debounce


def test_close_edge_on_right_turns_left():
    g = CliffGuard()
    assert g.update(edge(0.28, bearing=0.8)) is CliffAction.TURN_AWAY_LEFT


def test_close_edge_on_left_turns_right():
    g = CliffGuard()
    assert g.update(edge(0.28, bearing=-0.8)) is CliffAction.TURN_AWAY_RIGHT


def test_close_dead_ahead_turns_left_by_default():
    g = CliffGuard()
    assert g.update(edge(0.28, bearing=0.0)) is CliffAction.TURN_AWAY_LEFT


def test_too_close_to_pivot_freezes():
    g = CliffGuard(CliffGuardConfig(pivot_safe_dist=0.30))
    act = g.update(edge(0.15, bearing=0.8))          # inside the pivot-safety margin
    assert act is CliffAction.FREEZE
    assert g.frozen
    # frozen is sticky -- a later clear read doesn't release it
    assert g.update(CLEAR) is CliffAction.FREEZE


def test_back_up_only_when_rear_sensing_enabled():
    no_rear = CliffGuard(CliffGuardConfig(rear_sensing=False, pivot_safe_dist=0.10))
    assert no_rear.update(edge(0.20, bearing=0.0)) is CliffAction.TURN_AWAY_LEFT

    rear = CliffGuard(CliffGuardConfig(rear_sensing=True))
    assert rear.update(edge(0.20, bearing=0.0)) is CliffAction.BACK_UP


def test_unsure_low_confidence_read_holds():
    g = CliffGuard(CliffGuardConfig(min_confidence=0.6))
    unsure = EdgeReading(present=False, dist_norm=1.0, bearing_norm=0.0, confidence=0.3)
    assert g.update(unsure) is CliffAction.STOP
    assert g.holding


def test_resume_needs_consecutive_clears():
    g = CliffGuard(CliffGuardConfig(clear_scans_to_resume=3))
    assert g.update(edge(0.4)) is CliffAction.STOP        # holding
    assert g.update(CLEAR) is CliffAction.STOP            # clear 1/3 -- still held
    assert g.update(CLEAR) is CliffAction.STOP            # clear 2/3
    assert g.update(CLEAR) is CliffAction.NONE            # clear 3/3 -- resume
    assert not g.holding


def test_clear_streak_resets_on_a_hazard():
    g = CliffGuard(CliffGuardConfig(clear_scans_to_resume=3))
    g.update(edge(0.4))
    g.update(CLEAR)
    g.update(CLEAR)
    assert g.update(edge(0.4)) is CliffAction.STOP        # hazard again -- streak reset
    assert g.update(CLEAR) is CliffAction.STOP            # back to 1/3


def test_repeated_turns_without_clearing_freeze():
    g = CliffGuard(CliffGuardConfig(max_turn_attempts=3, pivot_safe_dist=0.10))
    for _ in range(3):
        assert g.update(edge(0.20, bearing=0.8)) is CliffAction.TURN_AWAY_LEFT
    assert g.update(edge(0.20, bearing=0.8)) is CliffAction.FREEZE
    assert g.frozen


def test_reset_clears_freeze():
    g = CliffGuard(CliffGuardConfig(pivot_safe_dist=0.30))
    g.update(edge(0.15))
    assert g.frozen
    g.reset()
    assert not g.frozen
    assert g.update(CLEAR) is CliffAction.NONE


def test_action_commands_use_real_tokens():
    cfg = CliffGuardConfig()
    assert action_commands(CliffAction.NONE, cfg) == []
    assert action_commands(CliffAction.STOP, cfg) == [opencat.BALANCE]
    assert action_commands(CliffAction.TURN_AWAY_LEFT, cfg) == [opencat.WALK_LEFT]
    assert action_commands(CliffAction.TURN_AWAY_RIGHT, cfg) == [opencat.WALK_RIGHT]
    assert action_commands(CliffAction.BACK_UP, cfg) == [opencat.WALK_BACKWARD]
    for act in CliffAction:
        for c in action_commands(act, cfg):
            assert opencat.is_safe(c)


def test_speed_scale_table():
    assert ACTION_SPEED_SCALE[CliffAction.NONE] == 1.0
    assert 0.0 < ACTION_SPEED_SCALE[CliffAction.SLOW] < 1.0
    assert ACTION_SPEED_SCALE[CliffAction.STOP] == 0.0
    assert ACTION_SPEED_SCALE[CliffAction.FREEZE] == 0.0


def test_mock_edge_feed_repeats_last():
    feed = MockEdgeFeed([CLEAR, (True, 0.4, 0.0), edge(0.2)])
    assert feed.read() is CLEAR
    assert feed.read().present and feed.read().dist_norm == 0.2
    assert feed.read().dist_norm == 0.2   # exhausted -> repeats last
