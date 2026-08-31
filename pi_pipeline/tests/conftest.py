"""Shared test fixtures. No network, no audio, no API key."""
from __future__ import annotations

import types

import pytest

from pi_pipeline.config import Settings


@pytest.fixture
def cfg(tmp_path):
    """A Settings pointed at a temp DB, with a fake API key so Conversation builds."""
    s = Settings()
    over = {
        "anthropic_api_key": "sk-test",
        "memory_db_path": str(tmp_path / "mem.db"),
        "memory_max_facts": 5,
        "memory_recall_exchanges": 2,
        "history_turns": 2,
        "claude_max_tokens": 100,
    }
    for k, v in over.items():
        object.__setattr__(s, k, v)
    return s


class Block:
    """Stand-in for an anthropic content block."""

    def __init__(self, type, **kw):
        self.type = type
        self.text = kw.get("text", "")
        self.name = kw.get("name", "")
        self.id = kw.get("id", "")
        self.input = kw.get("input", None)


class Resp:
    def __init__(self, *blocks, stop_reason="end_turn"):
        self.content = list(blocks)
        self.stop_reason = stop_reason


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Patch anthropic.Anthropic; `set_reply(Resp(...))` controls the next call.
    Returns a recorder with `.calls` (kwargs of each messages.create call)."""
    import anthropic

    rec = types.SimpleNamespace(calls=[], _next=Resp(Block("text", text="ok")))

    def _create(**kw):
        # snapshot messages: conv._history is mutated (assistant reply appended)
        # right after this returns, so a live reference would mislead assertions
        rec.calls.append({**kw, "messages": [dict(m) for m in kw["messages"]]})
        return rec._next() if callable(rec._next) else rec._next

    fake = types.SimpleNamespace(messages=types.SimpleNamespace(create=_create))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: fake)
    rec.set_reply = lambda r: setattr(rec, "_next", r)
    return rec
