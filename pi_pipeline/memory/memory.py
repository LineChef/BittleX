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
import re
import time
from datetime import datetime, timezone

from ..config import Settings
from .store import Store

log = logging.getLogger("g2.memory")

# Questions about what G2 saw earlier: only then are stored sightings brought into the prompt.
_PAST_SIGHT_RE = re.compile(
    r"\b(did you (see|notice|spot)|what did you see|you (saw|noticed|were looking at)|remember seeing|saw|earlier|before|last time|"
    r"yesterday|a while ago|the other day)\b", re.I)


def _when(ts: str) -> str:
    today = datetime.now(timezone.utc).date()
    try:
        d = datetime.fromisoformat(ts).date()
    except ValueError:
        return ts
    return "today" if d == today else "yesterday" if (today - d).days == 1 else ts


class Memory:
    def __init__(self, cfg: Settings, *, clock=time.monotonic):
        self._cfg = cfg
        self._store = Store(cfg.memory_db_path)
        self._max_facts = cfg.memory_max_facts
        self._core_max = getattr(cfg, "memory_core_max", 12)
        pruned = self._store.prune_observations(getattr(cfg, "observation_days", 30.0))
        if pruned:
            log.info("pruned %d old sighting(s)", pruned)
        self._recall_exchanges = cfg.memory_recall_exchanges
        # roughly how many recent turns conversation.py keeps in-context, so we
        # don't re-surface them here
        self._recent_window = cfg.history_turns
        # high-water marks captured at wake, so "forget that" can drop exactly
        # what this session recorded
        self._session_from_ex = 0
        self._session_from_fact = 0
        self._session_from_obs = 0
        # in-process interaction recency, for the mood model. Deliberately NOT
        # from the DB: `exchanges.ts` is a date only (no clock time) by privacy
        # design, so sub-day recency can't come from disk. Session-local,
        # nothing persisted.
        self._clock = clock
        self._last_exchange_at: float | None = None
        self._session_exchanges = 0

    def close(self) -> None:
        self._store.close()

    def mark_session_start(self) -> None:
        """Call once when the wake word fires. Records where the log stands so a
        later `forget_session()` removes only what this session added."""
        self._session_from_ex = self._store.max_exchange_id()
        self._session_from_fact = self._store.max_fact_id()
        self._session_from_obs = self._store.max_observation_id()
        self._session_exchanges = 0

    def recency(self) -> tuple[float | None, int]:
        """`(seconds_since_last_exchange | None, exchanges_this_session)` -- the
        two inputs the mood model wants. `None` age = nothing recorded yet."""
        age = (None if self._last_exchange_at is None
               else self._clock() - self._last_exchange_at)
        return age, self._session_exchanges

    def forget_session(self) -> tuple[int, int]:
        """Delete every exchange and fact recorded since `mark_session_start()`.
        Returns (exchanges_deleted, facts_deleted)."""
        n_ex = self._store.delete_exchanges_after(self._session_from_ex)
        n_fa = self._store.delete_facts_after(self._session_from_fact)
        self._store.delete_observations_after(self._session_from_obs)
        # a second "forget that" in the same session is then a no-op
        self._session_from_ex = self._store.max_exchange_id()
        self._session_from_fact = self._store.max_fact_id()
        self._session_from_obs = self._store.max_observation_id()
        if n_ex or n_fa:
            log.info("forgot session: %d exchange(s), %d fact(s)", n_ex, n_fa)
        return n_ex, n_fa

    def recall(self, user_text: str) -> str:
        parts: list[str] = []

        core = self._store.list_core(self._core_max)
        if core:
            parts.append("About you and your people (always true):\n" + "\n".join(f"- {f['fact']}" for f in core))
        facts = self._store.list_ranked(self._max_facts)          # importance + recency; the core facts are already above
        if facts:
            parts.append("What you know:\n" + "\n".join(f"- {f['fact']}" for f in facts))
        self._store.touch_facts([f["id"] for f in core] + [f["id"] for f in facts])

        seen: list = []
        if _PAST_SIGHT_RE.search(user_text or ""):
            seen = self._store.search_observations(user_text, limit=3) or self._store.recent_observations(3)
            if seen:
                lines = [f"- ({_when(r['ts'])}) {r['caption']}" + (f" [detector: {r['labels']}]" if r["labels"] else "") for r in seen]
                parts.append("Things you saw earlier:\n" + "\n".join(lines))

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
            log.info("recall: %d core, %d facts, %d sightings, %d past moments", len(core), len(facts), len(seen), len(older))
        return ctx

    def record(self, user_text: str, turn) -> None:
        self._store.log_exchange(user_text, turn.speech, list(turn.actions))
        self._last_exchange_at = self._clock()
        self._session_exchanges += 1
        details = getattr(turn, "fact_details", None) or [(f, 3, False) for f in getattr(turn, "facts", [])]
        for fact, importance, core in details:
            if self._store.add_fact(fact, importance=importance, core=core):
                log.info("remembered (importance %d%s): %s", importance, ", core" if core else "", fact)

    def record_observation(self, caption: str, labels: str = "") -> None:
        """Keep what G2 saw when he looked: his spoken description and the detector's labels. Text only, date only."""
        if self._store.add_observation(caption, labels):
            log.info("sighting noted")

    # --- for the CLI ---
    @property
    def store(self) -> Store:
        return self._store
