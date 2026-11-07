import pytest

ort = pytest.importorskip("onnxruntime")
from pi_pipeline.util import ort_memory


def test_apply_turns_the_arena_off_unless_asked(monkeypatch):
    monkeypatch.delenv("G2_ORT_ARENA", raising=False)
    so = ort_memory.apply(ort.SessionOptions())
    assert so.enable_cpu_mem_arena is False and so.enable_mem_pattern is False
    monkeypatch.setenv("G2_ORT_ARENA", "1")
    so2 = ort_memory.apply(ort.SessionOptions())
    assert so2.enable_cpu_mem_arena is True


def test_lean_sessions_patches_and_restores(monkeypatch):
    monkeypatch.delenv("G2_ORT_ARENA", raising=False)
    orig = ort.InferenceSession
    seen = []
    monkeypatch.setattr(ort, "InferenceSession", lambda path, sess_options=None, *a, **k: seen.append(sess_options) or "s")
    inner = ort.InferenceSession
    with ort_memory.lean_sessions():
        assert ort.InferenceSession("m.onnx") == "s"
    assert ort.InferenceSession is inner and seen[0].enable_cpu_mem_arena is False
    monkeypatch.setattr(ort, "InferenceSession", orig)
