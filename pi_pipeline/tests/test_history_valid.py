"""The conversation history must always satisfy the API's tool rules, whatever the model returns:
every tool_use in an assistant message is answered by a tool_result in the very next user message, and every tool_result answers a
tool_use of the message just before it. Fuzzed over random reply shapes, failures and retries."""
import dataclasses
import random

import pytest

from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.voice.conversation import Conversation


def ids(content, kind):
    out = []
    for b in content if isinstance(content, list) else []:
        t = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
        if t == kind:
            out.append(b["tool_use_id"] if isinstance(b, dict) else b.id)
    return out


def check(messages, pending=()):
    """`pending`: tool_use ids whose acknowledgement is queued for the next message (a history may end on such an assistant message)."""
    for i, m in enumerate(messages):
        if m["role"] == "assistant":
            uses = ids(m["content"], "tool_use")
            nxt = messages[i + 1] if i + 1 < len(messages) else None
            if uses and nxt is None:
                assert set(uses) <= set(pending), f"messages.{i}: the last assistant message's tool_use {set(uses) - set(pending)} is not queued for ack"
                continue
            if uses:
                assert nxt["role"] == "user", f"messages.{i}: tool_use with no user message after"
                got = ids(nxt["content"], "tool_result")
                assert set(uses) <= set(got), f"messages.{i}: tool_use {set(uses) - set(got)} has no tool_result in the next message"
        else:
            results = ids(m["content"], "tool_result")
            if results:
                prev = messages[i - 1] if i else None
                assert prev is not None and prev["role"] == "assistant", f"messages.{i}: tool_result without an assistant message before"
                assert set(results) <= set(ids(prev["content"], "tool_use")), f"messages.{i}: tool_result for an unknown tool_use"
    # roles alternate (the API merges consecutive same-role messages, but ours should not produce them)
    for a, b in zip(messages, messages[1:]):
        assert a["role"] != b["role"], "two consecutive messages with the same role"


TOOLS = [("perform_skill", {"skill": "wave"}), ("perform_skill", {"skill": "sit"}), ("remember", {"fact": "They like jazz.", "importance": 4}),
         ("remember", {"fact": ""}), ("await_reply", {}), ("diagnostics_query", {"topic": "status"}),
         ("memory_used", {"notes": ["#1"]}), ("perform_skill", {"skill": "backflip"}), ("some_unknown_tool", {"x": 1})]
PROMPTS = ["hi", "what do you see", "tell me about my dog", "walk forward", "remember that I like tea", "do you remember what I like?", "sit"]


def random_reply(rnd, n):
    blocks = []
    if rnd.random() < 0.55:
        blocks.append(Block("text", text="Some words."))
    for k in range(rnd.choice([0, 0, 1, 1, 2, 3])):
        name, inp = rnd.choice(TOOLS)
        blocks.append(Block("tool_use", name=name, id=f"t{n}_{k}", input=dict(inp)))
    rnd.shuffle(blocks)
    return Resp(*blocks, stop_reason="tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn")


@pytest.mark.parametrize("seed", range(300))
def test_the_history_always_satisfies_the_tool_rules(cfg, fake_anthropic, seed, monkeypatch):
    rnd = random.Random(seed)
    counter = {"n": 0}

    def reply():
        counter["n"] += 1
        # sometimes the call itself fails (a network error, an overloaded API)
        if rnd.random() < 0.12:
            raise RuntimeError("simulated API failure")
        return random_reply(rnd, counter["n"])

    fake_anthropic.set_reply(reply)
    c = dataclasses.replace(cfg, history_turns=rnd.choice([2, 3, 12]), memory_use_log=rnd.choice(["match", "declare"]))
    conv = Conversation(c)
    for _ in range(25):
        image = b"\xff\xd8x\xff\xd9" if rnd.random() < 0.3 else None
        try:
            conv.send(rnd.choice(PROMPTS), image=image, image_note="[pic]" if image else None)
        except Exception:
            pass                                               # a failed turn: the history must still be valid for the next one
        check(conv._history, [b['tool_use_id'] for b in conv._pending_tool_results])
        for call in fake_anthropic.calls[-1:]:
            check(call["messages"])
    # every request that was ever sent was valid, not just the last
    for call in fake_anthropic.calls:
        check(call["messages"])


# ---- the three bugs the fuzz found, stated plainly

def test_an_unknown_tool_call_is_still_acknowledged(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(Block("text", text="hi"), Block("tool_use", name="some_new_tool", id="x1", input={})))
    conv = Conversation(cfg)
    conv.send("hello")
    assert [b["tool_use_id"] for b in conv._pending_tool_results] == ["x1"]


def test_an_empty_reply_is_stored_as_a_placeholder_never_as_an_empty_message(cfg, fake_anthropic):
    replies = iter([Resp(), Resp(), Resp(Block("text", text="fine"))])
    fake_anthropic.set_reply(lambda: next(replies))
    conv = Conversation(cfg)
    conv.send("hello")
    assert all(m["content"] for m in conv._history)


def test_trimming_never_leaves_a_tool_result_without_its_tool_use(cfg, fake_anthropic):
    c = dataclasses.replace(cfg, history_turns=2)
    replies = iter([Resp(Block("tool_use", name="perform_skill", id=f"s{i}", input={"skill": "wave"}), stop_reason="tool_use")
                    for i in range(8)])
    fake_anthropic.set_reply(lambda: next(replies))
    conv = Conversation(c)
    for i in range(6):
        conv.send(f"wave {i}")
        check(conv._history, [b["tool_use_id"] for b in conv._pending_tool_results])
    for call in fake_anthropic.calls:
        check(call["messages"])
