"""The head's read-only recall tool: G2's saved facts and recent sightings, for the cloud model to speak.

What this returns leaves the house (it travels through XiaoZhi's cloud to the model), so it is OFF unless `G2_HEAD_RECALL=1`, it never returns conversation transcripts, and names
from G2_BONDS are replaced with "[name]" before anything is sent. Facts are read without marking them as recalled, so the head never changes which facts the voice loop injects.
"""
from __future__ import annotations

import os
import re

from .mcp_tools import MAX_RESULT_BYTES, Tool

MAX_TOPIC_CHARS = 80
_WORD = re.compile(r"[a-z0-9']{3,}")
_SCHEMA = {"type": "object", "properties": {"topic": {"type": "string", "description": "A few words about what to look for, such as 'cat' or 'who lives here'. Leave empty for the most important things."}},
           "additionalProperties": False}


def enabled() -> bool:
    return os.environ.get("G2_HEAD_RECALL", "").strip() == "1"


def _bond_names(spec: str) -> list[str]:
    return [e.split(":", 1)[0].strip() for e in (spec or "").split(";") if e.split(":", 1)[0].strip()]


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def recall_text(store, topic: str = "", *, names: list[str] | None = None, limit_bytes: int = MAX_RESULT_BYTES) -> str:
    """Core facts, then matching (or top-ranked) facts, then up to 3 sightings, as short lines that fit `limit_bytes`. Read-only."""
    from ..memory.store import scrub_text
    topic = (topic or "").strip()[:MAX_TOPIC_CHARS]
    want = _words(topic)
    facts = list(store.list_core()) + list(store.list_ranked(30))
    if want:
        hits = [f for f in facts if want & _words(f["fact"])]
        facts = hits
    lines = [f"- {f['fact']}" for f in facts]
    sights = (store.search_observations(topic, 3) if want else store.recent_observations(3))
    lines += [f"- saw: {s['caption']}" for s in sights]
    if not lines:
        return "G2 has nothing saved about that." if want else "G2 has nothing saved yet."
    out, used = [], 0
    for line in lines:
        line = scrub_text(line, names)
        size = len(line.encode("utf-8")) + 1
        if used + size > limit_bytes:
            break
        out.append(line)
        used += size
    return "\n".join(out)


def make_tool(store_factory=None, names: list[str] | None = None) -> Tool:
    def handler(args: dict) -> str:
        topic = args.get("topic", "")
        if not isinstance(topic, str):
            raise ValueError("topic must be text")
        if store_factory is None:
            from ..config import settings
            from ..memory.store import Store
            store, bonds = Store(settings.memory_db_path), (names if names is not None else _bond_names(settings.bonds_spec))
        else:
            store, bonds = store_factory(), names or []
        try:
            return recall_text(store, topic, names=bonds)
        finally:
            store.close()
    return Tool("g2_recall", "Look up what G2 has learned and remembered about the people and place around him. Call this first whenever someone asks what G2 knows or remembers, "
                "about a person, a pet, or something he saw.", handler, _SCHEMA)
