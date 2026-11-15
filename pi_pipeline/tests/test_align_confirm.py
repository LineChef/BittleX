"""The line-up of 2026-11-15: a turn stopped on the gyro leaves for the body's coast, a line-up pulse has a floor per side, a close line-up is sized from two pictures that agree, and a ball
farther out must be nearly straight before he walks on. (Goal log: asked 6 deg, got 10 to 14; asked 20, got 22 to 28; the bearing swung 25 to 40 deg between pictures at 2 to 4 in.)"""
import pytest

from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.tests.test_ball_chase import reading


def test_the_gyro_stop_leaves_early_by_the_coast_but_never_ends_a_small_turn_before_it_begins():
    assert bc.align_stop_lead(20.0) == bc.ALIGN_COAST_DEG                              # a big turn: the whole coast
    assert bc.ALIGN_STOP_LEAD_DEG <= bc.align_stop_lead(6.0) < bc.ALIGN_COAST_DEG       # a small one: less, so it still starts (the 2026-11-15 goal runs: asked 6, got 9 on average with the old 1.5 lead)
    assert bc.align_stop_lead(20.0, coast_deg=3.0) == 3.0                              # a learned coast replaces the constant
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


def test_a_move_leaves_the_imu_print_on(monkeypatch):
    """2026-11-15 goal run: every move ended with `gp`, so G2 stood waiting for each picture with the IMU print off (62 pictures with no frames, 33 guard resends)."""
    from pi_pipeline.tests.test_ball_chase import _gyro_robot
    r, lk = _gyro_robot(28.0)
    r.turn(30.0, 1.0, stop_deg=5.0)
    sent = [c for c, _ in lk.sent]
    assert "gP" in sent and "gp" not in sent
    monkeypatch.setattr(bc, "IMU_PRINT_STAYS_ON", False)
    r2, lk2 = _gyro_robot(28.0)
    r2.turn(30.0, 1.0, stop_deg=5.0)
    assert "gp" in [c for c, _ in lk2.sent]                                            # the old behavior is one switch


def test_the_coast_is_learned_from_the_turns_of_the_session(monkeypatch):
    from pi_pipeline.tests.test_ball_chase import _gyro_robot
    r, lk = _gyro_robot(28.0, coast_deg=6.0)
    assert r._coast_deg is None
    r.turn(30.0, 1.0, stop_deg=20.0)
    assert r._coast_deg is not None and bc.ALIGN_STOP_LEAD_DEG <= r._coast_deg <= 8.0


def test_the_legs_are_checked_for_sag_again_when_the_last_check_is_old(monkeypatch):
    """2026-11-15: 11.5 s standing still, the legs sagged after the one clean check of that stand (roll 22 deg), and the next move threw him over."""
    from pi_pipeline.tests.test_ball_chase import _PoseLink
    lk = _PoseLink("stand")
    t = {"now": 0.0}
    r = bc.SerialRobot(lk, sleep=lambda s: t.__setitem__("now", t["now"] + s), clock=lambda: t["now"])
    seen = []
    r._tilt = lambda *a, **k: seen.append(t["now"]) or (0.0, 0.0)
    r.posture, r._moved_at = "stand", 0.0
    t["now"] = 6.0
    r.stand_up()
    t["now"] = 7.0
    r.stand_up()                                                                       # 1 s later: not again
    t["now"] = 11.5
    r.stand_up()                                                                       # 5.5 s after the first: checked again
    assert len(seen) == 2 and seen[1] - seen[0] >= bc.SAG_RECHECK_S


def test_a_ball_at_the_frame_edge_is_never_read_as_an_overshoot():
    """2026-11-15 attempt 150: the ball sat at the frame edge (bearing clipped to about -39) and a turn that showed it there was called an overshoot: back up and start again."""
    p = bc.ChasePlanner()
    p.prev_kind, p.turn_before = "turn", 25.0
    edge = bc.bf.BallReading(120.0, 110.0, 500, 30, 30, 30.0, 6.0, -44.0, True) if hasattr(bc, "bf") else None
    if edge is None:
        from pi_pipeline.vision import ball_finder as bf
        edge = bf.BallReading(120.0, 110.0, 500, 30, 30, 30.0, 6.0, -44.0, True)
    assert p.decide(edge).kind != "back"
    p2 = bc.ChasePlanner()
    p2.prev_kind, p2.turn_before = "turn", 25.0
    from pi_pipeline.vision import ball_finder as bf
    assert p2.decide(bf.BallReading(120.0, 110.0, 500, 30, 30, 30.0, 6.0, -44.0, False)).kind == "back"     # the same reading away from the edge still is
