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
    src = (ROOT / "pi_pipeline" / "behavior" / "ball_chase.py").read_text()
    assert 'CYCLE_STOP and token in ("kwkL", "kwkR", "kbkF", "kwkF", "kvtL", "kvtR")' in src                           # the whole-cycle stop covers the pivots (still off by default)


def test_the_mode_check_blocks_a_second_turn_skill_choice():
    spec = importlib.util.spec_from_file_location("check_modes_t", ROOT / "tools" / "check_modes.py")
    cm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cm)
    assert cm.TURN_SKILL.search("fn(opencat.WALK_RIGHT if rad >= 0 else opencat.WALK_LEFT)")
    assert not cm.TURN_SKILL.search("fn(opencat.turn_tokens()[0])")
