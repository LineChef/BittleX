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
        import threading
        import time

        def feed():                                     # a live microphone: blocks keep arriving
            while not self.closed and not getattr(self, "stopped_feeding", False):
                self.cb(b"\x00" * 8, 4, None, None)
                time.sleep(0.002)
        threading.Thread(target=feed, daemon=True).start()

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

    def FinalResult(self):
        return json.dumps({"text": "gee two", "result": [{"word": "gee", "conf": 1.0}, {"word": "two", "conf": 1.0}]})


def _wake():
    w = object.__new__(VoskWakeWord)
    holder = {}

    def factory(**k):
        holder["s"] = _Stream(**k)
        return holder["s"]

    w._sd = types.SimpleNamespace(RawInputStream=factory)
    w._rate, w._phrases, w._grammar, w._Recognizer, w._model = 16000, ["gee two"], "[]", _Rec, None
    w._stream, w._q, w._handover = None, queue.Queue(maxsize=200), False
    return w, holder


def test_the_stream_stays_open_after_the_wake_word_and_is_handed_over():
    w, holder = _wake()
    w.wait()
    assert not holder["s"].closed
    q, close = w.hand_over()
    assert isinstance(q, queue.Queue)
    close()
    assert not holder["s"].closed                  # closing a PortAudio stream segfaulted the service: the stream is never closed
    q2, _ = w.hand_over()                           # a follow-up window with no new wake word: the SAME stream (the card cannot be opened twice)
    assert q2 is q and holder["s"] is w._stream


def test_one_stream_serves_every_wake_word_and_is_never_closed():
    w, holder = _wake()
    w.wait()
    first = holder["s"]
    w.hand_over()
    w.wait()
    assert holder["s"] is first and not first.closed


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


def test_a_stalled_microphone_stream_is_replaced_by_the_keeper():
    """B27: a stream that stays 'active' but stops delivering blocks is reopened by the supervised keeper."""
    import time
    from pi_pipeline.util.supervisor import Supervisor, WatchdogConfig
    w, holder = _wake()
    made = []
    orig = w._sd.RawInputStream

    def factory(**k):
        s = orig(**k)
        made.append(s)
        return s
    w._sd = types.SimpleNamespace(RawInputStream=factory)
    w._ensure_stream()
    first = made[0]
    cfg = WatchdogConfig(heartbeat_timeout_s=0.4, startup_grace_s=0.4, backoff_base_s=0.05)
    w._keeper = Supervisor("microphone-test", w._keep, cfg=cfg, emit=lambda *a, **k: None, poll_interval_s=0.05)
    w._keeper.start()
    try:
        time.sleep(0.3)
        assert len(made) == 1                      # blocks keep arriving: no restart
        first.stopped_feeding = True               # the stream stalls
        deadline = time.time() + 5
        while len(made) < 2 and time.time() < deadline:
            time.sleep(0.05)
        assert len(made) == 2 and w._stream is made[1] and not first.closed
    finally:
        for s in made:
            s.stopped_feeding = True
        w._keeper.stop()
