"""The turn skill is chosen in one place (link/opencat.turn_tokens): the arc turns by default, the in-place pivots with G2_TURN_GAIT=pivot, in every mode (owner, 2026-11-18)."""
import importlib.util
from pathlib import Path

from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.behavior import transition_drill
from pi_pipeline.link import opencat

ROOT = Path(__file__).resolve().parents[2]


def test_the_default_turn_is_the_arc_and_the_switch_makes_it_the_pivot(monkeypatch):
    monkeypatch.delenv("G2_TURN_GAIT", raising=False)
    assert opencat.turn_tokens() == ("kwkR", "kwkL")
    monkeypatch.setenv("G2_TURN_GAIT", "pivot")
    assert opencat.turn_tokens() == ("kvtR", "kvtL")
    monkeypatch.setenv("G2_TURN_GAIT", "nonsense")
    assert opencat.turn_tokens() == ("kwkR", "kwkL")                                   # anything but "pivot" is the arc


def test_every_mode_that_turns_takes_its_skill_from_the_one_choice(monkeypatch):
    monkeypatch.setenv("G2_TURN_GAIT", "pivot")
    assert bc.SerialRobot.__init__.__code__ and "turn_tokens" in bc.SerialRobot.__init__.__code__.co_names               # the chase's line-up turns
    import inspect
    from pi_pipeline.app import sinks
    from pi_pipeline.behavior import bindings
    assert "opencat.turn_tokens()" in inspect.getsource(sinks)                                                            # the timed turn of the walk bindings
    assert "turn_tokens" in inspect.getsource(bindings)                                                                  # the behaviour runtime's turn effect
    import pi_pipeline.gait.jam_guard as jg
    import pi_pipeline.vision.cliff_guard as cg
    assert jg.JamGuardConfig().turn_left_token == "kvtL" and jg.JamGuardConfig().turn_right_token == "kvtR"
    cfg = next(c for c in vars(cg).values() if isinstance(c, type) and hasattr(c, "__dataclass_fields__") and "turn_left_token" in c.__dataclass_fields__)
    assert cfg().turn_left_token == "kvtL" and cfg().turn_right_token == "kvtR"                                         # the escape turns follow the switch too


def test_the_pivot_has_its_own_longer_cap_and_the_cycle_stop_and_measurement_know_it():
    assert bc.align_cap_for("kwkL") == bc.ALIGN_CAP_S == 1.5
    assert bc.align_cap_for("kvtR") == bc.PIVOT_ALIGN_CAP_S == 4.0 and bc.align_cap_for("kvtL") == 4.0
    assert "kvtL" in transition_drill.MEASURE_GAITS and "kvtR" in transition_drill.MEASURE_GAITS                        # the cycle length is measured like the other gaits'


def test_the_mode_check_blocks_a_second_turn_skill_choice():
    spec = importlib.util.spec_from_file_location("check_modes_t", ROOT / "tools" / "check_modes.py")
    cm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cm)
    assert cm.TURN_SKILL.search("fn(opencat.WALK_RIGHT if rad >= 0 else opencat.WALK_LEFT)")
    assert not cm.TURN_SKILL.search("fn(opencat.turn_tokens()[0])")


def test_the_pivot_keeps_to_a_whole_cycle_but_the_arc_turn_does_not_unless_its_own_switch_is_on(monkeypatch):
    monkeypatch.setattr(bc, "PIVOT_CYCLE_STOP", True)
    monkeypatch.setattr(bc, "CYCLE_STOP", False)
    assert bc.cycle_stop_for("kvtL") and bc.cycle_stop_for("kvtR") and not bc.cycle_stop_for("kwkL")                    # the pivots only (owner, 2026-11-18)
    monkeypatch.setattr(bc, "CYCLE_STOP", True)
    assert bc.cycle_stop_for("kwkL") and bc.cycle_stop_for("kbkF") and not bc.cycle_stop_for("kcrL")
    monkeypatch.setattr(bc, "PIVOT_CYCLE_STOP", False)
    assert not bc.cycle_stop_for("kvtR")


class _Fake:
    def __init__(self, tilt, fell=False):
        self._claw, self._t, self.fixed, self._fell_now = (0.0, 60.0), tilt, [], fell

    def _tilt(self, secs):
        return self._t

    def _already_fell(self, t):
        return self._fell_now

    def recover_sag(self, t):
        self.fixed.append(t)
        return "ok"


def test_after_a_pivot_the_tilt_and_arm_are_kept_and_a_nose_up_lean_is_put_right_at_once(monkeypatch):
    monkeypatch.setattr(bc, "PIVOT_LEAN_DEG", 8.0)
    f = _Fake((-20.0, 1.0))
    bc.SerialRobot._after_pivot(f)
    assert f.last_end_tilt == (-20.0, 1.0) and f.last_turn_arm == (0.0, 60.0) and f.last_lean_fix is True and f.fixed == [(-20.0, 1.0)] and f.pivot_lean_fixes == 1
    for t in ((-5.0, 0.0), (15.0, 0.0), (0.0, 25.0)):                                                                  # level, nose DOWN or rolled: not this check's job (the move gate has them)
        f = _Fake(t)
        bc.SerialRobot._after_pivot(f)
        assert f.fixed == [] and f.last_end_tilt == t
    monkeypatch.setattr(bc, "PIVOT_LEAN_DEG", 0.0)                                                                      # switched off
    f = _Fake((-30.0, 0.0))
    bc.SerialRobot._after_pivot(f)
    assert f.fixed == []
    monkeypatch.setattr(bc, "PIVOT_LEAN_DEG", 8.0)
    f = _Fake((-45.0, 0.0), fell=True)                                                                                  # already fallen: never stood up here (the fall path lays him in rest)
    bc.SerialRobot._after_pivot(f)
    assert f.fixed == []


def test_the_pivot_has_eased_stop_frames_and_the_mirror_for_the_right_pivot():
    from pi_pipeline.behavior import eased_stop
    left, lmir = eased_stop.gait_frames("kvtL", False)
    right, rmir = eased_stop.gait_frames("kvtR", False)
    assert left and len(left) == 72 and not lmir and right is left and rmir                                            # vtR is the firmware's mirror of vtL
    assert eased_stop.pose_at("kvtR", 0.3, 0.86) is not None
