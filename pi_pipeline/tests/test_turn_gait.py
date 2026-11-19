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


def test_the_line_up_turn_uses_both_gaits_the_pivot_only_in_a_band_and_the_switch_can_force_either(monkeypatch):
    for k in ("G2_LINEUP_GAIT", "G2_TURN_GAIT", "G2_PIVOT_MIN_IN", "G2_PIVOT_MAX_IN"):
        monkeypatch.delenv(k, raising=False)
    arc, piv = ("kwkR", "kwkL"), ("kvtR", "kvtL")
    assert opencat.lineup_tokens() == arc and opencat.lineup_tokens(None) == arc                    # distance unknown: the arc
    assert opencat.lineup_tokens(20.0) == arc and opencat.lineup_tokens(14.5) == arc                # far: the arc
    assert opencat.lineup_tokens(14.0) == piv and opencat.lineup_tokens(8.0) == piv and opencat.lineup_tokens(5.0) == piv     # the band: the pivot, a bit away from the ball
    assert opencat.lineup_tokens(4.9) == arc and opencat.lineup_tokens(3.0) == arc                  # right up against the ball: never the pivot (it pushes him forward a little)
    monkeypatch.setenv("G2_LINEUP_GAIT", "arc")
    assert opencat.lineup_tokens(8.0) == arc
    monkeypatch.setenv("G2_LINEUP_GAIT", "pivot")
    assert opencat.lineup_tokens(30.0) == piv
    monkeypatch.setenv("G2_LINEUP_GAIT", "auto")
    monkeypatch.setenv("G2_PIVOT_MIN_IN", "6")
    monkeypatch.setenv("G2_PIVOT_MAX_IN", "10")
    assert opencat.lineup_tokens(5.5) == arc and opencat.lineup_tokens(10.0) == piv and opencat.lineup_tokens(10.5) == arc
    assert opencat.turn_tokens() == arc                                                              # every other turn is unaffected


def test_a_line_up_turn_in_the_band_is_whole_pivot_cycles_and_outside_it_the_gyro_stopped_arc(monkeypatch):
    for k in ("G2_LINEUP_GAIT", "G2_TURN_GAIT", "G2_PIVOT_MIN_IN", "G2_PIVOT_MAX_IN", "G2_GAIT_CYCLE_S"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(bc.gait_cycle, "period_for", lambda *a, **k: (None, "none"))                 # no measured period: the 0.86 s default
    sent = []

    class R(bc.SerialRobot):
        def __init__(self):
            self.lineup_tokens, self.lineup_ball_in, self.turn_tokens = None, None, ("kwkR", "kwkL")

        def stand_up(self):
            return "ok"

        def _skill(self, token, seconds, stop_yaw_deg=None):
            sent.append((token, round(seconds, 3), stop_yaw_deg))
            return "ok"
    r = R()
    r.lineup_ball_in = 10.0
    r.turn(22.0, 1.0, stop_deg=22.0)                                   # one cycle (about 20 deg)
    assert sent[-1] == ("kvtR", round(0.75 * bc.PIVOT_CYCLE_S, 3), None) and r.last_turn_deg == 20.0 and r.last_turn_end == "cycles" and r.last_turn_signed == 20.0
    r.turn(-45.0, 1.0, stop_deg=45.0)                                  # two cycles, never more
    assert sent[-1] == ("kvtL", round(1.75 * bc.PIVOT_CYCLE_S, 3), None) and r.last_turn_deg == 40.0 and r.last_turn_signed == -40.0
    r.turn(14.0, 1.0, stop_deg=14.0)                                   # the smallest turn that is a pivot: one cycle
    assert sent[-1][0] == "kvtR" and r.last_turn_deg == 20.0
    r.turn(6.0, 1.0, stop_deg=6.0)                                     # an align pulse is smaller than one pivot cycle: the gyro-stopped arc (2026-11-18 goal run: a pivot turned it 3 to 7 times too far)
    assert sent[-1][0] == "kwkR" and sent[-1][2] == (6.0 if bc.ALIGN_YAW_STOP else None)
    r.turn(-6.0, 1.0, stop_deg=6.0)
    assert sent[-1][0] == "kwkL"
    r.lineup_ball_in = 3.0
    r.turn(8.0, 1.0, stop_deg=8.0)                                     # right up against the ball: the arc, stopped on the gyro as before
    assert sent[-1][0] == "kwkR" and sent[-1][2] == (8.0 if bc.ALIGN_YAW_STOP else None)
    r.lineup_ball_in = 30.0
    r.turn(-20.0, 1.0, stop_deg=20.0)
    assert sent[-1][0] == "kwkL"
    r.lineup_ball_in = 10.0
    r.turn(-20.0, 1.0)                                                 # a timed turn (no stop_deg) is not a line-up: its own choice
    assert sent[-1][0] == "kwkL"


def _planner_ask(monkeypatch, ball_in, bearing, **env):
    from pi_pipeline.tests.test_ball_chase import reading
    for k in ("G2_LINEUP_GAIT", "G2_PIVOT_MIN_IN", "G2_PIVOT_MAX_IN"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(bc, "ALIGN_CONFIRM_IN", 0.0)                                   # one picture is enough here
    a = bc.ChasePlanner().decide(reading(ball_in, bearing))
    assert a.kind == "align"
    return a


def test_in_the_pivot_band_the_line_up_is_asked_for_the_whole_bearing_up_to_two_cycles(monkeypatch):
    """2026-11-19 goal run: ball 34 deg off at 6 in, the planner asked 6 deg, the pivot starts at 14: it never ran."""
    assert _planner_ask(monkeypatch, 6.0, 34.0).stop_deg == 34.0                        # a whole bearing: 2 cycles of about 20 deg
    assert _planner_ask(monkeypatch, 7.0, -21.0).stop_deg == 21.0                        # 1 cycle (the line-up pulses are for a ball within the nudge range; farther out the plain turn already has the whole bearing)
    assert _planner_ask(monkeypatch, 6.0, 60.0).stop_deg == bc.PIVOT_DEG_PER_CYCLE * bc.PIVOT_MAX_CYCLES      # never more than the cap
    assert bc.PIVOT_MIN_DEG <= 34.0 and opencat.lineup_uses_pivot(6.0)


def test_outside_the_band_or_for_a_small_bearing_it_is_still_the_small_arc_pulse(monkeypatch):
    assert _planner_ask(monkeypatch, 3.0, 34.0).stop_deg <= bc.ALIGN_MAX_DEG            # right against the ball: the arc, small
    assert _planner_ask(monkeypatch, 6.0, 10.0).stop_deg <= bc.ALIGN_MAX_DEG            # under 14 deg: a pivot cycle would overshoot
    assert _planner_ask(monkeypatch, 6.0, 34.0, G2_LINEUP_GAIT="arc").stop_deg <= bc.ALIGN_MAX_DEG     # the arc setting keeps the small pulses


def test_the_switch_restores_the_small_pulses_and_the_planner_and_the_skill_choice_share_one_rule(monkeypatch):
    monkeypatch.setattr(bc, "PIVOT_FULL_BEARING", False)
    assert _planner_ask(monkeypatch, 6.0, 34.0).stop_deg <= bc.ALIGN_MAX_DEG
    import inspect
    assert "opencat.lineup_uses_pivot(" in inspect.getsource(bc.ChasePlanner.decide)                    # one rule for both
    assert "lineup_uses_pivot(ball_in)" in inspect.getsource(opencat.lineup_tokens)
