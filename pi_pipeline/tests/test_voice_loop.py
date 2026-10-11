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


def test_loop_passes_seconds_to_the_actuator():
    lp, w, stt, conv, tts = _loop(["walk for eight seconds and then wave at me", ""])     # (a bare "walk for N seconds" is a local command since 2026-10-09)
    conv.send = lambda text, memory_context=None: types.SimpleNamespace(
        speech="", actions=["walk_forward", "wave"], facts=[], action_seconds=[8.0, None])
    calls = []
    lp._act = types.SimpleNamespace(
        perform=lambda skill, seconds=None: calls.append((skill, seconds)), stop=lambda: None)
    _run(lp, 2)
    assert calls == [("walk_forward", 8.0), ("wave", None)]


def test_wake_word_triggers_the_api_warm_up_once_per_session():
    lp, w, stt, conv, tts = _loop(["hello", "again", ""])
    warmed = []
    conv.warm_up = lambda: warmed.append(1)
    _run(lp, 3)
    assert len(warmed) == 1              # one wake word; the follow-up turns reuse the warm connection


def test_non_streamed_turn_moves_before_it_talks():
    order = []
    lp, w, stt, conv, tts = _loop(["sit down", ""])
    conv.send = lambda text, memory_context=None: types.SimpleNamespace(
        speech="Sitting.", actions=["sit"], facts=[], action_seconds=[None])
    lp._act = types.SimpleNamespace(perform=lambda s, seconds=None: order.append("move"), stop=lambda: None)
    orig = tts.speak
    tts.speak = lambda t: (order.append("talk"), orig(t))[1]
    _run(lp, 2)
    assert order[:2] == ["move", "talk"]


def test_streamed_turn_speaks_each_sentence_and_acts_immediately():
    order = []
    lp, w, stt, conv, tts = _loop(["go for a little walk around the room", ""])     # Claude decides (a bare "walk" is a local command)
    conv.supports_streaming = True

    def send(text, memory_context=None, on_action=None, on_speech=None):
        on_speech("Okay.")
        on_action("walk_forward", 5.0)
        on_speech("Off I go.")
        return types.SimpleNamespace(speech="Okay. Off I go.", actions=["walk_forward"], facts=[],
                                     action_seconds=[5.0], streamed=True)

    conv.send = send
    lp._act = types.SimpleNamespace(perform=lambda s, seconds=None: order.append(("move", s, seconds)), stop=lambda: None)
    orig = tts.speak
    tts.speak = lambda t: (order.append(("say", t)), orig(t))[1]
    _run(lp, 2)
    moves = [o for o in order if o[0] == "move"]
    says = [o[1] for o in order if o[0] == "say"]
    assert moves == [("move", "walk_forward", 5.0)] and says[:2] == ["Okay.", "Off I go."]


def test_streamed_action_without_speech_still_says_okay():
    lp, w, stt, conv, tts = _loop(["sit", ""])
    conv.supports_streaming = True

    def send(text, memory_context=None, on_action=None, on_speech=None):
        on_action("sit", None)
        return types.SimpleNamespace(speech="", actions=["sit"], facts=[], action_seconds=[None], streamed=True)

    conv.send = send
    lp._act = types.SimpleNamespace(perform=lambda s, seconds=None: None, stop=lambda: None)
    _run(lp, 2)
    assert "Okay." in tts.said


def test_speech_worker_synthesises_the_next_sentence_while_the_previous_plays():
    import threading
    import time

    from pi_pipeline.voice.loop import _SpeechWorker

    events, lock = [], threading.Lock()

    def log_(e):
        with lock:
            events.append((round(time.monotonic() - t0, 2), e))

    class _Tts:
        def prepare(self, text):
            log_(f"synth start {text}")
            time.sleep(0.2)
            log_(f"synth end {text}")
            return text

        def play(self, item):
            log_(f"play start {item}")
            time.sleep(0.3)
            log_(f"play end {item}")

    t0 = time.monotonic()
    w = _SpeechWorker(_Tts(), on_first=lambda: log_("first"))
    for t in ("one", "two", "three"):
        w.say(t)
    assert w.said
    w.finish()
    names = [e for _t, e in events]
    plays = [e for e in names if e.startswith("play start")]
    assert plays == ["play start one", "play start two", "play start three"]     # in order
    # sentence two was synthesised while sentence one was still playing
    assert names.index("synth end two") < names.index("play end one")
    assert names.count("first") == 1 and names[0].startswith("synth start one")


