import types

from pi_pipeline.voice.loop import VoiceLoop


class _Wake:
    def __init__(self):
        self.calls = 0

    def wait(self):
        self.calls += 1


class _STT:
    def __init__(self, script):
        self._script = list(script)
        self.timeouts = []

    def listen(self, timeout_s=None):
        self.timeouts.append(timeout_s)
        return self._script.pop(0) if self._script else ""


class _Conv:
    def __init__(self):
        self.sent = []
        self.mood_hints = []
        self.narration_hints = []

    def send(self, text, memory_context=None):
        self.sent.append(text)
        return types.SimpleNamespace(speech="ok", actions=[], facts=[])

    def set_mood_hint(self, hint):
        self.mood_hints.append(hint)

    def set_narration_hint(self, hint):
        self.narration_hints.append(hint)


class _TTS:
    def __init__(self):
        self.said = []

    def speak(self, text):
        self.said.append(text)


class _Act:
    def perform(self, s):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class _Cue:
    def set(self, stage):
        pass


class _Mem:
    def __init__(self):
        self.marks = 0
        self.forgets = 0
        self.recorded = []

    def mark_session_start(self):
        self.marks += 1

    def forget_session(self):
        self.forgets += 1
        return (1, 0)

    def recall(self, text):
        return None

    def recency(self):
        return (None, 0)

    def record(self, user_text, turn):
        self.recorded.append(user_text)


def _loop(script, follow_up_s=8.0, memory=None, on_event=None):
    w, stt, conv, tts = _Wake(), _STT(script), _Conv(), _TTS()
    lp = VoiceLoop(
        wake_word=w, stt=stt, conversation=conv, tts=tts,
        actuator=_Act(), cue=_Cue(), memory=memory, follow_up_s=follow_up_s,
        on_event=on_event,
    )
    return lp, w, stt, conv, tts


def _run(lp, n):
    for _ in range(n):
        try:
            lp._one_turn()
        except KeyboardInterrupt:
            break


def test_follow_up_window_skips_wake_word():
    lp, w, stt, conv, tts = _loop(["hello", "and another thing", ""])
    _run(lp, 3)
    assert conv.sent == ["hello", "and another thing"]
    assert w.calls == 1  # only the first turn waited for the wake word
    # first listen has no onset timeout; the follow-ups do
    assert stt.timeouts == [None, 8.0, 8.0]


def test_silence_ends_session():
    lp, w, stt, conv, tts = _loop(["hello", "", "back again"])
    _run(lp, 3)
    assert conv.sent == ["hello", "back again"]
    assert w.calls == 2  # session ended on the blank -> wake needed again


def test_zero_follow_up_requires_wake_each_turn():
    lp, w, stt, conv, tts = _loop(["one", "two"], follow_up_s=0.0)
    _run(lp, 2)
    assert w.calls == 2
    assert stt.timeouts == [None, None]


def test_go_to_sleep_ends_session_without_calling_claude():
    lp, w, stt, conv, tts = _loop(["hello", "go to sleep", "hi again"])
    _run(lp, 3)
    assert conv.sent == ["hello", "hi again"]
    assert w.calls == 2  # sleep ended the session
    assert any("quiet" in s.lower() for s in tts.said)


def test_forget_that_calls_memory_and_not_claude():
    m = _Mem()
    lp, w, stt, conv, tts = _loop(["my secret", "forget that", ""], memory=m)
    _run(lp, 3)
    assert m.forgets == 1
    assert conv.sent == ["my secret"]  # "forget that" never reached Claude
    assert any("forgotten" in s.lower() for s in tts.said)


def test_forget_that_with_nothing_new_says_so():
    m = _Mem()
    m.forget_session = lambda: (0, 0)
    lp, w, stt, conv, tts = _loop(["forget that"], memory=m)
    _run(lp, 1)
    assert conv.sent == []
    assert any("nothing new" in s.lower() for s in tts.said)


def test_session_start_marked_once_per_wake():
    m = _Mem()
    lp, w, stt, conv, tts = _loop(["a", "b", ""], memory=m)
    _run(lp, 3)
    assert m.marks == 1
    assert m.recorded == ["a", "b"]


# ------------------------------------------------ Phase 10 event bridge
def test_on_event_bridge_posts_wake_end_and_sleep():
    events = []
    lp, w, stt, conv, tts = _loop(
        ["hello", "go to sleep", ""], on_event=lambda **kw: events.append(kw))
    _run(lp, 3)
    kinds = [next(iter(e)) for e in events]
    assert kinds[0] == "wake_word"                 # first turn waited for wake
    assert "told_sleep" in kinds                   # "go to sleep" bridged
    assert "conversation_ended" in kinds           # session end bridged


# --------------------------------------- G2 always acknowledges a command
def test_recognised_command_acks_before_acting():
    events = []
    lp, w, stt, conv, tts = _loop(
        ["go to sleep", ""], on_event=lambda **kw: events.append(kw))
    _run(lp, 2)
    kinds = [next(iter(e)) for e in events]
    # ack fires for the command, before the told_sleep action event
    assert kinds.index("ack") < kinds.index("told_sleep")


def test_conversational_turn_also_acks():
    events = []
    lp, w, stt, conv, tts = _loop(
        ["what do you see", ""], on_event=lambda **kw: events.append(kw))
    _run(lp, 2)
    assert any("ack" in e for e in events)
    assert conv.sent == ["what do you see"]           # still went to Claude


def test_actions_without_speech_still_get_a_spoken_ok():
    lp, w, stt, conv, tts = _loop(["sit down", ""])
    conv.send = lambda text, memory_context=None: __import__("types").SimpleNamespace(
        speech="", actions=["sit"], facts=[])
    _run(lp, 2)
    assert "Okay." in tts.said


# ------------------------------------------------------ chirps / narration
def test_chirps_on_off_post_events_not_claude():
    events = []
    lp, w, stt, conv, tts = _loop(
        ["turn off your chirps", "turn on your chirps", ""],
        on_event=lambda **kw: events.append(kw))
    _run(lp, 3)
    assert conv.sent == []                          # never reached Claude
    kinds = [next(iter(e)) for e in events]
    assert "chirps_off" in kinds and "chirps_on" in kinds


def test_narration_level_sets_hint_not_claude():
    # levels 1 and 5 (not 3, the default -- its hint is deliberately empty)
    lp, w, stt, conv, tts = _loop(["narration level 1", "narration level 5", ""])
    _run(lp, 3)
    assert conv.sent == []
    assert len(conv.narration_hints) == 2
    assert conv.narration_hints[0] != conv.narration_hints[1]
    assert all(conv.narration_hints)                 # both non-empty hints
    assert "level 1" in tts.said[0] and "level 5" in tts.said[1]
