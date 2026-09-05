"""`Memory` -- what the voice loop talks to.

- `recall(user_text)` -> a context string to prepend to the next Claude prompt:
  G2's durable facts plus any older conversation turns that look relevant to
  what was just said. Returns "" when there's nothing useful.
- `record(user_text, turn)` -> log the exchange and store any facts G2 chose to
  keep (its `remember` tool calls, carried on `turn.facts`).

The rolling window of *recent* turns is already handled by `conversation.py`;
Memory deliberately only surfaces the older material so the two don't overlap.
"""
from __future__ import annotations

import logging

from ..config import Settings
from .store import Store

log = logging.getLogger("g2.memory")


class Memory:
    def __init__(self, cfg: Settings):
        self._cfg = cfg
        self._store = Store(cfg.memory_db_path)
        self._max_facts = cfg.memory_max_facts
        self._recall_exchanges = cfg.memory_recall_exchanges
        # roughly how many recent turns conversation.py keeps in-context, so we
        # don't re-surface them here
        self._recent_window = cfg.history_turns
        # high-water marks captured at wake, so "forget that" can drop exactly
        # what this session recorded
        self._session_from_ex = 0
        self._session_from_fact = 0

    def close(self) -> None:
        self._store.close()

    def mark_session_start(self) -> None:
        """Call once when the wake word fires. Records where the log stands so a
        later `forget_session()` removes only what this session added."""
        self._session_from_ex = self._store.max_exchange_id()
        self._session_from_fact = self._store.max_fact_id()

    def forget_session(self) -> tuple[int, int]:
        """Delete every exchange and fact recorded since `mark_session_start()`.
        Returns (exchanges_deleted, facts_deleted)."""
        n_ex = self._store.delete_exchanges_after(self._session_from_ex)
        n_fa = self._store.delete_facts_after(self._session_from_fact)
        # a second "forget that" in the same session is then a no-op
        self._session_from_ex = self._store.max_exchange_id()
        self._session_from_fact = self._store.max_fact_id()
        if n_ex or n_fa:
            log.info("forgot session: %d exchange(s), %d fact(s)", n_ex, n_fa)
        return n_ex, n_fa

    def recall(self, user_text: str) -> str:
        parts: list[str] = []

        facts = self._store.list_facts(limit=self._max_facts)
        if facts:
            parts.append("What you know:\n" + "\n".join(f"- {f['fact']}" for f in facts))
            self._store.touch_facts([f["id"] for f in facts])

        older = self._store.search_exchanges(
            user_text, limit=self._recall_exchanges, exclude_last=self._recent_window
        )
        if older:
            lines = [
                f'- earlier they said "{r["user_text"]}"; you replied "{r["assistant_text"]}"'
                for r in older
            ]
            parts.append("Relevant past moments:\n" + "\n".join(lines))

        ctx = "\n\n".join(parts)
        if ctx:
            log.info("recall: %d facts, %d past moments", len(facts), len(older))
        return ctx

    def record(self, user_text: str, turn) -> None:
        self._store.log_exchange(user_text, turn.speech, list(turn.actions))
        for fact in getattr(turn, "facts", []):
            if self._store.add_fact(fact):
                log.info("remembered: %s", fact)

    # --- for the CLI ---
    @property
    def store(self) -> Store:
        return self._store
