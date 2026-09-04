# Memory — Phase 9

Persistent conversation memory so G2 carries context across sessions. Plugs into
the voice loop through one seam (`Memory.recall` / `Memory.record`); it is not
coupled to movement or vision.

## How it works

SQLite (`pi_pipeline/memory/data/g2_memory.db`, gitignored). Two kinds of memory:

| | What | How it's used |
|---|---|---|
| **Exchanges** | the full log, one row per turn, mirrored into an FTS5 index | relevance-searched at recall time for *older* turns related to what was just said |
| **Facts** | short durable notes G2 chose to keep ("Their name is Sam.") | the top `G2_MEMORY_MAX_FACTS` (by recency of creation/use) are injected every turn |

**Recall** (before each Claude call): `recall(user_text)` returns a context block
— the current fact set plus up to `G2_MEMORY_RECALL` older exchanges that match
the input (BM25-ranked, excluding the recent turns `conversation.py` still has
in-context). Empty string if nothing.

**Record** (after each turn): logs the exchange, and stores any facts from G2's
`remember` tool calls. The `remember` tool is defined in
`voice/conversation.py`; G2 decides what's worth keeping — no extra API call.

Surfacing a fact bumps its `last_recalled` time, so once the injected set hits
the cap, stale facts drop off it (they stay in the DB). Light decay without a
scheduler.

## Config (`.env`)

```
G2_MEMORY=1                                            # 0 to disable
G2_MEMORY_DB=pi_pipeline/memory/data/g2_memory.db
G2_MEMORY_MAX_FACTS=30
G2_MEMORY_RECALL=3
```

## Inspect / edit it

```bash
python -m pi_pipeline.memory facts                 # durable facts
python -m pi_pipeline.memory log 30                # recent exchanges
python -m pi_pipeline.memory search "cat"          # relevance search the log
python -m pi_pipeline.memory recall "my cat"       # exactly what recall() would inject
python -m pi_pipeline.memory remember "Their name is Sam."
python -m pi_pipeline.memory forget "Their name is Sam."   # by text or #id
python -m pi_pipeline.memory wipe --yes
```

Or open it directly: `sqlite3 pi_pipeline/memory/data/g2_memory.db`.

## Later

- Semantic recall (embeddings) if FTS keyword matching feels too literal —
  weigh the model/latency cost on the Pi first.
- A small web UI to browse/prune memory (per the plan).
