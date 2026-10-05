"""SQLite persistence for G2's memory. Stdlib only.

Tables:
- `exchanges` -- the full conversation log (one row per user/assistant turn),
  mirrored into an FTS5 index for relevance search.
- `facts`    -- short durable notes G2 chose to keep ("their name is Sam").
  Facts encoding a date / clock time / schedule / timeline are rejected
  (`has_temporal_detail`) so the DB never becomes a record of what the household
  does when. `last_recalled` is bumped on surface, so the injected set favours
  recently-relevant facts once it hits the cap (a light decay).

- facts also carry an `importance` (1-5, rated when saved), a `core` flag (identity-level facts that are always injected and never
  rotate out: who lives here, the pets, how G2 looks) and a `source` ("told" = saved from conversation, "reflection" = an inferred
  note written by consolidation). Injected facts are ranked by importance plus recency, not recency alone.
- `observations` -- what G2 saw when he looked (his spoken description + the detector's labels), date only, searchable, pruned
  after `observation_days`. Text only: no pictures are kept.
- `meta` -- small bookkeeping (e.g. how far consolidation has read).

Inspect it directly:  sqlite3 pi_pipeline/memory/data/g2_memory.db
"""
from __future__ import annotations

import logging
import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("g2.memory.store")

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
CREATE TABLE IF NOT EXISTS observations (
    id      INTEGER PRIMARY KEY,
    ts      TEXT NOT NULL,
    caption TEXT NOT NULL,
    labels  TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
    caption, labels,
    content='observations', content_rowid='id', tokenize='porter'
);
CREATE TRIGGER IF NOT EXISTS observations_ai AFTER INSERT ON observations BEGIN
    INSERT INTO observations_fts(rowid, caption, labels) VALUES (new.id, new.caption, new.labels);
END;
CREATE TRIGGER IF NOT EXISTS observations_ad AFTER DELETE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, caption, labels) VALUES ('delete', old.id, old.caption, old.labels);
END;
CREATE TABLE IF NOT EXISTS fact_use (
    fact_id   INTEGER PRIMARY KEY,
    injected  INTEGER NOT NULL DEFAULT 0,
    declared  INTEGER NOT NULL DEFAULT 0,
    matched   INTEGER NOT NULL DEFAULT 0,
    last_used TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# columns added to `facts` after the first version of the schema (added in place to an existing database)
_FACT_COLUMNS = (
    ("importance", "INTEGER NOT NULL DEFAULT 3"),
    ("core", "INTEGER NOT NULL DEFAULT 0"),
    ("source", "TEXT NOT NULL DEFAULT 'told'"),
)
RECENCY_HALF_LIFE_DAYS = 14.0
RECENCY_BONUS = 2.0                  # a brand-new fact scores up to this much on top of its importance (1-5)


def fact_score(importance: int, stamp: str, now: datetime | None = None) -> float:
    """Importance plus a recency bonus that halves every two weeks (`stamp` is the fact's last-recalled or creation time)."""
    try:
        age_days = max(0.0, ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(stamp)).total_seconds() / 86400.0)
    except (TypeError, ValueError):
        age_days = 0.0
    return float(importance) + RECENCY_BONUS * 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "to",
    "of", "in", "on", "for", "with", "you", "i", "me", "my", "your", "it", "that",
    "this", "do", "does", "did", "can", "could", "would", "what", "how", "why",
}


def _now() -> str:
    # microsecond precision -- orders the fact set (recency decay). Row metadata
    # only; never the *content* of a fact (see _TEMPORAL_RE).
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _today() -> str:
    # date only -- the conversation log keeps *when roughly*, not a clock time,
    # so a leaked DB isn't a minute-by-minute timeline of the household.
    return datetime.now(timezone.utc).date().isoformat()


# A durable fact must not encode dates / clock times / schedules / a timeline of
# the household's comings and goings -- that turns the memory DB into a
# surveillance profile. Facts matching this are rejected (add_fact -> False).
_MONTHS = (r"jan(uary)?|feb(ruary)?|march|april|may|june|july|aug(ust)?|"
          r"sep(t|tember)?|oct(ober)?|nov(ember)?|dec(ember)?")
