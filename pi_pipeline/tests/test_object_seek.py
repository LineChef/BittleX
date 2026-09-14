from pi_pipeline.behavior.explore import ExploreAction
from pi_pipeline.behavior.object_seek import (
    ObjectSeek,
    ObjectSeekAction,
    ObjectSeekConfig,
)


def test_never_requests_a_scan_while_actually_moving():
    seek = ObjectSeek()
    for action in (ExploreAction.WANDER, ExploreAction.TURN, ExploreAction.APPROACH):
        t = seek.update(1.0, explore_action=action)
        assert t.action is ObjectSeekAction.NONE


def test_requests_a_scan_when_stationary_during_explore():
    seek = ObjectSeek(ObjectSeekConfig(scan_cooldown_s=10.0))
    t = seek.update(1.0, explore_action=ExploreAction.HOLD)
    assert t.action is ObjectSeekAction.SCAN
    t2 = seek.update(1.0, explore_action=ExploreAction.INVESTIGATE)
    # cooldown hasn't elapsed yet (same timestamp) -- no second scan immediately
    assert t2.action is ObjectSeekAction.NONE


def test_cooldown_blocks_a_second_scan_too_soon():
    seek = ObjectSeek(ObjectSeekConfig(scan_cooldown_s=10.0))
    seek.update(0.0, explore_action=ExploreAction.HOLD)
    t = seek.update(5.0, explore_action=ExploreAction.HOLD)   # only 5s later
    assert t.action is ObjectSeekAction.NONE
    t2 = seek.update(11.0, explore_action=ExploreAction.HOLD)  # 11s later -- clear
    assert t2.action is ObjectSeekAction.SCAN


def test_gallery_at_capacity_blocks_a_scan():
    seek = ObjectSeek()
    t = seek.update(1.0, explore_action=ExploreAction.HOLD, gallery_has_capacity=False)
    assert t.action is ObjectSeekAction.NONE


def test_reset_clears_the_cooldown():
    seek = ObjectSeek(ObjectSeekConfig(scan_cooldown_s=100.0))
    seek.update(0.0, explore_action=ExploreAction.HOLD)
    seek.reset()
    t = seek.update(1.0, explore_action=ExploreAction.HOLD)   # would still be in cooldown otherwise
    assert t.action is ObjectSeekAction.SCAN
