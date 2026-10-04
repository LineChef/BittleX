import types

import anthropic
import httpx2 as httpx
import pytest

from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.voice.conversation import Conversation, SentenceSplitter


def test_splitter_emits_whole_sentences_and_flushes_the_tail():
    sp = SentenceSplitter()
    out = []
    for chunk in ("Hello the", "re! How ", "are you? I'm", " fine."):
        out += sp.feed(chunk)
    assert out == ["Hello there!", "How are you?"]
    assert sp.flush() == "I'm fine."


def test_splitter_keeps_decimals_and_unfinished_text_together():
    sp = SentenceSplitter()
    assert sp.feed("It is 3.5 metres") == []
    assert sp.flush() == "It is 3.5 metres"


class _Stream:
    def __init__(self, events, final, boom_after=None):
        self._events, self._final, self._boom_after = events, final, boom_after

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for i, ev in enumerate(self._events):
            if self._boom_after is not None and i == self._boom_after:
                raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
            yield ev

    def get_final_message(self):
        return self._final


def _ev(kind, **kw):
    return types.SimpleNamespace(type=kind, **kw)


def _tool_stop(skill, seconds=None):
    inp = {"skill": skill} if seconds is None else {"skill": skill, "seconds": seconds}
    return _ev("content_block_stop", content_block=types.SimpleNamespace(type="tool_use", name="perform_skill", input=inp))


def _install(fake_anthropic, stream_factory):
    import anthropic as a
    fake = a.Anthropic()    # the patched fake from the fixture
    fake.messages.stream = stream_factory
    return fake


def test_streamed_reply_delivers_sentences_and_moves_as_they_complete(cfg, fake_anthropic):
    final = Resp(Block("text", text="On it! Walking now."),
                 Block("tool_use", name="perform_skill", id="t1", input={"skill": "walk_forward", "seconds": 5}))
    events = [_ev("text", text="On it! "), _ev("text", text="Walking now."),
              _ev("content_block_stop", content_block=types.SimpleNamespace(type="text")), _tool_stop("walk_forward", 5)]
    _install(fake_anthropic, lambda **kw: _Stream(events, final))
    seen = []
    turn = Conversation(cfg).send(
        "walk", on_action=lambda s, sec: seen.append(("act", s, sec)), on_speech=lambda t: seen.append(("say", t)))
    assert seen == [("say", "On it!"), ("say", "Walking now."), ("act", "walk_forward", 5.0)]
    assert turn.streamed and turn.actions == ["walk_forward"] and turn.action_seconds == [5.0]


def test_a_failure_before_anything_was_delivered_is_retried(cfg, fake_anthropic, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    final = Resp(Block("text", text="Hi."))
    calls = []

    def factory(**kw):
        calls.append(1)
        return _Stream([_ev("text", text="Hi.")], final, boom_after=0 if len(calls) == 1 else None)

    _install(fake_anthropic, factory)
    said = []
    turn = Conversation(cfg).send("hello", on_action=lambda *a: None, on_speech=said.append)
    assert len(calls) == 2 and said == ["Hi."] and turn.streamed


def test_a_failure_after_delivery_is_not_retried(cfg, fake_anthropic, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    final = Resp(Block("text", text="One. Two."))
    calls = []

    def factory(**kw):
        calls.append(1)
        return _Stream([_ev("text", text="One. "), _ev("text", text="Two.")], final, boom_after=1)

    _install(fake_anthropic, factory)
    said = []
    with pytest.raises(anthropic.APIConnectionError):
        Conversation(cfg).send("hello", on_action=lambda *a: None, on_speech=said.append)
    assert len(calls) == 1 and said == ["One."]     # already spoken, so the failure is raised, not retried


def test_without_callbacks_the_plain_path_is_used(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(Block("text", text="plain")))
    turn = Conversation(cfg).send("hi")
    assert turn.streamed is False and turn.speech == "plain"
