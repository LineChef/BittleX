"""The sim training's world (tools/sim_train) must be deterministic, leak nothing between attempts, get the camera geometry right and pass the searched settings to the real chase code."""
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "sim_train"))
import world  # noqa: E402
from pi_pipeline.behavior import ball_chase as bc  # noqa: E402
from pi_pipeline.behavior import punt_settings as ps  # noqa: E402

CUR = {"punt_max_in": 4.0, "nudge_max_in": 7.0, "nudges_before_punt": 3, "nudge_step_s": 0.9, "walk_aim_in": 4.0, "lost_looks": 3, "when_vanished": "punt", "search_order": "back_turn",
       "scan_turn_deg": 60.0, "search_step_deg": 20.0}


def _full(**kw):
    return {**ps.defaults(bc), **CUR, **kw}


def test_a_ball_to_the_right_reads_a_positive_bearing_and_a_pan_away_loses_it():
    w = world.World(random.Random(1), "ahead", {}); w.x = w.y = 50.0; w.W = w.H = 200; w.h = 0.0; w.drop = w.miss = w.decoy = 0
    w.bx, w.by = 50 + 20 * math.cos(math.radians(-30)), 50 + 20 * math.sin(math.radians(-30))
    r = world.Camera(w).look()[1]
    assert 25 < r.bearing_deg < 35 and 15 < r.distance_in < 19
    w.pan = 35.0                                          # the camera turned LEFT (claw_pan_sign left): the ball is 65 deg off, out of the picture
    assert world.Camera(w).look()[1] is None


def test_the_same_seed_gives_the_same_attempt_and_nothing_leaks_from_the_one_before():
    a = world.run_episode(_full(), "side", 4242, {})[:3]
    for i in range(5):
        world.run_episode(_full(walk_aim_in=6.5, search_order="claw_scan", lost_looks=1, nudges_before_punt=0, punt_max_in=3.2), "behind", 900 + i, {})
    assert world.run_episode(_full(), "side", 4242, {})[:3] == a


def test_the_searched_settings_and_the_pins_reach_the_real_chase_code():
    world.run_episode(_full(walk_aim_in=6.5, search_order="claw_scan", punt_max_in=3.3), "ahead", 3, {})
    assert bc.WALK_AIM_IN == 6.5 and bc.SEARCH_ORDER == "claw_scan" and bc.PUNT_MAX_IN == 3.3
    assert bc.ALIGN_TRIES == 3 and bc.PUNT_ALIGN_DEG == 12.0 and bc.CLAW_PAN_SIGN == "left" and bc.BETWEEN_MOVES == "stand"       # pinned


def test_a_walk_into_a_wall_bumps_and_the_ball_it_reaches_stops_him():
    w = world.World(random.Random(2), "ahead", {}); w.x, w.y, w.h, w.W, w.H = 20.0, 30.0, 180.0, 100, 100; w.bx, w.by = 90.0, 90.0
    bot = world.Bot(w); bot.walk(10.0)
    assert bot.bumped and w.x == 4.0                    # the wall behind the heading stopped him at the edge


def test_a_session_carries_the_ball_and_the_robot_from_one_attempt_to_the_next():
    """The owner does not put the ball back between attempts (2026-11-02): a session is one world, attempts one after another, the later ones labelled "chained"."""
    res = world.run_session(_full(), "ahead", 11, {}, n_att=4)
    assert [r[3] for r in res] == ["ahead", "chained", "chained", "chained"]
    assert world.run_session(_full(), "ahead", 11, {}, n_att=4) == res                      # deterministic
    first_alone = world.run_episode(_full(), "ahead", 11, {})
    assert res[0][:3] == first_alone[:3]                                                     # the first attempt of a session is the same attempt as a lone one
