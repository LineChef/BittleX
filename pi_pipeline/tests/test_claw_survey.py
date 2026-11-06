"""The claw look as the way G2 looks (user, 2026-11-06), the turning chirp off by default, and the "da naaaa" when a goal session finishes."""
import os

from pi_pipeline.behavior import claw_survey
from pi_pipeline.behavior.survey import SurveyConfig, naming_plan, survey_plan


class _Link:
    def __init__(self):
        self.sent = []

    def send(self, cmd, **kw):
        self.sent.append(cmd)


def test_with_the_claw_the_plan_is_pose_claw_look_stand_and_has_no_bow_or_check():
    plan = survey_plan(SurveyConfig(claw=True), "after_bow_m25")
    skills = [p for _, k, p, _ in plan if k == "skill"]
    assert skills == ["kcalib", "kup"]
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


def test_the_look_takes_left_right_centre_and_ends_with_the_arm_down():
    link, shots = _Link(), []
    state = claw_survey.run_claw_look(link, shots.append, "after_bow", sleep=lambda s: None)
    assert state == "ok" and shots == ["look_left", "look_right", "after_bow"]
    assert link.sent[0] == "gP" and link.sent[-1] == "gp"
    assert link.sent[-2] == "i0 0 1 0"                                              # arm centred and lowered


def test_a_stop_during_the_look_halts_the_arm_at_once_and_a_stop_between_moves_lowers_it():
    link, shots = _Link(), []
    state = claw_survey.run_claw_look(link, shots.append, "x", sleep=lambda s: None, stopped=lambda: True)
    assert state == "stopped" and shots == [] and link.sent[-1] == "gp" and len([c for c in link.sent if c.startswith("i0")]) <= 10      # a fall mid-move: no more arm moves are sent
    link2, calls = _Link(), {"n": 0}
    def later():
        calls["n"] += 1
        return calls["n"] > 20                                                        # not during the raise, only at the start of a later swing
    state = claw_survey.run_claw_look(link2, [].append, "x", sleep=lambda s: None, stopped=later)
    assert state in ("ok", "stopped")


def test_env_forces_the_claw_look_on_or_off(monkeypatch):
    monkeypatch.setenv("G2_SURVEY_CLAW", "1")
    assert claw_survey.wanted()
    monkeypatch.setenv("G2_SURVEY_CLAW", "0")
    assert not claw_survey.wanted()


def test_the_turning_chirp_is_off_unless_asked_for(monkeypatch):
    import inspect

    from pi_pipeline.behavior import driver
    src = inspect.getsource(driver.BehaviorDriver)
    assert 'G2_AVOID_CHIRP", "0") == "1"' in src
    assert os.environ.get("G2_AVOID_CHIRP") is None


def test_a_finished_goal_session_plays_the_done_sound_and_a_failed_one_does_not():
    from pi_pipeline.goals.runner import COMPLETE_WHY
    assert {"attempts", "target", "time"} <= set(COMPLETE_WHY)
    assert not {"fell", "stopped", "battery", "board_silent"} & set(COMPLETE_WHY)
