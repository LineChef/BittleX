

def test_a_walk_leg_ends_by_blending_the_legs_to_the_balance_pose_not_snapping_there():
    """2026-10-10: exploration legs ended with one foot in the air; the legs now ease from the last stride pose to balance first."""
    from pi_pipeline.gait import standup
    sent = []
    stride = standup.move_cmd([60, -9, 20, 27, 40, 0, 25, 10])
    assert standup.blend_to_balance(sent.append, last_motion_command=stride, sleep=lambda s: None, seconds=0.6)
    assert len(sent) >= 10 and sent[-1] == standup.move_cmd(standup.BALANCE_URDF_DEG)
    firsts = [standup.start_pose(c) for c in sent[:2]]
    assert firsts[0][1] < firsts[1][1] < standup.BALANCE_URDF_DEG[1] + 0.01 or firsts[0][1] > firsts[1][1]      # monotone toward the balance pose
    assert standup.blend_to_balance(sent.append, last_motion_command="kwkF", sleep=lambda s: None) is False         # an unknown pose is left to the firmware
