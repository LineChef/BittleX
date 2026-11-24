"""The claw look as the way G2 looks (user, 2026-11-06), the turning chirp off by default, and the "da naaaa" when a goal session finishes."""
import os

from pi_pipeline.behavior import claw_survey
from pi_pipeline.behavior.survey import SurveyConfig, naming_plan, survey_plan


class _Link:
    def __init__(self):
        self.sent = []

    def send(self, cmd, **kw):
        self.sent.append(cmd)


def test_with_the_claw_the_plan_is_the_one_standard_look_and_has_no_bow_or_check():
    """Owner, 2026-11-12: the look is one standard move; the plan does not put him in the attention pose or stand him up around it."""
    plan = survey_plan(SurveyConfig(claw=True), "after_bow_m25")
    skills = [p for _, k, p, _ in plan if k == "skill"]
    assert skills == []
    claw = [(k, p) for _, k, p, _ in plan if k == "claw"]
    assert claw == [("claw", "after_bow_m25")]                                     # the milestone name rides on the centre picture
    assert not any(k == "shot" for _, k, _, _ in plan)                              # the pictures are taken inside the look
    assert [d for d, *_ in plan] == sorted(d for d, *_ in plan)


def test_without_the_claw_the_old_looks_stay():
    plan = survey_plan(SurveyConfig(claw=False))
    assert [p for _, k, p, _ in plan if k == "skill"][:2] == ["ksit", "kbuttUp"]
    assert any(k == "shot" for _, k, _, _ in plan)


def test_naming_uses_the_claw_look_too():
    plan = naming_plan("mug", SurveyConfig(claw=True))
    assert ("claw", "name:mug") in [(k, p) for _, k, p, _ in plan]


class _Robot:
    """A chase robot that records the moves: what the standard look asks of him."""

    def __init__(self, fell_at=None):
        self.moves, self._lk, self.fell_at = [], type("L", (), {"imu_print_on": False, "sent": [], "send": lambda s, c, **k: s.sent.append(c) or ""})(), fell_at

    def sit_down(self):
        self.moves.append("sit_down")
        return "ok"

    def claw_pose(self, pan, lift):
        self.moves.append(("claw", pan, lift))
        return "fell" if self.fell_at == len(self.moves) else "ok"

    def stand_from_sit(self):
        self.moves.append("stand_from_sit")
        return "ok"

    def _tx(self, c):
        self._lk.send(c)


def test_the_standard_look_is_the_chases_sequence_stand_first_attention_claw_up_left_right_centre_lower_stand():
    """Owner, 2026-11-13: ONE claw look, the ball chase's (ball_chase.claw_look_sequence); the survey, the voice loop and the drill call it. It is the whole move: nobody puts him in the attention pose or stands him up."""
    from pi_pipeline.behavior import ball_chase as bc
    r, shots = _Robot(), []
    state = claw_survey.run_claw_look(None, shots.append, "after_bow", sleep=lambda s: None, robot=r)
    left = bc.CLAW_PAN_DEG if bc.CLAW_PAN_SIGN == "left" else -bc.CLAW_PAN_DEG
    assert state == "ok" and shots == ["look_left", "look_right", "after_bow"]
    assert r.moves == ["sit_down", ("claw", 0.0, bc.CLAW_LIFT_DEG), ("claw", left, bc.CLAW_LIFT_DEG), ("claw", -left, bc.CLAW_LIFT_DEG), ("claw", 0.0, bc.CLAW_LIFT_DEG), ("claw", 0.0, 0.0), "stand_from_sit"]


def test_the_confirm_look_is_the_same_move_with_the_centre_picture_alone():
    """Owner, 2026-11-24: the basket goal's confirm look is ONE picture from close to the tub. Not a second look: `centre_only` of the shared function, so the stand, the attention pose, the claw moves and the stand-up are the ones every look makes."""
    from pi_pipeline.behavior import ball_chase as bc
    r, shots = _Robot(), []
    state = claw_survey.run_claw_look(None, shots.append, "centre", sleep=lambda s: None, robot=r, centre_only=True)
    assert state == "ok" and shots == ["centre"]
    assert r.moves == ["sit_down", ("claw", 0.0, bc.CLAW_LIFT_DEG), ("claw", 0.0, bc.CLAW_LIFT_DEG), ("claw", 0.0, 0.0), "stand_from_sit"]      # raised, the one centre pose (the settle and the picture), lowered, stood up


