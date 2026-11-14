"""Every mode behaves the same (owner, 2026-11-13: "any change we make to G2 in any mode should apply to all modes"). The body limits are defined once (pi_pipeline/body.py), the claw look is one move, the guards are
built the same way, and tools/check_modes.py (also run by the pre-commit hook) finds a mode that builds its own."""
import importlib.util
import inspect
import re
from pathlib import Path

from pi_pipeline import body

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_modes", ROOT / "tools" / "check_modes.py")
CM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CM)


def test_no_mode_builds_its_own_look_guard_or_fall_threshold_and_no_new_gap_appears():
    blocking, new, known = CM.check()
    assert not blocking, "\n".join(f"{v['rule']} {v['file']}:{v['line']} {v['why']}" for v in blocking)
    assert not new, "a NEW mode-specific gap (call the standard move, or ask the owner for an exception): " + "; ".join(f"{v['rule']} {v['file']}:{v['line']}" for v in new)
    assert {v["rule"] for v in known} <= {"R4", "R5"}                                             # the known gaps are only these two kinds, and the list only shrinks


def test_every_fall_threshold_is_the_bodys():
    from pi_pipeline.behavior import ball_chase
    from pi_pipeline.gait import stand_guard
    assert body.FALL_DEG == 60.0 and body.FALL_HOLD_S == 0.3 and body.SILENT_END_S == 20.0                       # the owner's numbers (2026-11-13)
    assert inspect.signature(stand_guard.StandGuard.__init__).parameters["fall_deg"].default == body.FALL_DEG
    assert inspect.signature(stand_guard.StandGuard.__init__).parameters["silent_end_s"].default == body.SILENT_END_S
    assert inspect.signature(ball_chase.SerialRobot.__init__).parameters["fall_deg"].default == body.FALL_DEG
    run_gait = (ROOT / "pi_pipeline" / "gait" / "run_gait.py").read_text()
    walk_common = (ROOT / "pi_pipeline" / "gait" / "walk_common.py").read_text()
    assert float(re.search(r"fall_abort_deg=([0-9.]+)", run_gait).group(1)) == body.FALL_DEG                  # the walk loop's own guard (run as a script, so it cannot import body.py)
    assert float(re.search(r"^FALL_ABORT_S = ([0-9.]+)", walk_common, re.M).group(1)) == body.FALL_HOLD_S


def test_the_claw_look_is_the_chases_and_every_caller_goes_through_run_claw_look():
    from pi_pipeline.behavior import ball_chase, claw_survey
    assert claw_survey.run_claw_look.__module__.endswith("claw_survey") and "claw_look_sequence" in inspect.getsource(claw_survey.run_claw_look)
    assert "claw_look_sequence(" in inspect.getsource(ball_chase.claw_scan)                                      # the chase's own look is the same function
    callers = [p for p in (ROOT / "pi_pipeline").rglob("*.py") if "tests" not in p.parts and ".venv" not in p.parts and "claw_look_sequence(" in p.read_text() and p.name not in ("ball_chase.py", "claw_survey.py")]
    assert callers == []                                                                                         # nothing else builds a look
