"""The backward catapult (behavior/catapult.py): the frames it builds, the stage-by-stage check, and the wait for a pick to finish."""
import json

import pytest

from pi_pipeline.behavior import catapult as c

BASE = [0, 0, 0, 0, 0, 0, 0, 0, 20, 20, 30, 30, 30, 30, 30, 30]       # the legs and the arm as pickF leaves them


def test_the_bow_stage_only_bows_and_returns_with_the_arm_and_jaw_still():
    plan = c.build_plan("bow", BASE, amount=1.0)
    assert [p["name"] for p in plan] == ["bow", "return"]
    assert plan[0]["frame"][8:] == c.BOW_LEGS and plan[0]["frame"][c.LIFT] == 0 and plan[0]["frame"][c.JAW] == 0
    assert plan[1]["frame"][8:] == BASE[8:]                                                         # back to where the legs were


def test_the_swing_stage_swings_the_arm_with_the_launch_legs_and_keeps_the_jaw_shut():
    plan = c.build_plan("swing", BASE, amount=1.0, lift_top=90.0, speed=32)
    assert [p["name"] for p in plan] == ["bow", "swing", "return"]
    swing = plan[1]
    assert swing["frame"][8:] == c.LAUNCH_LEGS and swing["frame"][c.LIFT] == 90 and swing["frame"][c.JAW] == 0 and swing["speed"] == 32


def test_the_throw_stage_opens_the_jaw_during_the_swing_and_fully_at_speed_zero_after_it():
    plan = c.build_plan("throw", BASE, amount=1.0, lift_top=120.0, speed=127, jaw_delta=25.0)
    assert [p["name"] for p in plan] == ["bow", "swing", "open", "return"]
    assert plan[1]["frame"][c.JAW] == 25 and plan[1]["frame"][c.LIFT] == 120                        # the release starts inside the swing, not after it
    assert plan[2]["speed"] == 0 and plan[2]["frame"][c.JAW] == c.JAW_OPEN_DEG and plan[2]["frame"][c.LIFT] == 120
    assert plan[3]["frame"][c.JAW] == 0 and plan[3]["frame"][c.LIFT] == 0 and plan[3]["speed"] == c.SLOW_BYTE


def test_the_amount_scales_the_legs_between_where_they_are_and_the_poses():
    half = c.build_plan("swing", BASE, amount=0.5)
    assert half[0]["frame"][8:] == c.mix(BASE[8:], c.BOW_LEGS, 0.5)
    assert half[1]["frame"][8:] == c.mix(BASE[8:], c.LAUNCH_LEGS, 0.5)


REFUSED = [("nope", {}), ("bow", {"amount": 0.0}), ("bow", {"amount": 1.5}), ("swing", {"speed": 128}), ("swing", {"speed": -1}), ("swing", {"lift_top": 5.0}),
           ("swing", {"lift_top": 121.0}), ("throw", {"jaw_delta": 41.0}), ("throw", {"jaw_open": 10.0})]


def test_values_out_of_range_are_refused_before_anything_is_sent():
    for stage, kw in REFUSED:
        with pytest.raises(ValueError):
            c.build_plan(stage, BASE, **kw)
    with pytest.raises(ValueError):
        c.build_plan("bow", BASE[:8])                                                               # no angles for the legs: they cannot be held


def test_a_stage_runs_only_after_the_one_before_it_logged_a_run_with_the_body_ok(tmp_path):
    d = str(tmp_path)
    assert c.previous_stage_ok("bow", d) is None
    assert "bow" in c.previous_stage_ok("swing", d)
    (tmp_path / "20261121_100000_catapult_bow.json").write_text(json.dumps({"verdict": "tilt"}))
    assert c.previous_stage_ok("swing", d) is not None                                              # a bow run that did not end ok does not count
    (tmp_path / "20261121_100100_catapult_bow.json").write_text(json.dumps({"verdict": "ok"}))
    assert c.previous_stage_ok("swing", d) is None
    assert "swing" in c.previous_stage_ok("throw", d)


def test_the_pick_wait_ends_when_the_link_goes_quiet_and_gives_up_at_the_limit():
    class Link:
        def __init__(self, ends_after):
            self.n, self.ends_after = 0, ends_after

        def _quiet_active(self):
            self.n += 1
            return self.n <= self.ends_after

    now = [0.0]
    sleep = lambda s: now.__setitem__(0, now[0] + s)                                                # noqa: E731
    assert c.wait_skill_done(Link(3), 5.0, sleep=sleep, clock=lambda: now[0], min_s=0.0) is True
    now[0] = 0.0
    assert c.wait_skill_done(Link(10 ** 6), 1.0, sleep=sleep, clock=lambda: now[0], min_s=0.0) is False


