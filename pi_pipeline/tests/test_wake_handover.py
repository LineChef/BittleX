"""The wake-word stream stays open and the speech recogniser carries on from it, so a command said right after the wake word is not lost."""
import json
import queue
import types

from pi_pipeline.voice.stt import VoskSTT
from pi_pipeline.voice.wake_word import VoskWakeWord


class _Stream:
    def __init__(self, **k):
        self.cb, self.closed, self.started = k["callback"], False, False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


class _Rec:
    def __init__(self, *a):
        self.n = 0

    def AcceptWaveform(self, _d):
        self.n += 1
        return False

    def PartialResult(self):
        return json.dumps({"partial": "gee two" if self.n >= 2 else ""})

    def Result(self):
        return json.dumps({"text": ""})


def _wake():
    w = object.__new__(VoskWakeWord)
    holder = {}

    def factory(**k):
        holder["s"] = _Stream(**k)
        for _ in range(3):
            k["callback"](b"\x00" * 8, 4, None, None)      # three blocks are already waiting
        return holder["s"]

    w._sd = types.SimpleNamespace(RawInputStream=factory)
    w._rate, w._phrases, w._grammar, w._Recognizer, w._model, w._live = 16000, ["gee two"], "[]", _Rec, None, None
    return w, holder


def test_the_stream_stays_open_after_the_wake_word_and_is_handed_over():
    w, holder = _wake()
    w.wait()
    assert not holder["s"].closed
    q, close = w.hand_over()
    assert isinstance(q, queue.Queue) and q.qsize() >= 1        # the audio since the hit is waiting
    close()
    assert holder["s"].closed
    assert w.hand_over() is None


def test_an_untaken_stream_is_closed_before_the_next_wait():
    w, holder = _wake()
    w.wait()
    first = holder["s"]
    w.wait()
    assert first.closed


def test_stt_uses_the_handed_over_stream_instead_of_opening_the_microphone():
    closed = []
    q = queue.Queue()
    for _ in range(6):
        q.put(b"\x00" * 8)

    class Rec:
        def __init__(self, *a):
            self.i = -1

        def AcceptWaveform(self, _d):
            self.i += 1
            return self.i == 1

        def PartialResult(self):
            return json.dumps({"partial": "power down"})

        def Result(self):
            return json.dumps({"text": "power down"})

        def FinalResult(self):
            return json.dumps({"text": "power down"})

    stt = object.__new__(VoskSTT)
    stt._rate, stt._silence_blocks, stt._model, stt._Recognizer = 16000, 2, None, Rec
    stt._sd = types.SimpleNamespace(RawInputStream=lambda **k: (_ for _ in ()).throw(AssertionError("must not open the mic")))
    stt.audio_source = lambda: (q, lambda: closed.append(True))
    assert stt.listen(timeout_s=2) == "power down"
    assert closed == [True]
