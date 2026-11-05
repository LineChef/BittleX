"""What keeps each Claude request small and cheap (user, 2026-11-04): the prompt cache on the part that never changes, memory notes sent with one request only and trimmed to a
budget, and a daily spending ceiling."""
import dataclasses
import json
import time

import pytest

from pi_pipeline.memory.memory import Memory
from pi_pipeline.tests._system_text import system_text
from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.voice import api_budget
from pi_pipeline.voice.conversation import Conversation, ConversationError


# ---- the prompt cache

def test_the_static_prompt_is_cached_and_the_changing_hints_come_after_it(cfg, fake_anthropic):
    conv = Conversation(cfg)
    conv.send("hello")
    first = fake_anthropic.calls[-1]["system"]
    assert isinstance(first, list) and len(first) == 1
    assert first[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}           # the tool list before it is cached with it
    conv.set_narration_hint("Explain what you are doing.")
    conv.send("hello again")
    second = fake_anthropic.calls[-1]["system"]
    assert len(second) == 2 and second[0] == first[0]                                 # the cached block is byte-for-byte the same, so the cache still hits
    assert "cache_control" not in second[1] and "Explain what you are doing." in second[1]["text"]
    assert "Explain what you are doing." in system_text(second)


def test_the_cache_lifetime_and_the_off_switch(cfg, fake_anthropic):
    Conversation(dataclasses.replace(cfg, prompt_cache="5m")).send("hi")
    assert fake_anthropic.calls[-1]["system"][0]["cache_control"] == {"type": "ephemeral"}
    Conversation(dataclasses.replace(cfg, prompt_cache="off")).send("hi")
    assert isinstance(fake_anthropic.calls[-1]["system"], str)                        # the plain string, as before


# ---- memory notes belong to one request

def test_the_memory_notes_are_sent_with_one_request_only(cfg, fake_anthropic):
    conv = Conversation(cfg)
    conv.send("one", memory_context="NOTES-ONE")
    conv.send("two", memory_context="NOTES-TWO")
    msgs = fake_anthropic.calls[-1]["messages"]
    assert "NOTES-ONE" not in json.dumps(msgs, default=str)                           # the first turn's notes are not resent
    assert "NOTES-TWO" in json.dumps(msgs[-1], default=str)                           # this turn's are
    assert "Memory of past conversations" not in json.dumps(conv._history, default=str)


def test_a_turn_with_notes_keeps_no_thinking_block_and_a_turn_without_keeps_it(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(Block("thinking", thinking="plan", signature="s"), Block("text", text="ok")))
    conv = Conversation(cfg)
    conv.send("with notes", memory_context="NOTES")
    assert all(getattr(b, "type", None) != "thinking" for b in conv._history[-1]["content"])      # the notes are taken out: the block no longer matches
    conv2 = Conversation(cfg)
    conv2.send("no notes")
    assert any(getattr(b, "type", None) == "thinking" for b in conv2._history[-1]["content"])


# ---- the budget for one request's notes

def _memory(cfg, tmp_path, **over):
    m = Memory(dataclasses.replace(cfg, memory_db_path=str(tmp_path / "m.db"), memory_max_facts=30, **over))
    for t in ("The kitchen has a steel fridge and a black stove.", "Alice enjoys strong black coffee every morning.", "A small brown dog named Biscuit lives upstairs.",
              "The piano stands against the lounge wall.", "Maple trees line the street outside the front window.", "Granddad built the wooden bookcase himself.",
              "The garage door sticks when the weather is damp.", "Violet curtains hang in the back bedroom."):
        m.store.add_fact(t, importance=3)
    m.store.add_fact("Their family has two children and a dog.", importance=5, core=True)
    return m


def test_the_notes_of_one_request_are_trimmed_to_the_budget_and_the_core_facts_stay(cfg, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    full = _memory(cfg, tmp_path / "a", recall_max_chars=0).recall("hello")
    assert "steel fridge" in full and len(full) > 400
    small = _memory(cfg, tmp_path / "b", recall_max_chars=300).recall("hello")
    assert len(small) <= 300 or "What you know" not in small                           # trimmed until it fits (or nothing but the core facts is left)
    assert "two children and a dog" in small                                          # the always-true core fact is never dropped
    assert len(small) < len(full)


# ---- the daily ceiling

def _log_spend(tmp_path, input_tokens):
    line = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": "done", "source": "voice", "api": "messages.create", "input_tokens": input_tokens, "output_tokens": 0}
    (tmp_path / "api_calls.jsonl").write_text(json.dumps(line) + "\n")                 # the autouse fixture points G2_API_LOG here
    api_budget.reset_cache()


def test_the_daily_ceiling_warns_then_stops_claude_calls_and_zero_means_no_ceiling(cfg, fake_anthropic, tmp_path, monkeypatch):
    monkeypatch.setenv("G2_API_DAILY_USD", "1.0")
    _log_spend(tmp_path, 400_000)                                                      # $0.80 at $2 per million
    assert api_budget.state()[0] == "warn"
    Conversation(cfg).send("still allowed")
    assert len(fake_anthropic.calls) == 1
    _log_spend(tmp_path, 600_000)                                                      # $1.20
    assert api_budget.state()[0] == "over"
    with pytest.raises(ConversationError) as e:
        Conversation(cfg).send("one too many")
    assert e.value.kind == "limit" and "thinking budget" in e.value.spoken
    assert len(fake_anthropic.calls) == 1                                              # no second call was made
    monkeypatch.setenv("G2_API_DAILY_USD", "0")
    api_budget.reset_cache()
    assert api_budget.state()[0] == "ok"
    Conversation(cfg).send("no ceiling now")
    assert len(fake_anthropic.calls) == 2
    assert "ceiling" in api_budget.status_line()
