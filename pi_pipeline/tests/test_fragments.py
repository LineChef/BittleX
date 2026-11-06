"""Scraps of speech after a false wake word, or in the follow-up window, never reach Claude or memory (user, 2026-11-06)."""
from pi_pipeline.tests.test_voice_loop import _loop, _run
from pi_pipeline.voice import fragments


def test_what_counts_as_a_scrap():
    for t in ("yeah", "ah", "the", "oh", "on", "do to", "the the", "um yeah", "and the"):
        assert fragments.is_fragment(t), t
    for t in ("hi", "ball chase", "tell me a joke", "stop", "sit down", "oh boy", "brian", "what time", ""):
        assert not fragments.is_fragment(t), t


def test_a_scrap_after_the_wake_word_is_dropped_without_a_reply_or_a_record():
    lp, w, stt, conv, tts = _loop(["yeah"])
    _run(lp, 1)
    assert conv.sent == [] and tts.said == []


def test_a_real_request_after_the_wake_word_still_goes_through():
    lp, w, stt, conv, tts = _loop(["hello robot"])
    _run(lp, 1)
    assert conv.sent == ["hello robot"]


def test_the_off_switch_keeps_the_old_behaviour(monkeypatch):
    monkeypatch.setenv("G2_DROP_FRAGMENTS", "0")
    lp, w, stt, conv, tts = _loop(["yeah"])
    _run(lp, 1)
    assert conv.sent == ["yeah"]


def test_a_single_word_in_the_follow_up_window_is_dropped_but_an_answer_to_a_question_is_not():
    lp, w, stt, conv, tts = _loop(["tell me a joke", "mm"])
    _run(lp, 2)
    assert conv.sent == ["tell me a joke"]                         # "mm" in the follow-up window: the room
    lp2, w2, stt2, conv2, tts2 = _loop(["tell me a joke", "yeah"])
    lp2._expects_reply = True
    lp2._set_session = lambda expects_reply=False, _o=lp2._set_session: _o(True)       # the reply asked something
    _run(lp2, 2)
    assert conv2.sent == ["tell me a joke", "yeah"]                # "yeah" answering a question is real