_TEMPORAL_RE = re.compile(
    rf"""
      \b\d{{1,2}}:\d{{2}}\b                            # 6:30, 18:05
    | \b\d{{1,2}}\s?[ap]\.?m\.?\b                      # 6pm, 6 a.m.
    | \bo['’]?clock\b | \bnoon\b | \bmidnight\b
    | \b(mon|tue|tues|wed|wednes|thu|thur|thurs|fri|sat|satur|sun)(day)?\b
    | \b\d{{1,2}}\s+(of\s+)?({_MONTHS})\b             # 3 June  /  3rd of June
    | \b({_MONTHS})\s+\d{{1,2}}\b                      # June 3
    | \b\d{{1,2}}/\d{{1,2}}(/\d{{2,4}})?\b            # 9/3, 09/03/2026
    | \b\d{{4}}-\d{{2}}-\d{{2}}\b                      # 2026-09-03
    | \b(yester|to)day\b | \btonight\b | \btomorrow\b
    | \bthis\s+(morning|afternoon|evening|week|month|weekend|year)\b
    | \b(last|next)\s+(week|month|year|night|
        mon|tues?|wednes?|thurs?|fri|satur?|sun)(day)?\b
    | \b\d+\s+(minute|hour|day|week|month|year)s?\s+ago\b
    | \b(every|each)\s+(day|morning|night|week|weekend|month|
        mon|tues?|wednes?|thurs?|fri|satur?|sun)(day)?\b
    | \b(daily|weekly|nightly|weekdays?|weekends?)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def has_temporal_detail(text: str) -> bool:
    return bool(_TEMPORAL_RE.search(text))


def scrub_text(text: str, extra_terms: list[str] | None = None) -> str:
    """Redact date/time/schedule spans and any `extra_terms` (whole word,
    case-insensitive) -- for safely sharing a memory dump. Not a security
    guarantee, a courtesy filter."""
    out = _TEMPORAL_RE.sub("[when]", text)
    for term in extra_terms or []:
        term = term.strip()
        if term:
            out = re.sub(rf"\b{re.escape(term)}\b", "[name]", out, flags=re.IGNORECASE)
    return out


# How G2 looks is a single slot: "I look like ..." facts replace each other. Other facts are only skipped when they are rewordings of one
# already stored (word overlap this high or more); "has a cat named Biscuit" vs "has a dog named Biscuit" (0.67) must stay two facts.
_SELF_LOOK = re.compile(r"^\s*i look like\b", re.I)
NEAR_DUPLICATE = 0.85
_STOPWORDS = frozenset("i a an the and of on with my me to is are in it its that this from up out like they their he she we you".split())


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of the content words of two facts (0..1)."""
    ta = {w for w in re.findall(r"[a-z0-9']+", a.lower()) if w not in _STOPWORDS}
    tb = {w for w in re.findall(r"[a-z0-9']+", b.lower()) if w not in _STOPWORDS}
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def _fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 OR-query of its content words."""
    words = [w for w in re.findall(r"[a-zA-Z0-9]{3,}", text.lower()) if w not in _STOPWORDS]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))  # dedupe, keep order


class Store:
    """Thin wrapper over the two-table sqlite schema above -- open/close plus
    one method per query the rest of the memory package needs."""
    def __init__(self, db_path: str):
        p = Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(p))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        have = {r["name"] for r in self._db.execute("PRAGMA table_info(facts)")}
        for name, ddl in _FACT_COLUMNS:
            if name not in have:
                self._db.execute(f"ALTER TABLE facts ADD COLUMN {name} {ddl}")
        # how G2 looks is identity-level: always injected, never rotated out (also fixes a database from before the `core` column)
        self._db.execute("UPDATE facts SET core = 1, importance = 5 WHERE fact LIKE 'I look like%' AND core = 0")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- exchanges ---------------------------------------------------------

    def log_exchange(self, user_text: str, assistant_text: str, actions: list[str]) -> int:
        cur = self._db.execute(
            "INSERT INTO exchanges (ts, user_text, assistant_text, actions) VALUES (?, ?, ?, ?)",
            (_today(), user_text.strip(), assistant_text.strip(), ",".join(actions)),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def recent_exchanges(self, n: int) -> list[sqlite3.Row]:
        return list(self._db.execute(
            "SELECT * FROM exchanges ORDER BY id DESC LIMIT ?", (n,)
        ))

    def max_exchange_id(self) -> int:
        return int(self._db.execute(
            "SELECT COALESCE(MAX(id), 0) FROM exchanges").fetchone()[0])

    def delete_exchanges_after(self, exchange_id: int) -> int:
        """Delete exchanges with id > `exchange_id` (the FTS mirror follows via
        the AFTER DELETE trigger). Used by the spoken "forget that" command."""
        cur = self._db.execute(
            "DELETE FROM exchanges WHERE id > ?", (exchange_id,))
        self._db.commit()
        return cur.rowcount

    def search_exchanges(self, text: str, limit: int, exclude_last: int = 0) -> list[sqlite3.Row]:
        # relevance search via FTS5, optionally excluding the N most recent
        # rows (so recall doesn't just echo back the current conversation)
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

    def add_fact(self, fact: str, importance: int = 3, core: bool = False, source: str = "told") -> bool:
        fact = fact.strip()
        importance = max(1, min(5, int(importance)))
        if not fact:
            return False
        if has_temporal_detail(fact):
            # keep stable facts about people / preferences, never a dated log of
            # what the household does when.
            log.info("fact rejected (date/time/schedule detail): %s", fact)
            return False
        existing = self.list_facts()
        if _SELF_LOOK.match(fact):
            importance, core = 5, True                      # identity-level
            # one slot for how G2 looks: the newest description replaces the older ones
            old = [r["id"] for r in existing if _SELF_LOOK.match(r["fact"]) and r["fact"] != fact]
            if old:
                self._db.executemany("DELETE FROM facts WHERE id = ?", [(i,) for i in old])
                log.info("replaced %d older self-description fact(s)", len(old))
        else:
            for r in existing:
                if similarity(fact, r["fact"]) >= NEAR_DUPLICATE:
                    log.info("fact skipped (near-duplicate of #%d): %s", r["id"], fact)
                    return False
        cur = self._db.execute(
            "INSERT OR IGNORE INTO facts (ts, fact, importance, core, source) VALUES (?, ?, ?, ?, ?)",
            (_now(), fact, importance, 1 if core else 0, source),
        )
        self._db.commit()
        return cur.rowcount > 0

    def max_fact_id(self) -> int:
        return int(self._db.execute(
            "SELECT COALESCE(MAX(id), 0) FROM facts").fetchone()[0])

    def delete_facts_after(self, fact_id: int) -> int:
        """Delete facts with id > `fact_id`. Used by "forget that"."""
        cur = self._db.execute("DELETE FROM facts WHERE id > ?", (fact_id,))
        self._db.commit()
        return cur.rowcount

    def list_facts(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM facts ORDER BY COALESCE(last_recalled, ts) DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return list(self._db.execute(sql))

    def list_core(self, limit: int | None = None) -> list[sqlite3.Row]:
        """The pinned facts: always injected, most important (then newest) first."""
        sql = "SELECT * FROM facts WHERE core = 1 ORDER BY importance DESC, id DESC"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return list(self._db.execute(sql))

    def list_ranked(self, limit: int, exclude_core: bool = True) -> list[sqlite3.Row]:
        """The facts to inject on a turn, best first: importance plus recency (see `fact_score`)."""
        now = datetime.now(timezone.utc)
        rows = list(self._db.execute("SELECT * FROM facts" + (" WHERE core = 0" if exclude_core else "")))
        rows.sort(key=lambda r: fact_score(r["importance"], r["last_recalled"] or r["ts"], now), reverse=True)
        return rows[:limit]

    def set_core(self, fact_id: int, core: bool) -> bool:
        cur = self._db.execute("UPDATE facts SET core = ? WHERE id = ?", (1 if core else 0, fact_id))
        self._db.commit()
        return cur.rowcount > 0

    def set_importance(self, fact_id: int, importance: int) -> bool:
        cur = self._db.execute("UPDATE facts SET importance = ? WHERE id = ?", (max(1, min(5, int(importance))), fact_id))
        self._db.commit()
        return cur.rowcount > 0

    def update_fact(self, fact_id: int, text: str, importance: int | None = None) -> bool:
        """Rewrite a fact's text (and optionally its importance), e.g. when consolidation merges duplicates. False if the text already
        exists on another fact."""
        try:
            if importance is None:
                cur = self._db.execute("UPDATE facts SET fact = ? WHERE id = ?", (text.strip(), fact_id))
            else:
                cur = self._db.execute("UPDATE facts SET fact = ?, importance = ? WHERE id = ?",
                                       (text.strip(), max(1, min(5, int(importance))), fact_id))
        except sqlite3.IntegrityError:
            return False
        self._db.commit()
        return cur.rowcount > 0

    def delete_fact(self, fact_id: int) -> bool:
        cur = self._db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self._db.commit()
        return cur.rowcount > 0

    def get_fact(self, fact_id: int) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()

    # --- observations (what G2 saw: text only, date only) ----------------------

    def add_observation(self, caption: str, labels: str = "") -> int:
        caption = scrub_text(caption.strip())
        if not caption:
            return 0
        cur = self._db.execute("INSERT INTO observations (ts, caption, labels) VALUES (?, ?, ?)", (_today(), caption, labels.strip()))
        self._db.commit()
        return int(cur.lastrowid)

    def recent_observations(self, n: int) -> list[sqlite3.Row]:
        return list(self._db.execute("SELECT * FROM observations ORDER BY id DESC LIMIT ?", (n,)))

    def search_observations(self, text: str, limit: int) -> list[sqlite3.Row]:
        q = _fts_query(text)
        if not q:
            return []
        return list(self._db.execute(
            """
            SELECT o.* FROM observations_fts f JOIN observations o ON o.id = f.rowid
            WHERE observations_fts MATCH ? ORDER BY bm25(observations_fts) LIMIT ?
            """, (q, limit)))

    def observations_after(self, observation_id: int, limit: int = 40) -> list[sqlite3.Row]:
        return list(self._db.execute("SELECT * FROM observations WHERE id > ? ORDER BY id LIMIT ?", (observation_id, limit)))

    def delete_observations_after(self, observation_id: int) -> int:
        """Used by the spoken "forget that": drop the sightings recorded since the wake word."""
        cur = self._db.execute("DELETE FROM observations WHERE id > ?", (observation_id,))
        self._db.commit()
        return cur.rowcount

    def prune_observations(self, days: float) -> int:
        """Delete observations older than `days` days (0 or less = keep forever). Returns how many."""
        if days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
        cur = self._db.execute("DELETE FROM observations WHERE ts < ?", (cutoff,))
        self._db.commit()
        return cur.rowcount

    def observation_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM observations").fetchone()[0])

    def max_observation_id(self) -> int:
        return int(self._db.execute("SELECT COALESCE(MAX(id), 0) FROM observations").fetchone()[0])

    # --- exchanges after a given id, and meta (for consolidation) ----------------

    def exchanges_after(self, exchange_id: int, limit: int = 40) -> list[sqlite3.Row]:
        return list(self._db.execute("SELECT * FROM exchanges WHERE id > ? ORDER BY id LIMIT ?", (exchange_id, limit)))

    # --- which memory shaped a reply (counters only; see memory/use_log.py) ----------------

    def record_fact_use(self, injected: list[int], declared: set[int], matched: set[int]) -> None:
        for i in injected:
            self._db.execute("INSERT INTO fact_use (fact_id, injected) VALUES (?, 1) "
                             "ON CONFLICT(fact_id) DO UPDATE SET injected = injected + 1", (i,))
        for i in declared | matched:
            self._db.execute("INSERT INTO fact_use (fact_id, declared, matched, last_used) VALUES (?, ?, ?, ?) "
                             "ON CONFLICT(fact_id) DO UPDATE SET declared = declared + ?, matched = matched + ?, last_used = ?",
                             (i, int(i in declared), int(i in matched), _today(), int(i in declared), int(i in matched), _today()))
        self._db.commit()

    def incr_meta(self, key: str, n: int = 1) -> None:
        self._db.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + ?",
                         (key, str(n), n))
        self._db.commit()

    def fact_use_rows(self) -> list[sqlite3.Row]:
        """Every fact with its use counters (zeros if it was never injected), most-used first."""
        return list(self._db.execute(
            """
            SELECT f.id, f.fact, f.core, f.importance, f.source,
                   COALESCE(u.injected, 0) AS injected, COALESCE(u.declared, 0) AS declared,
                   COALESCE(u.matched, 0) AS matched, u.last_used
            FROM facts f LEFT JOIN fact_use u ON u.fact_id = f.id
            ORDER BY COALESCE(u.declared, 0) + COALESCE(u.matched, 0) DESC, COALESCE(u.injected, 0) DESC, f.id
            """))

    def get_meta(self, key: str, default: str = "") -> str:
        r = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else default

    def set_meta(self, key: str, value: str) -> None:
        self._db.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
        self._db.commit()

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
            "DELETE FROM exchanges; DELETE FROM facts; DELETE FROM observations; DELETE FROM meta; DELETE FROM fact_use; "
            "INSERT INTO exchanges_fts(exchanges_fts) VALUES ('rebuild');"
        )
        self._db.commit()
