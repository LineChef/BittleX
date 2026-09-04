from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.voice.conversation import Conversation


def test_reply_splits_into_speech_actions_facts(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(
        Block("text", text="Hi Sam!"),
        Block("tool_use", name="remember", id="r1", input={"fact": "Their name is Sam."}),
        Block("tool_use", name="perform_skill", id="s1", input={"skill": "wave"}),
    ))
    turn = Conversation(cfg).send("hi, I'm Sam")
    assert turn.speech == "Hi Sam!"
    assert turn.actions == ["wave"]
    assert turn.facts == ["Their name is Sam."]


def test_tool_results_flushed_on_next_turn(cfg, fake_anthropic):
    conv = Conversation(cfg)
    fake_anthropic.set_reply(Resp(Block("tool_use", name="perform_skill", id="s1",
                                        input={"skill": "sit"})))
    conv.send("sit")
    fake_anthropic.set_reply(Resp(Block("text", text="ok")))
    conv.send("thanks")
    last_user_blocks = fake_anthropic.calls[-1]["messages"][-1]["content"]
    assert any(b.get("type") == "tool_result" and b["tool_use_id"] == "s1"
               for b in last_user_blocks)
    assert conv._pending_tool_results == []


def test_unknown_skill_dropped_but_acknowledged(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(Block("tool_use", name="perform_skill", id="x",
                                        input={"skill": "backflip"})))
    conv = Conversation(cfg)
    turn = conv.send("do a backflip")
    assert turn.actions == []
    assert conv._pending_tool_results[0]["content"].startswith("unknown")


def test_memory_context_is_prepended(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(Block("text", text="ok")))
    Conversation(cfg).send("hello", memory_context="What you know:\n- Their name is Sam.")
    blocks = fake_anthropic.calls[-1]["messages"][-1]["content"]
    joined = " ".join(b.get("text", "") for b in blocks)
    assert "Memory of past conversations" in joined and "Sam" in joined


def test_history_trims_to_window(cfg, fake_anthropic):
    conv = Conversation(cfg)  # cfg.history_turns == 2 -> keep ~4 messages
    fake_anthropic.set_reply(Resp(Block("text", text="ok")))
    for i in range(6):
        conv.send(f"msg {i}")
    assert len(conv._history) <= 4
    assert conv._history[0]["role"] == "user"


def test_retry_on_timeout_then_succeeds(cfg, fake_anthropic, monkeypatch):
    import anthropic

    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise anthropic.APITimeoutError(request=None)
        return Resp(Block("text", text="recovered"))

    monkeypatch.setattr(fake_anthropic, "_next", None)
    conv = Conversation(cfg)
    monkeypatch.setattr(conv._client.messages, "create", flaky)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    turn = conv.send("hi")
    assert turn.speech == "recovered" and calls["n"] == 2
