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


def test_piper_tts_release_and_reload(monkeypatch, tmp_path):
    import sys
    import types

    from pi_pipeline.voice import tts as T
    loads = []

    class FakeVoice:
        config = types.SimpleNamespace(sample_rate=22050)

        @staticmethod
        def load(path):
            loads.append(path)
            return FakeVoice()

        def synthesize(self, text):
            return []
    mod = types.ModuleType("piper.voice")
    mod.PiperVoice = FakeVoice
    monkeypatch.setitem(sys.modules, "piper", types.ModuleType("piper"))
    monkeypatch.setitem(sys.modules, "piper.voice", mod)
    monkeypatch.setitem(sys.modules, "sounddevice", types.ModuleType("sounddevice"))
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    t = T.PiperTTS(str(model))
    assert t.loaded and len(loads) == 1
    assert T.release_speech(t) is True and not t.loaded
    assert T.release_speech(t) is False                                    # already released
    t._synth("hi")                                                          # a line that needs synthesis loads it again
    assert t.loaded and len(loads) == 2
    T.release_speech(t)
    T.warm_speech(t)
    for _ in range(100):
        if t.loaded:
            break
        import time
        time.sleep(0.02)
    assert t.loaded and len(loads) == 3
    assert T.release_speech(object()) is False                             # an engine that cannot release is left alone
