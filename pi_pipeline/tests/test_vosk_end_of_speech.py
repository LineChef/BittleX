import json
import types

from pi_pipeline.voice.stt import VoskSTT


class _Rec:
    """Scripted recogniser: one partial per block; never endpoints on its own."""
    def __init__(self, partials, final="walk forward", endpoint_at=None):
        self._partials, self._i, self._final, self._endpoint_at = list(partials), -1, final, endpoint_at

    def AcceptWaveform(self, _data):
        self._i += 1
        return self._endpoint_at is not None and self._i == self._endpoint_at

    def PartialResult(self):
        return json.dumps({"partial": self._partials[min(self._i, len(self._partials) - 1)]})

    def Result(self):
        return json.dumps({"text": self._final})

    def FinalResult(self):
        return json.dumps({"text": self._final})


def _stt(partials, silence_blocks, **kw):
    rec = _Rec(partials, **kw)
    stt = object.__new__(VoskSTT)
    stt._rate = 16000
    stt._silence_blocks = silence_blocks
    stt._model = None
    stt._Recognizer = lambda model, rate: rec

    class _Stream:
        def __init__(self, **k):
            self._cb = k["callback"]

        def __enter__(self):
            for _ in range(len(partials) + 6):      # more audio than the script needs
                self._cb(b"\x00" * 8000, 4000, None, None)
            return self

        def __exit__(self, *a):
            return False

    stt._sd = types.SimpleNamespace(RawInputStream=_Stream)
    return stt, rec


def test_ends_when_the_partial_stops_changing():
    stt, rec = _stt(["", "walk", "walk forward", "walk forward", "walk forward", "walk forward"], silence_blocks=2)
    assert stt.listen(timeout_s=5) == "walk forward"
    assert rec._i == 4          # two unchanged blocks after the last change (block 2) -> block 4


def test_a_changing_partial_keeps_listening():
    partials = ["a", "a b", "a b c", "a b c d", "a b c d e", "a b c d e f"]
    stt, rec = _stt(partials, silence_blocks=2, final="a b c d e f")
    stt.listen(timeout_s=5)
    assert rec._i >= len(partials)       # never cut off while words were still arriving


def test_vosks_own_endpoint_still_wins_when_it_fires_first():
    stt, rec = _stt(["walk", "walk forward", "walk forward", "walk forward"], silence_blocks=4,
                    final="walk forward", endpoint_at=2)
    assert stt.listen(timeout_s=5) == "walk forward"
    assert rec._i == 2


def test_an_emptied_partial_after_speech_counts_as_quiet():
    stt, rec = _stt(["walk", "walk forward", "", "", ""], silence_blocks=2)
    assert stt.listen(timeout_s=5) == "walk forward"
    assert rec._i == 3
