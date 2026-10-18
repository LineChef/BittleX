import sys
import types

from pi_pipeline.voice import vosk_model


def test_the_same_model_object_is_returned_for_the_same_path(monkeypatch):
    loads = []

    class _Model:
        def __init__(self, path):
            loads.append(path)

    monkeypatch.setitem(sys.modules, "vosk", types.SimpleNamespace(Model=_Model))
    monkeypatch.setattr(vosk_model, "_models", {})
    a = vosk_model.get_model("models/vosk")
    b = vosk_model.get_model("models/vosk")
    c = vosk_model.get_model("models/other")
    assert a is b and a is not c
    assert loads == ["models/vosk", "models/other"]        # loaded once per path


def test_a_failed_load_is_retried_once_then_raised(monkeypatch):
    """On the Pi a failed load showed only as "'Model' object has no attribute '_handle'"; it is now logged with the free memory and retried."""
    import pytest
    tries, slept = [], []

    class _Flaky:
        def __init__(self, path):
            tries.append(path)
            if len(tries) == 1:
                raise Exception("Failed to create a model")

    monkeypatch.setattr(vosk_model, "_models", {})
    assert vosk_model.get_model("m", _model_cls=_Flaky, _sleep=slept.append) is not None
    assert len(tries) == 2 and slept == [vosk_model.RETRY_WAIT_S]

    class _Broken:
        def __init__(self, path):
            raise Exception("Failed to create a model")

    monkeypatch.setattr(vosk_model, "_models", {})
    with pytest.raises(Exception, match="Failed"):
        vosk_model.get_model("m", _model_cls=_Broken, _sleep=lambda s: None)
    assert vosk_model._models == {}                          # a failed load is not cached


def test_free_memory_reads_proc_meminfo_or_none():
    v = vosk_model.mem_available_mb()
    assert v is None or v > 0
