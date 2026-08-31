"""SQLite persistence for G2's memory. Stdlib only.

Two tables:
- `exchanges` -- the full conversation log (one row per user/assistant turn),
  mirrored into an FTS5 index for relevance search.
- `facts`    -- short durable notes G2 chose to keep ("their name is Mark").
  `last_recalled` is bumped whenever a fact is surfaced, so the injected set
  favours recently-relevant facts once it hits the cap (a light decay).

Inspect it directly:  sqlite3 pi_pipeline/memory/data/g2_memory.db
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS exchanges (
    id             INTEGER PRIMARY KEY,
    ts             TEXT NOT NULL,
    user_text      TEXT NOT NULL,
    assistant_text TEXT NOT NULL DEFAULT '',
    actions        TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS exchanges_fts USING fts5(
    user_text, assistant_text,
    content='exchanges', content_rowid='id', tokenize='porter'
);
CREATE TRIGGER IF NOT EXISTS exchanges_ai AFTER INSERT ON exchanges BEGIN
    INSERT INTO exchanges_fts(rowid, user_text, assistant_text)
    VALUES (new.id, new.user_text, new.assistant_text);
END;
CREATE TRIGGER IF NOT EXISTS exchanges_ad AFTER DELETE ON exchanges BEGIN
    INSERT INTO exchanges_fts(exchanges_fts, rowid, user_text, assistant_text)
    VALUES ('delete', old.id, old.user_text, old.assistant_text);
END;
CREATE TABLE IF NOT EXISTS facts (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,
    last_recalled TEXT,
    fact          TEXT NOT NULL UNIQUE
);
"""

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "to",
    "of", "in", "on", "for", "with", "you", "i", "me", "my", "your", "it", "that",
    "this", "do", "does", "did", "can", "could", "would", "what", "how", "why",
}


def _now() -> str:
    # microsecond precision -- these timestamps order the fact set (recency decay)
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 OR-query of its content words."""
    words = [w for w in re.findall(r"[a-zA-Z0-9]{3,}", text.lower()) if w not in _STOPWORDS]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))  # dedupe, keep order


class Store:
    def __init__(self, db_path: str):
        p = Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(p))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- exchanges ---------------------------------------------------------

    def log_exchange(self, user_text: str, assistant_text: str, actions: list[str]) -> int:
        cur = self._db.execute(
            "INSERT INTO exchanges (ts, user_text, assistant_text, actions) VALUES (?, ?, ?, ?)",
            (_now(), user_text.strip(), assistant_text.strip(), ",".join(actions)),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def recent_exchanges(self, n: int) -> list[sqlite3.Row]:
        return list(self._db.execute(
            "SELECT * FROM exchanges ORDER BY id DESC LIMIT ?", (n,)
        ))

    def search_exchanges(self, text: str, limit: int, exclude_last: int = 0) -> list[sqlite3.Row]:
        q = _fts_query(text)
        if not q:
            return []
        max_id = self._db.execute("SELECT COALESCE(MAX(id), 0) FROM exchanges").fetchone()[0]
        cutoff = max_id - exclude_last
        rows = self._db.execute(
            """
            SELECT e.* FROM exchanges_fts f
            JOIN exchanges e ON e.id = f.rowid
            WHERE exchanges_fts MATCH ? AND e.id <= ?
            ORDER BY bm25(exchanges_fts) LIMIT ?
            """,
            (q, cutoff, limit),
        )
        return list(rows)

    def exchange_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0])

    # --- facts -----------------------------------------------------------

    def add_fact(self, fact: str) -> bool:
        fact = fact.strip()
        if not fact:
            return False
        cur = self._db.execute(
            "INSERT OR IGNORE INTO facts (ts, fact) VALUES (?, ?)", (_now(), fact)
        )
        self._db.commit()
        return cur.rowcount > 0

    def list_facts(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM facts ORDER BY COALESCE(last_recalled, ts) DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return list(self._db.execute(sql))

    def touch_facts(self, ids: list[int]) -> None:
        if not ids:
            return
        self._db.executemany(
            "UPDATE facts SET last_recalled = ? WHERE id = ?",
            [(_now(), i) for i in ids],
        )
        self._db.commit()

    def forget_fact(self, needle: str) -> int:
        cur = self._db.execute(
            "DELETE FROM facts WHERE fact = ? OR id = ?",
            (needle.strip(), needle if needle.isdigit() else -1),
        )
        self._db.commit()
        return cur.rowcount

    def wipe(self) -> None:
        self._db.executescript(
            "DELETE FROM exchanges; DELETE FROM facts; "
            "INSERT INTO exchanges_fts(exchanges_fts) VALUES ('rebuild');"
        )
        self._db.commit()