def test_the_front_legs_can_have_their_own_amount_so_the_front_feet_stay_down():
    plan = c.build_plan("bow", BASE, amount=1.0, front_amount=0.5)
    legs = plan[0]["frame"][8:]
    assert legs[2:4] == c.BOW_LEGS[2:4] and legs[6:8] == c.BOW_LEGS[6:8]                              # the rear legs go the full way (the rump up)
    assert legs[0] == c.mix(BASE[8:], c.BOW_LEGS, 0.5)[0] and legs[4] == c.mix(BASE[8:], c.BOW_LEGS, 0.5)[4]      # the front legs half way
    with pytest.raises(ValueError):
        c.build_plan("bow", BASE, amount=1.0, front_amount=1.2)


def test_the_swing_can_use_the_sit_pose_the_old_look_up_and_an_unknown_pose_is_refused():
    plan = c.build_plan("swing", BASE, amount=1.0, launch_pose="sit")
    assert plan[1]["frame"][8:] == c.SIT_LEGS
    assert c.build_plan("swing", BASE, amount=1.0)[1]["frame"][8:] == c.LAUNCH_LEGS                 # the default is unchanged
    with pytest.raises(ValueError):
        c.build_plan("swing", BASE, launch_pose="flip")


def test_the_pick_wait_reads_the_port_but_an_early_k_does_not_end_it_before_the_minimum():
    class Link:
        def __init__(self):
            self.reads, self.quiet = 0, True

        def _quiet_active(self):
            return self.quiet

        def drain(self, seconds=0.3):
            self.reads += 1
            now[0] += seconds
            if self.reads == 2:
                self.quiet = False                                                                  # an old `k` came in and the link ended the silence at 0.2 s
                return "k"
            return ""

    now = [0.0]
    heard = []
    lk = Link()
    assert c.wait_skill_done(lk, 12.0, sleep=lambda s: pytest.fail("it must read the port, not just sleep"), clock=lambda: now[0], min_s=5.0, seen=heard) is True
    assert now[0] >= 5.0 and heard == [(0.2, "k")]                                                  # not before the minimum, and the line is on record


def test_the_pick_wait_ends_at_the_k_after_the_skills_own_name_not_at_an_old_k_and_not_at_the_minimum():
    script = ["k", "balance", "k", "pickF", "", "", "k"]                                            # an old k, then the name, then the end k (what the board sent on 2026-11-21)

    class Link:
        def __init__(self):
            self.reads = 0

        def _quiet_active(self):
            return True

        def drain(self, seconds=0.3):
            now[0] += seconds
            self.reads += 1
            return script.pop(0) if script else ""

    now = [0.0]
    heard = []
    lk = Link()
    assert c.wait_skill_done(lk, 12.0, clock=lambda: now[0], min_s=10.0, seen=heard, name="pickF") is True
    assert now[0] < 1.0 and [ln for _, ln in heard if ln] == ["k", "balance", "k", "pickF", "k"]


def test_the_pick_up_reads_the_old_lines_before_pickF_goes_out_so_they_cannot_end_its_silence(monkeypatch):
    order = []

    class Link:
        def drain(self, seconds=0.3):
            order.append("drain")
            return ""

        def send(self, command, **kw):
            order.append(command)

    monkeypatch.setattr(c, "wait_skill_done", lambda link, **kw: order.append(("wait", kw.get("name"))) or True)
    assert c.pick_up(Link()) is True
    assert order == ["drain", "kpickF", ("wait", "pickF")]                                          # the old `balance` and `k` are read before the skill is sent, then the wait is for pickF's own end


def test_inside_the_service_the_wait_ends_when_the_link_has_seen_the_end_echo_not_after_the_full_minimum():
    class Link:                                                       # the service's own reader takes the board's lines: drain sees nothing, but the link's silence ends at the `k`
        def __init__(self):
            self.t = 0.0

        def _quiet_active(self):
            return now[0] < 2.6

        def drain(self, seconds=0.3):
            now[0] += seconds
            return ""

    now = [0.0]
    assert c.wait_skill_done(Link(), 12.0, clock=lambda: now[0], min_s=10.0, name="pickF", echo_floor_s=c.PICK_ECHO_FLOOR_S) is True
    assert 3.6 <= now[0] < 4.5                                        # not at the 10 second minimum
    now[0] = 0.0

    class Early(Link):                                                # an old k ended the silence at once: still nothing before the floor
        def _quiet_active(self):
            return False
    assert c.wait_skill_done(Early(), 12.0, clock=lambda: now[0], min_s=10.0, name="pickF", echo_floor_s=c.PICK_ECHO_FLOOR_S) is True and now[0] >= 3.6