def test_a_stop_between_moves_ends_the_look_with_the_claw_lowered_and_a_fall_ends_it_at_once():
    r, shots = _Robot(), []
    n = {"i": 0}

    def stopped():
        n["i"] += 1
        return n["i"] > 1                                                   # after the first picture
    assert claw_survey.run_claw_look(None, shots.append, "x", sleep=lambda s: None, stopped=stopped, robot=r) == "stopped"
    assert shots == ["look_left"] and ("claw", 0.0, 0.0) in r.moves and r.moves[-1] == "stand_from_sit"      # lowered and stood up: he is never left in the attention pose with the claw up
    f = _Robot(fell_at=2)                                                   # the second claw move reports a fall
    assert claw_survey.run_claw_look(None, [].append, "x", sleep=lambda s: None, robot=f) == "stopped"
    assert "stand_from_sit" not in f.moves and ("claw", 0.0, 0.0) not in f.moves       # no more arm moves and no stand-up on a fallen G2


def test_pictures_discard_one_stale_frame_first_and_a_missed_side_picture_skips_the_other():
    r, got, drops = _Robot(), [], []
    state = claw_survey.run_claw_look(None, lambda lb: got.append(lb) or None, "look", sleep=lambda s: None, discard=lambda: drops.append(1), miss_skips=True, robot=r)
    assert state == "ok" and got == ["look_left", "look"] and len(drops) == 2          # the camera missed look_left: look_right is skipped, the one that counts is still taken
    got2, drops2 = [], []
    claw_survey.run_claw_look(None, lambda lb: got2.append(lb), "look", sleep=lambda s: None, discard=lambda: drops2.append(1), robot=_Robot())
    assert got2 == ["look_left", "look_right", "look"] and len(drops2) == 3


def test_a_failure_in_the_look_never_raises():
    class Boom(_Robot):
        def sit_down(self):
            raise RuntimeError("serial gone")
    assert claw_survey.run_claw_look(None, None, "x", sleep=lambda s: None, robot=Boom()) == "error"


def test_the_motion_sensor_print_is_put_back_after_the_look():
    from pi_pipeline.behavior import ball_chase as bc
    on = _Robot()
    on._lk.imu_print_on = True
    bc.claw_look_sequence(on, lambda pan: False, pans=[0.0], sleep=lambda s: None)
    assert on._lk.sent[-1] == "gP"                                           # was on before: on after (the guards read it)
    off = _Robot()
    bc.claw_look_sequence(off, lambda pan: False, pans=[0.0], sleep=lambda s: None)
    assert "gP" not in off._lk.sent


class _BusyWalker:
    """A policy walker whose thread is still running (what `walk_active` sees)."""
    busy = True


def test_the_claw_look_never_starts_while_a_policy_walk_runs(monkeypatch):
    """2026-11-14: the attention pose and the arm moves went out while the policy walk was still driving the legs, and G2 went onto his back. Every mode's look is this one function."""
    from pi_pipeline.gait import policy_walker
    monkeypatch.setattr(policy_walker, "_WALKERS", [_BusyWalker()])
    robot, slept = _Robot(), []
    assert claw_survey.run_claw_look(None, None, "look", sleep=slept.append, robot=robot) == "stopped"
    assert sum(slept) >= claw_survey.WALK_WAIT_S - 0.3                                # it waited for the walk to end first
    assert robot.moves == []                                                          # and moved nothing


def test_the_claw_look_goes_on_once_the_walk_has_ended(monkeypatch):
    from pi_pipeline.gait import policy_walker
    w = _BusyWalker()
    monkeypatch.setattr(policy_walker, "_WALKERS", [w])
    n = []

    def sleep(s):
        n.append(s)
        if len(n) == 3:
            w.busy = False                                                            # the walker thread ended
    robot = _Robot()
    assert claw_survey.run_claw_look(None, None, "look", sleep=sleep, robot=robot) == "ok"
    assert robot.moves[0] == "sit_down" and len(n) >= 3


def test_a_real_walker_registers_itself_for_the_check():
    from pi_pipeline.gait import policy_walker
    w = policy_walker.PolicyWalker(_Link())
    assert w in policy_walker._WALKERS and not policy_walker.walk_active()
