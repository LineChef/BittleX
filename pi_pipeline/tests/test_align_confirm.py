"""The line-up of 2026-11-15: a turn stopped on the gyro leaves for the body's coast, a line-up pulse has a floor per side, a close line-up is sized from two pictures that agree, and a ball
farther out must be nearly straight before he walks on. (Goal log: asked 6 deg, got 10 to 14; asked 20, got 22 to 28; the bearing swung 25 to 40 deg between pictures at 2 to 4 in.)"""
import pytest

from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.tests.test_ball_chase import reading


def test_the_gyro_stop_leaves_early_by_the_coast_but_never_ends_a_small_turn_before_it_begins():
    assert bc.align_stop_lead(20.0) == bc.ALIGN_COAST_DEG                              # a big turn: the whole coast
    assert bc.ALIGN_STOP_LEAD_DEG <= bc.align_stop_lead(6.0) < bc.ALIGN_COAST_DEG       # a small one: less, so it still starts
    assert 0.0 < bc.align_stop_at(6.0) < 6.0 and bc.align_stop_at(1.0) >= 0.0


def test_the_pulse_floor_is_per_side_the_slower_side_gets_the_longer_floor(monkeypatch):
    monkeypatch.setattr(bc, "ALIGN_CONFIRM_IN", 0.0)
    class P(bc.ChasePlanner):
        def _turn_rate(self, side, short):
            return 28.0 if side > 0 else 20.0                                          # the learned right and left pulse paces
    right = P().decide(reading(3.0, 14.0))
    left = P().decide(reading(3.0, -14.0))
    assert right.kind == left.kind == "align"
    assert bc.ALIGN_PULSE_FLOOR_MIN_S <= right.seconds < left.seconds <= bc.ALIGN_PULSE_MAX_S


def test_a_close_line_up_waits_for_a_second_picture_and_turns_on_the_mean(monkeypatch):
    monkeypatch.setattr(bc, "ALIGN_CONFIRM_IN", 5.0)
    p = bc.ChasePlanner()
    first = p.decide(reading(3.0, 30.0))
    assert first.kind == "look" and "second picture" in first.why
    second = p.decide(reading(3.0, 24.0))                                              # agrees within ALIGN_CONFIRM_AGREE_DEG
    assert second.kind == "align" and second.degrees == pytest.approx(27.0)            # the mean of the two
    assert p.confirm_bearing is None


def test_two_pictures_that_disagree_get_one_more_look_then_the_newest_is_used(monkeypatch):
    monkeypatch.setattr(bc, "ALIGN_CONFIRM_IN", 5.0)
    p = bc.ChasePlanner()
    assert p.decide(reading(3.0, 40.0)).kind == "look"
    assert p.decide(reading(3.0, -20.0)).kind == "look"                                # disagree: look once more
    third = p.decide(reading(3.0, -22.0))
    assert third.kind == "align" and third.degrees == pytest.approx(-21.0)             # the last two agree


def test_farther_out_the_ball_must_be_nearly_straight_before_he_walks_on(monkeypatch):
    monkeypatch.setattr(bc, "ALIGN_CONFIRM_IN", 0.0)
    p = bc.ChasePlanner()
    far_off = p.decide(reading(6.5, 9.0))                                              # inside the nudge range, 9 deg off: under the punch tolerance but over the far one
    assert far_off.kind == "align"
    straight = bc.ChasePlanner().decide(reading(6.5, 3.0))
    assert straight.kind == "walk"
    close = bc.ChasePlanner().decide(reading(2.5, 9.0))                                # near the claw the punch tolerance applies
    assert close.kind in ("punt", "walk")


def test_a_gyro_turn_whose_yaw_goes_quiet_ends_at_its_timed_length_not_the_cap():
    """2026-11-15 goal log: a pulse asked for 6 deg ran its whole 1 to 2.5 s with the yaw reading frozen (the IMU print had gone quiet): 20 to 70 deg of real turning. With no new yaw
    for YAW_STALE_S the timed length applies."""
    from pi_pipeline.tests.test_ball_chase import _gyro_robot
    r, lk = _gyro_robot(0.0)                                                          # the yaw never changes
    r.turn(30.0, 0.4, stop_deg=6.0)
    at = {c: t for c, t in lk.sent}
    ran = at["kbalance"] - at["kwkR"]
    assert ran < bc.ALIGN_CAP_S - 0.5 and ran < 1.5
    assert r.last_turn_end == "stale"


def test_a_gyro_stopped_turn_says_what_ended_it():
    from pi_pipeline.tests.test_ball_chase import _gyro_robot
    r, lk = _gyro_robot(28.0)
    r.turn(30.0, 1.0, stop_deg=5.0)
    assert r.last_turn_end == "gyro"
