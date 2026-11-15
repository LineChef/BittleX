"""BallTrack (behavior/ball_track.py): inside 3 in or at the frame edge the camera bearing is not usable, so the chase goes on the last good picture plus what he has done since."""
import pytest

from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.behavior.ball_track import BallTrack
from pi_pipeline.tests.test_ball_chase import reading
from pi_pipeline.vision import ball_finder as bf


def edge_reading(dist, bearing):
    return bf.BallReading(120.0, 110.0, 500, 30, 30, 30.0, dist, bearing, True)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_a_good_picture_is_used_as_it_is_and_remembered():
    t = BallTrack()
    r = reading(6.0, 14.0)
    assert t.see(r) is r and t.bearing() == pytest.approx(14.0)


def test_a_turn_moves_the_tracked_bearing_the_other_way_and_a_walk_brings_it_nearer():
    t = BallTrack()
    t.see(reading(6.0, 20.0))
    t.turned(15.0)                                                                       # turned right 15: the ball is 15 deg farther left
    assert t.bearing() == pytest.approx(5.0, abs=0.1)
    t.turned(-10.0)
    assert t.bearing() == pytest.approx(15.0, abs=0.1)
    t.walked(3.0)                                                                        # a ball off to the side: walking forward swings its bearing outward
    assert t.bearing() > 15.0
    assert t.y == pytest.approx(6.0 * 0.966 - 3.0, abs=0.2) or t.y > 0


def test_a_blind_picture_is_answered_with_the_tracked_bearing():
    t = BallTrack()
    t.see(reading(6.0, 14.0))
    t.turned(10.0)
    got = t.see(reading(2.0, -30.0))                                                     # 2 in: the camera reading swings
    assert got.bearing_deg == pytest.approx(4.0, abs=0.2) and got.distance_in == 2.0 and t.used_estimate
    edge = t.see(edge_reading(5.0, -39.0))                                               # at the frame edge: clipped
    assert edge.bearing_deg == pytest.approx(4.0, abs=0.2)


def test_with_no_good_picture_or_an_old_or_moved_track_the_camera_reading_stands():
    t = BallTrack()
    blind = reading(2.0, -30.0)
    assert t.see(blind) is blind and not t.used_estimate                                 # nothing to go on
    c = Clock()
    t = BallTrack(clock=c)
    t.see(reading(6.0, 14.0))
    c.t = 25.0
    assert t.see(blind) is blind                                                         # too old
    t = BallTrack()
    t.see(reading(6.0, 14.0))
    t.walked(9.0)
    assert t.see(blind) is blind                                                         # walked too far to trust it
    t = BallTrack()
    t.see(reading(6.0, 14.0))
    t.clear()
    assert t.see(blind) is blind


def test_the_planner_lines_up_on_the_track_inside_3_in_not_on_the_swinging_camera_reading():
    """2026-11-15 attempt 154: at 2 in a 5 deg turn moved the camera bearing from +10 to -22 and he kept turning on noise."""
    p = bc.ChasePlanner()
    bc.ALIGN_CONFIRM_IN = 0.0
    try:
        far = p.decide(reading(6.0, 14.0))
        assert far.kind == "align"
        p.track.turned(13.0)                                                             # the turn he made (the gyro's count)
        near = p.decide(reading(2.0, -30.0))                                             # the camera now swings to -30; the track says +1
        assert near.kind in ("punt", "walk") and near.kind != "align"
        assert p.track.used_estimate
    finally:
        bc.ALIGN_CONFIRM_IN = 5.0


def test_losing_the_ball_for_good_clears_the_track():
    p = bc.ChasePlanner()
    p.decide(reading(6.0, 14.0))
    assert p.track.valid
    for _ in range(bc.LOST_LOOKS + 1):
        p.decide(None)
    assert not p.track.valid