def test_speech_worker_falls_back_to_plain_speak_without_prepare_and_play():
    from pi_pipeline.voice.loop import _SpeechWorker

    said = []
    w = _SpeechWorker(types.SimpleNamespace(speak=said.append))
    w.say("a")
    w.say("b")
    w.finish()
    assert said == ["a", "b"]


def test_a_failing_speaker_does_not_crash_a_turn_that_falls_back_to_plain_speak():
    lp, w, stt, conv, tts = _loop(["hello", ""])
    def boom(*a, **k):
        raise RuntimeError("Device unavailable")
    conv.send = boom                     # unexpected failure -> "Sorry, I glitched" path
    tts.speak = boom                     # ...and the speaker is broken too
    lp._one_turn()                       # must not raise


def test_after_a_question_the_loop_listens_briefly_without_the_wake_word():
    lp, w, stt, conv, tts = _loop(["are you ok", "yes I am", ""])
    lp._follow_up_s, lp._question_window_s = 0.0, 8.0
    answers = iter([types.SimpleNamespace(speech="Want me to stand?", actions=[], facts=[], action_seconds=[], expects_reply=True),
                    types.SimpleNamespace(speech="Standing.", actions=[], facts=[], action_seconds=[], expects_reply=False)])
    conv.send = lambda text, memory_context=None: next(answers)
    waits = []
    lp._wake.wait = lambda: waits.append(1)
    timeouts = []
    orig = stt.listen
    stt.listen = lambda timeout_s=None: (timeouts.append(timeout_s), orig(timeout_s))[1]
    lp._one_turn()                       # wake word + the first question
    assert lp._in_session and lp._session_window == 8.0
    lp._one_turn()                       # the answer: no wake word, 8 s window
    assert len(waits) == 1 and timeouts == [None, 8.0]
    assert not lp._in_session            # the second reply asked nothing: back to needing the wake word


def test_no_question_means_the_wake_word_is_needed_again():
    lp, w, stt, conv, tts = _loop(["stand up", ""])
    lp._follow_up_s, lp._question_window_s = 0.0, 8.0
    conv.send = lambda text, memory_context=None: types.SimpleNamespace(
        speech="Standing.", actions=[], facts=[], action_seconds=[], expects_reply=False)
    lp._one_turn()
    assert not lp._in_session


# --- conversation mode ("let's talk") and side-chatter rules ---

def _talk_loop(script, **kw):
    lp, w, stt, conv, tts = _loop(script, follow_up_s=0.0)
    lp._question_window_s = 8.0
    lp._conv_window_s = kw.get("window", 20.0)
    lp._conv_max_s = kw.get("max_s", 600.0)
    lp._side_max_words = kw.get("side", 14)
    lp._conv_max_words = kw.get("conv_words", 30)
    conv.send = lambda text, memory_context=None: (conv.sent.append(text), types.SimpleNamespace(
        speech="Sure.", actions=[], facts=[], action_seconds=[], expects_reply=False))[1]
    waits = []
    lp._wake.wait = lambda: waits.append(1)
    return lp, waits, stt, conv, tts


def test_lets_talk_starts_conversation_mode_without_calling_claude():
    lp, waits, stt, conv, tts = _talk_loop(["gee two let's talk"])
    lp._one_turn()
    assert lp._conversing and lp._in_session and lp._session_window == 20.0
    assert conv.sent == [] and any("let's talk" in s.lower() for s in tts.said)


def test_conversation_mode_needs_no_wake_word_between_turns_and_ends_on_silence():
    lp, waits, stt, conv, tts = _talk_loop(["lets talk", "how was your day", "tell me more", ""])
    for _ in range(4):
        lp._one_turn()
    assert conv.sent == ["how was your day", "tell me more"]
    assert len(waits) == 1                      # one wake word for the whole conversation
    assert stt.timeouts == [None, 20.0, 20.0, 20.0]
    assert not lp._conversing and not lp._in_session


def test_thats_all_ends_conversation_mode():
    lp, waits, stt, conv, tts = _talk_loop(["lets talk", "hello there", "that's all thanks", "next"])
    for _ in range(4):
        lp._one_turn()
    assert conv.sent == ["hello there", "next"] and len(waits) == 2
    assert any("wake word" in s.lower() for s in tts.said)


def test_thats_all_outside_conversation_mode_is_just_a_sentence():
    lp, waits, stt, conv, tts = _talk_loop(["that's all I wanted to say"])
    lp._one_turn()
    assert conv.sent == ["that's all I wanted to say"]


