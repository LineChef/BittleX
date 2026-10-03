import json

import pytest

from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.voice import llm
from pi_pipeline.voice.conversation import Conversation, ConversationError, _TOOLS


def _fast_cfg(cfg, mode="routed", **over):
    for k, v in {"llm_mode": mode, "fast_llm_base_url": "http://fast.test/v1", "fast_llm_model": "m", **over}.items():
        object.__setattr__(cfg, k, v)
    return cfg


def _reply(text=None, calls=()):
    msg = {"content": text}
    if calls:
        msg["tool_calls"] = [{"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                             for i, n, a in calls]
    return 200, {"choices": [{"message": msg, "finish_reason": "stop"}]}


def _with_fast(conv, replies):
    """Replace the fast backend's transport; `replies` is a list of (status, body) or exceptions. Returns the request log."""
    sent = []

    def post(url, headers, payload, timeout):
        sent.append(payload)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    conv._fast._post = post
    return sent


# ------------------------------------------------------------------ router
def test_casual_turn_stays_on_the_fast_backend():
    assert llm.needs_claude("hello there", None, sees_memory=False, max_words=25) is None


@pytest.mark.parametrize("text", ["remember that I like tea", "what do you see", "tell me about my cat",
                                  "explain how a tide works"])
def test_personal_vision_and_reasoning_turns_escalate(text):
    assert llm.needs_claude(text, None, sees_memory=False, max_words=25)


def test_long_requests_escalate():
    assert llm.needs_claude("word " * 30, None, sees_memory=False, max_words=25)


def test_memory_context_stays_off_the_fast_backend_unless_allowed():
    assert llm.needs_claude("hello", "- a fact", sees_memory=False, max_words=25)
    assert llm.needs_claude("hello", "- a fact", sees_memory=True, max_words=25) is None


# ------------------------------------------------------------ translation
def test_history_translates_to_chat_completions_shape():
    history = [
        {"role": "user", "content": [{"type": "text", "text": "sit"}]},
        {"role": "assistant", "content": [Block("text", text="ok"),
                                          Block("tool_use", id="s1", name="perform_skill", input={"skill": "sit"})]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "s1", "content": "done"},
                                     {"type": "text", "text": "thanks"}]},
    ]
    msgs = llm.to_openai_messages("SYS", history)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "user"]
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "perform_skill"
    assert json.loads(msgs[2]["tool_calls"][0]["function"]["arguments"]) == {"skill": "sit"}
    assert msgs[3] == {"role": "tool", "tool_call_id": "s1", "content": "done"}


def test_orphan_tool_result_is_dropped():
    history = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "gone", "content": "x"},
                                            {"type": "text", "text": "hi"}]}]
    assert [m["role"] for m in llm.to_openai_messages("S", history)] == ["system", "user"]


def test_tools_translate_to_function_format():
    t = llm.to_openai_tools(_TOOLS)
    assert {x["function"]["name"] for x in t} == {"perform_skill", "remember", "diagnostics_query"}
    assert t[0]["type"] == "function" and "properties" in t[0]["function"]["parameters"]


def test_response_parsing_handles_text_and_tool_calls_and_bad_json():
    _, data = _reply("hi", [("c1", "perform_skill", {"skill": "wave"})])
    r = llm.parse_openai_response(data)
    assert [b.type for b in r.content] == ["text", "tool_use"] and r.content[1].input == {"skill": "wave"}
    bad = {"choices": [{"message": {"tool_calls": [{"id": "x", "function": {"name": "remember", "arguments": "{oops"}}]}}]}
    assert llm.parse_openai_response(bad).content[0].input == {}


# ------------------------------------------------------------ Conversation
def test_default_mode_never_builds_the_fast_backend(cfg, fake_anthropic):
    assert Conversation(cfg)._fast is None


def test_misconfigured_fast_mode_fails_loudly(cfg, fake_anthropic):
    object.__setattr__(cfg, "llm_mode", "routed")
    object.__setattr__(cfg, "fast_llm_base_url", "")
    with pytest.raises(RuntimeError, match="G2_FAST_LLM_BASE_URL"):
        Conversation(cfg)
    object.__setattr__(cfg, "llm_mode", "bogus")
    with pytest.raises(RuntimeError, match="G2_LLM_MODE"):
        Conversation(cfg)


def test_routed_casual_turn_uses_fast_and_not_claude(cfg, fake_anthropic):
    conv = Conversation(_fast_cfg(cfg))
    sent = _with_fast(conv, [_reply("Hello!")])
    turn = conv.send("hello there")
    assert turn.speech == "Hello!" and len(sent) == 1 and fake_anthropic.calls == []


def test_routed_escalation_uses_claude_and_history_survives_a_mixed_conversation(cfg, fake_anthropic):
    conv = Conversation(_fast_cfg(cfg, history_turns=6))
    sent = _with_fast(conv, [_reply(None, [("c1", "perform_skill", {"skill": "sit"})]), _reply("sure")])
    first = conv.send("hello there")
    assert first.actions == ["sit"]
    fake_anthropic.set_reply(Resp(Block("text", text="Because of tides.")))
    assert conv.send("explain how tides work").speech == "Because of tides."
    # the Claude call got plain dicts only (the fast reply's LLMBlock was converted) and the pending tool ack
    msgs = fake_anthropic.calls[-1]["messages"]
    assert all(isinstance(b, dict) for m in msgs for b in m["content"])
    assert any(b.get("type") == "tool_result" for b in msgs[-1]["content"])
    assert conv.send("thanks").speech == "sure"
    assert len(sent) == 2


def test_routed_falls_back_to_claude_when_the_fast_backend_fails(cfg, fake_anthropic):
    conv = Conversation(_fast_cfg(cfg))
    _with_fast(conv, [llm.LLMError("transient", "timeout")])
    fake_anthropic.set_reply(Resp(Block("text", text="from claude")))
    assert conv.send("hello there").speech == "from claude"


def test_routed_empty_fast_reply_falls_back_to_claude(cfg, fake_anthropic):
    conv = Conversation(_fast_cfg(cfg))
    _with_fast(conv, [_reply("")])
    fake_anthropic.set_reply(Resp(Block("text", text="from claude")))
    assert conv.send("hello there").speech == "from claude"


def test_fast_only_mode_needs_no_anthropic_key(cfg):
    object.__setattr__(cfg, "anthropic_api_key", "")
    conv = Conversation(_fast_cfg(cfg, mode="fast"))
    assert conv._client is None
    _with_fast(conv, [_reply("hi")])
    assert conv.send("anything at all, explain my life").speech == "hi"


def test_fast_only_auth_failure_is_spoken(cfg):
    conv = Conversation(_fast_cfg(cfg, mode="fast", anthropic_api_key=""))
    _with_fast(conv, [(401, {"error": "bad key"})])
    with pytest.raises(ConversationError) as e:
        conv.send("hello")
    assert e.value.kind == "auth"


def test_claude_calls_carry_the_configured_effort(cfg, fake_anthropic):
    Conversation(cfg).send("hello")
    assert fake_anthropic.calls[-1]["output_config"] == {"effort": "low"}
    object.__setattr__(cfg, "claude_effort", "")
    Conversation(cfg).send("hello")
    assert "output_config" not in fake_anthropic.calls[-1]
