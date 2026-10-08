import types

from pi_pipeline.behavior.explore_listener import ExploreListener
from pi_pipeline.vision.describe_local import describe
from pi_pipeline.vision.feed import Detection


def D(label, cx, w=0.2, conf=0.9):
    return Detection(label, conf, cx - w / 2, 0.3, w, w)


def test_describe_lists_what_the_detector_sees():
    assert describe([]) == "I don't see anything I recognise right now."
    assert describe([D("dog", 0.2)]) == "I see a dog on my left."
    assert describe([D("dog", 0.5, w=0.5), D("cat", 0.85, w=0.1)]) == "I see a dog straight ahead close up and a cat on my right in the distance."
    assert describe([D("dog", 0.5, conf=0.2)]) == "I don't see anything I recognise right now."


class RT:
    def __init__(self):
        self.calls = []

    def halt(self): self.calls.append("halt")
    def release(self): self.calls.append("release")
    def post(self, **k): self.calls.append(k)


def _l(frame=()):
    said, rt, flags = [], RT(), []
    li = ExploreListener(None, None, said.append, rt, lambda: list(frame), on_arm=lambda: flags.append("arm"), on_stop=lambda: flags.append("stop"))
    return li, said, rt, flags


def test_commands_map_to_runtime_actions_and_never_to_claude():
    li, said, rt, flags = _l()
    li.handle("emergency stop"); li.handle("resume"); li.handle("go ahead and look around"); li.handle("that's enough"); li.handle("shut down")
    assert rt.calls == ["halt", "release", {"arm_explore": True}, {"disarm_explore": True}]
    assert flags == ["arm", "stop"] and said[-1] == "Ending the exploration test."
    assert li.handle("what is the capital of france") is None


def test_tell_me_what_you_see_describes_the_detections():
    li, said, *_ = _l([D("dog", 0.2)])
    assert li.handle("tell me what you see") == "I see a dog on my left."
    assert said == ["I see a dog on my left."]
    li2, said2, rt2, _ = _l()
    li2.handle("look around")                                   # that phrase is the roam command, not a description
    assert rt2.calls == [{"arm_explore": True}]


def test_wake_word_chimes_hushes_narration_for_the_window_and_logs_the_mic():
    events = []

    class Wake:
        n = 0
        def wait(self):
            Wake.n += 1
            if Wake.n > 1:
                li.stop()
                import time; time.sleep(5)

    class STT:
        last_info = {"mic_peak": 1234, "blocks": 3, "partials": []}
        def listen(self, timeout_s=None):
            events.append("listen")
            return ""

    said, rt = [], RT()
    li = ExploreListener(Wake(), STT(), said.append, rt, lambda: [], settle_s=0.0, chime=lambda: events.append("chime"),
                         quiet=lambda on: events.append(("quiet", on)))
    import threading, time
    li.start()
    time.sleep(0.5)
    li.stop()
    assert events[:4] == ["chime", ("quiet", True), "listen", ("quiet", False)]
    assert said == ["I didn't catch that."]