def test_conversation_mode_time_limit():
    lp, waits, stt, conv, tts = _talk_loop(["lets talk", "hello", "again"])
    lp._one_turn()
    assert lp._conversing
    lp._conv_started -= 700.0                   # 700 s into a 600 s limit
    lp._one_turn()                              # answered, then the limit ends the mode
    assert conv.sent == ["hello"] and not lp._conversing
    lp._one_turn()
    assert len(waits) == 2                      # "again" needed a new wake word


def test_lets_talk_about_something_is_a_normal_request():
    from pi_pipeline.voice.commands import match_local_command
    assert match_local_command("lets talk about my day") is None
    assert match_local_command("let's talk") == "converse"
    assert match_local_command("lets talk now") == "converse"


def test_conversation_mode_off_when_window_is_zero():
    lp, waits, stt, conv, tts = _talk_loop(["lets talk"], window=0.0)
    lp._one_turn()
    assert not lp._conversing and any("isn't turned on" in s for s in tts.said)


def test_long_speech_without_the_wake_word_is_dropped_before_claude():
    chatter = "so then she said we should probably just go to the store later and get some of those things"
    lp, waits, stt, conv, tts = _talk_loop(["are you ok", chatter, "yes"])
    answers = iter([types.SimpleNamespace(speech="Want me to stand?", actions=[], facts=[], action_seconds=[], expects_reply=True)])
    conv.send = lambda text, memory_context=None: (conv.sent.append(text), next(answers))[1]
    lp._one_turn()                              # a question opens the window
    lp._one_turn()                              # long side chatter: dropped, window closes
    assert conv.sent == ["are you ok"] and not lp._in_session


def test_long_speech_after_the_wake_word_is_never_dropped():
    chatter = "so then she said we should probably just go to the store later and get some of those things"
    lp, waits, stt, conv, tts = _talk_loop([chatter])
    lp._one_turn()
    assert conv.sent == [chatter]


def test_conversation_mode_has_its_own_longer_word_limit_and_stays_open_after_chatter():
    medium = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
    huge = " ".join(["word"] * 40)
    lp, waits, stt, conv, tts = _talk_loop(["lets talk", medium, huge, "hello again"])
    for _ in range(4):
        lp._one_turn()
    assert conv.sent == [medium, "hello again"]  # 16 words pass in conversation mode, 40 are dropped, the mode stays on
    assert lp._conversing


def test_not_talking_to_you_is_ignored_and_ends_the_window_even_in_conversation_mode():
    lp, waits, stt, conv, tts = _talk_loop(["lets talk", "I'm not talking to you", "hi"])
    for _ in range(3):
        lp._one_turn()
    assert conv.sent == ["hi"] and len(waits) == 2    # the remark never reached Claude; "hi" needed a new wake word
    assert not lp._conversing


def test_stop_commands_work_in_a_window_whatever_their_length():
    lp, waits, stt, conv, tts = _talk_loop(["lets talk", "emergency stop"])
    seen = []
    lp._events = lambda **kw: seen.append(kw)
    lp._one_turn(); lp._one_turn()
    assert any(k.get("halt") for k in seen) and not lp._conversing


def test_what_did_you_do_and_what_have_you_learned_are_answered_locally_from_the_recap_and_the_notes(tmp_path, monkeypatch):
    from pi_pipeline.memory.store import Store
    from pi_pipeline.reflection.recap import ExperienceLog
    monkeypatch.setenv("G2_EXPERIENCES", str(tmp_path / "e.jsonl"))
    mem = _Mem()
    mem.store = Store(str(tmp_path / "m.db"))
    lp, w, stt, conv, tts = _loop(["what did you do", "what have you learned", "what have you learned", ""], memory=mem)
    _run(lp, 1)
    assert "nothing to tell" in tts.said[-1]
    ExperienceLog().append({"duration_s": 600, "events": {"wall.steer": 2}, "stops": 3})
    lp, w, stt, conv, tts = _loop(["what did you do", "what have you learned", ""], memory=mem)
    _run(lp, 2)
    assert tts.said[0].startswith("I explored for about 10 minutes.") and "turned away from a wall twice" in tts.said[0]
    assert tts.said[1] == "I haven't learned anything new from my explorations yet."
    mem.store.add_fact("I keep turning away from walls", importance=2, source="experience")
    lp, w, stt, conv, tts = _loop(["what have you learned", ""], memory=mem)
    _run(lp, 1)
    assert tts.said == ["I keep turning away from walls."] and conv.sent == []
