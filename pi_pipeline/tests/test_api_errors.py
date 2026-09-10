"""A failed Claude call for a known reason -> a plain spoken line, not "I glitched"."""
import types

import anthropic
import pytest

from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.voice.conversation import Conversation, ConversationError

_RESP = types.SimpleNamespace(status_code=0, headers={}, request=None)


def _raiser(exc):
    def _create(**_kw):
        raise exc
    return _create


def _err(cls, msg="boom"):
    return cls(msg, response=_RESP, body=None)


# ------------------------------------------------------------- conversation layer
def test_auth_error_becomes_a_spoken_conversation_error(cfg, fake_anthropic, monkeypatch):
    conv = Conversation(cfg)
    monkeypatch.setattr(conv._client.messages, "create",
                        _raiser(_err(anthropic.AuthenticationError)))
    with pytest.raises(ConversationError) as ei:
        conv.send("hi")
    assert ei.value.kind == "auth"
    assert ei.value.spoken == cfg.speech_api_auth
    assert "api key" in ei.value.spoken.lower()


def test_permission_denied_is_also_auth(cfg, fake_anthropic, monkeypatch):
    conv = Conversation(cfg)
    monkeypatch.setattr(conv._client.messages, "create",
                        _raiser(_err(anthropic.PermissionDeniedError)))
    with pytest.raises(ConversationError) as ei:
        conv.send("hi")
    assert ei.value.kind == "auth"


def test_billing_wording_in_a_400_becomes_billing_kind(cfg, fake_anthropic, monkeypatch):
    conv = Conversation(cfg)
    monkeypatch.setattr(conv._client.messages, "create",
                        _raiser(_err(anthropic.BadRequestError, "credit balance is too low")))
    with pytest.raises(ConversationError) as ei:
        conv.send("hi")
    assert ei.value.kind == "billing" and ei.value.spoken == cfg.speech_api_billing


def test_plain_400_still_raises_the_raw_error(cfg, fake_anthropic, monkeypatch):
    conv = Conversation(cfg)
    monkeypatch.setattr(conv._client.messages, "create",
                        _raiser(_err(anthropic.BadRequestError, "messages: too long")))
    with pytest.raises(anthropic.BadRequestError):
        conv.send("hi")


def test_rate_limit_retries_then_gives_a_spoken_error(cfg, fake_anthropic, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    conv = Conversation(cfg)
    calls = {"n": 0}

    def _create(**_kw):
        calls["n"] += 1
        raise _err(anthropic.RateLimitError, "slow down")

    monkeypatch.setattr(conv._client.messages, "create", _create)
    with pytest.raises(ConversationError) as ei:
        conv.send("hi")
    assert ei.value.kind == "rate" and ei.value.spoken == cfg.speech_api_rate
    assert calls["n"] == 3                       # retried, not given up on the first


def test_rate_limit_that_clears_still_succeeds(cfg, fake_anthropic, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    conv = Conversation(cfg)
    seq = [_err(anthropic.RateLimitError), Resp(Block("text", text="hello"))]

    def _create(**_kw):
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(conv._client.messages, "create", _create)
    assert conv.send("hi").speech == "hello"


def test_custom_phrase_via_env(cfg, monkeypatch, fake_anthropic):
    object.__setattr__(cfg, "speech_api_auth", "my noggin key stopped working")
    conv = Conversation(cfg)
    monkeypatch.setattr(conv._client.messages, "create",
                        _raiser(_err(anthropic.AuthenticationError)))
    with pytest.raises(ConversationError) as ei:
        conv.send("hi")
    assert ei.value.spoken == "my noggin key stopped working"


# ------------------------------------------------------------------- loop layer
def test_loop_speaks_the_known_reason_and_keeps_running(cfg, fake_anthropic, monkeypatch):
    from pi_pipeline.voice.loop import VoiceLoop

    said = []

    class _TTS:
        def speak(self, s): said.append(s)

    class _STT:
        _q = ["hello there", ""]
        def listen(self, timeout_s=None): return self._q.pop(0) if self._q else ""

    class _Stub:
        def __getattr__(self, _n): return lambda *a, **k: None

    conv = Conversation(cfg)
    monkeypatch.setattr(conv._client.messages, "create",
                        _raiser(_err(anthropic.AuthenticationError)))

    vl = VoiceLoop(wake_word=_Stub(), stt=_STT(), conversation=conv, tts=_TTS(),
                   actuator=_Stub(), cue=_Stub(), follow_up_s=0.0)
    vl._one_turn()                               # should not raise
    assert said == [cfg.speech_api_auth]
