"""tools/g2_cleanup.py: classification of scratch vs keep, and the Pi keep-pattern (no real git state or ssh needed)."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location("g2_cleanup", pathlib.Path(__file__).resolve().parents[2] / "tools" / "g2_cleanup.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

T = C.TRAINED


def test_scratch_patterns_match_generated_output():
    for p in (f"{T}/x_at5M_ppo.zip", f"{T}/v4_report_x_at5M", f"{T}/zz_probe.out", "docs/a.md.bak"):
        assert C.matches(p, C.SCRATCH), p


def test_protected_paths_never_match_as_deletable():
    for p in (f"{T}/v3_world2", f"{T}/checkpoints/v4_20m_200000_steps.zip", f"{T}/Release_CandidateV4_ppo.onnx", f"{T}/v4_c1_console.log"):
        assert C.matches(p, C.PROTECT), p


def test_ordinary_files_are_not_scratch():
    for p in ("tools/new_tool.py", f"{T}/v4_report.json", "docs/STATUS.md"):
        assert not C.matches(p, C.SCRATCH), p


def test_pi_keep_pattern_only_keeps_release_candidates():
    assert C.PI_KEEP.match("Release_CandidateV4_ppo.onnx")
    assert C.PI_KEEP.match("Release_CandidateV4_ppo.onnx.json")
    assert not C.PI_KEEP.match("run20m_ppo.zip")
    assert not C.PI_KEEP.match("checkpoints")


def test_classify_splits_delete_and_decide(monkeypatch):
    monkeypatch.setattr(C, "untracked", lambda: ["tools/new_tool.py", f"{T}/a_at5M_ppo.zip", f"{T}/v3_world2"])
    monkeypatch.setattr(C, "ignored_scratch", lambda: [])
    delete, decide = C.classify()
    assert delete == [f"{T}/a_at5M_ppo.zip"]
    assert decide == ["tools/new_tool.py"]
