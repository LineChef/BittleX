"""The pose editor (behavior/pose_edit.py) and the scripted-skill player (behavior/scripted_skill.py): the edits it parses, the limits, the frames it builds and the poses it keeps."""
import pytest

from pi_pipeline.behavior import pose_edit as pe
from pi_pipeline.behavior import scripted_skill as ss

BASE = [0, 0, 0, 0, 0, 0, 0, 0, 20, 20, 30, 30, 30, 30, 30, 30]


def test_edits_are_absolute_or_relative_and_groups_expand_to_their_joints():
    edits = pe.parse_edits(["fkn=-15", "rsh+=10", "jaw-=5"])
    assert edits == [(12, "=", -15.0), (13, "=", -15.0), (10, "+=", 10.0), (11, "+=", 10.0), (2, "-=", 5.0)]
    new, notes = pe.apply_edits(BASE, edits)
    assert new[12] == new[13] == -15 and new[10] == new[11] == 40 and new[2] == -5 and new[8] == 20 and notes == []


def test_an_edit_it_does_not_know_is_refused():
    for bad in ("fkn", "fkn=", "xyz=5", "j4=5", "lift=a", "fkn*=2"):
        with pytest.raises(ValueError):
            pe.parse_edits([bad])


def test_angles_are_clipped_to_the_joint_range_and_a_big_jump_is_refused():
    raised = list(BASE)
    raised[1], raised[2] = 100, -50
    new, notes = pe.apply_edits(raised, pe.parse_edits(["lift=140"]))
    assert new[1] == 135 and "clipped" in notes[0]
    new, notes = pe.apply_edits(raised, pe.parse_edits(["lift=130"]))
    assert new[1] == 130 and notes == []                                                     # above the 125 a skill frame carries: set by a direct command after the move
    new, notes = pe.apply_edits(raised, pe.parse_edits(["jaw=-120"]))
    assert new[2] == -100
    with pytest.raises(ValueError, match="at once"):
        pe.apply_edits(BASE, pe.parse_edits(["fkn=-60"]))                                 # 90 degrees from 30


def test_a_pose_is_kept_and_read_back_by_name_and_a_bad_name_is_refused(tmp_path):
    store = str(tmp_path)
    assert pe.list_poses(store) == []
    pe.save_pose("bow", [1] * 16, "front down", store)
    assert pe.load_pose("bow", store) == [1] * 16 and pe.list_poses(store) == ["bow"]
    for bad in ("", "a b", "../x", "x" * 41):
        with pytest.raises(ValueError):
            pe.pose_path(bad, store)


def test_one_frame_message_is_a_k_skill_ending_the_way_the_link_expects():
    m = pe.frame_message(BASE, 12, 2)
    assert m[:1] == b"K" and m[-1:] == b"~"


POSES = {"bow": [0] * 8 + [90, 90, 45, 45, -60, -60, 5, 5], "up": [0, 100, 30] + [0] * 5 + [21, 21, 60, 60, 35, 35, -34, -34]}


def test_a_script_frame_takes_a_pose_only_for_the_joints_it_names_and_scales_by_amount():
    script = {"frames": [{"name": "bow", "pose": "bow", "joints": ["legs"], "speed": 6, "delay_s": 0.4},
                         {"name": "swing", "pose": "up", "joints": ["lift", "fsh"], "speed": 127},
                         {"name": "back", "pose": "start", "speed": 6}]}
    plan = ss.build_plan(script, BASE, amount=1.0, pose_lookup=POSES.__getitem__)
    assert plan[0]["frame"][8:] == POSES["bow"][8:] and plan[0]["frame"][1] == 0 and plan[0]["delay"] == 8
    assert plan[1]["frame"][1] == 100 and plan[1]["frame"][8:10] == [21, 21] and plan[1]["frame"][10:12] == [45, 45]       # only the lift and the front shoulders changed
    assert plan[2]["frame"] == BASE                                                                                      # back to the start
    half = ss.build_plan(script, BASE, amount=0.5, pose_lookup=POSES.__getitem__)
    assert half[0]["frame"][8] == round(20 + 0.5 * (90 - 20))


def test_script_values_out_of_range_are_refused_and_the_example_script_is_valid():
    ok = {"frames": [{"pose": "start"}]}
    for bad in ({"frames": []}, {"frames": [{"pose": "bow", "speed": 128}]}, {"frames": [{"pose": "bow", "delay_s": 6}]}, {"frames": [{"name": "x"}]}, {"frames": [{"angles": [1, 2]}]},
                {"frames": [{"pose": "bow", "joints": ["nope"]}]}):
        with pytest.raises(ValueError):
            ss.build_plan(bad, BASE, pose_lookup=POSES.__getitem__)
    with pytest.raises(ValueError):
        ss.build_plan(ok, BASE, amount=0.0)
    plan = ss.build_plan(ss.load_script("crouch_example"), BASE, amount=1.0)
    assert [p["name"] for p in plan] == ["crouch", "back"] and plan[1]["frame"] == BASE


