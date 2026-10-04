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