def test_the_bow_script_moves_all_four_legs_and_the_arm_in_one_frame_and_returns_to_the_stand():
    stand = [0, 0, 0, 0, 0, 0, 0, 0, 15, 15, 20, 20, 56, 56, 50, 50]
    plan = ss.build_plan(ss.load_script("bow"), stand, amount=1.0)
    assert [p["name"] for p in plan] == ["bow", "back_to_stand"]
    assert plan[0]["frame"][8:] == [-9, -9, -19, -19, -3, -3, 84, 84] and plan[0]["speed"] == 20
    assert plan[0]["frame"][:3] == [1, 125, 0]                                    # the pose records a lift of 135; a data skill carries 125 at most
    assert plan[1]["frame"] == stand


def test_the_last_commanded_pose_is_kept_for_a_save_when_the_board_cannot_be_read_and_a_tick_is_one_joint_step(tmp_path):
    store = str(tmp_path)
    assert pe.read_state(store) is None
    pe.write_state(list(range(16)), store)
    assert pe.read_state(store) == list(range(16))
    assert pe.step_edits("fsh", -15) == [(8, "-=", 15.0), (9, "-=", 15.0)]
    assert pe.step_edits("rkn", 15) == [(14, "+=", 15.0), (15, "+=", 15.0)]


def test_two_saved_poses_are_compared_joint_by_joint(tmp_path):
    store = str(tmp_path)
    a, b = [0] * 16, [0] * 16
    b[8], b[14] = 20, -45
    pe.save_pose("a", a, None, store)
    pe.save_pose("b", b, None, store)
    d = pe.diff_poses("a", "b", store)
    assert d == [("fls", 0, 20), ("brk", 0, -45)]
    assert pe.diff_poses("a", "a", store) == []


def test_the_catapult_launch_script_drops_the_claw_as_the_legs_rise_and_swings_it_back_up_as_they_finish():
    stand = [0, 0, 0, 0, 0, 0, 0, 0, 15, 15, 20, 20, 56, 56, 50, 50]
    plan = ss.build_plan(ss.load_script("catapult_launch"), stand, amount=1.0)
    assert [p["name"] for p in plan] == ["bow", "rise_and_drop", "lunge", "back_to_stand"]
    bow, drop, lunge, back = plan
    assert bow["frame"][1] == 125 and drop["frame"][1] == 0 and lunge["frame"][1] == 125            # down to the lowest in the middle of the rise, up to 125 at the end
    assert lunge["frame"][8:] == [20, 20, 70, 70, 100, 100, -35, -35] and lunge["speed"] == 127
    assert drop["frame"][8:12] == [6, 6, 26, 26]                                                      # the front and back shoulders about halfway between the bow and the launch pose
    assert back["frame"] == stand


def test_a_committed_pose_wins_over_a_pose_saved_on_the_pi():
    assert ss._pose_angles("launch")[1] == 125 and ss._pose_angles("launch")[8:] == [20, 20, 70, 70, 100, 100, -35, -35]


def test_the_release_angle_is_set_inside_the_lunge_frame_and_can_be_overridden_per_run():
    stand = [0, 0, 0, 0, 0, 0, 0, 0, 15, 15, 20, 20, 56, 56, 50, 50]
    script = ss.load_script("catapult_throw")
    plan = ss.build_plan(script, stand, amount=1.0)
    assert [p["name"] for p in plan] == ["bow", "rise_and_drop", "lunge", "open", "back_to_stand"]
    lunge, opened = plan[2], plan[3]
    assert lunge["frame"][2] == 26 and lunge["frame"][1] == 125 and lunge["speed"] == 127          # the jaw opens a few degrees while the arm swings up
    assert opened["frame"][2] == 60 and opened["speed"] == 0                                         # then fully open at once
    plan2 = ss.build_plan(script, stand, amount=1.0, overrides=ss.parse_overrides(["lunge.jaw=34"]))
    assert plan2[2]["frame"][2] == 34 and plan2[3]["frame"][2] == 60
    for bad in ("lunge", "lunge.jaw", "lunge.j4=3", "a.b=x"):
        with pytest.raises(ValueError):
            ss.parse_overrides([bad])
