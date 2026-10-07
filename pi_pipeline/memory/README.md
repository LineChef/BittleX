# Memory — Phase 9

Persistent conversation memory so G2 carries context across sessions. Plugs into
the voice loop through one seam (`Memory.recall` / `Memory.record`); it is not
coupled to movement or vision.

## How it works

SQLite (`pi_pipeline/memory/data/g2_memory.db`, gitignored). Two kinds of memory:

| | What | How it's used |
|---|---|---|
| **Exchanges** | the conversation transcript, one row per turn, mirrored into an FTS5 index. Since 2026-10-07 turns that were only a short command ("rest", "walk forward") and exact repeats within 10 minutes are not logged (`G2_MEMORY_LOG_COMMANDS=1` brings them back); `python -m pi_pipeline.memory.review trash-commands [--apply]` moves the old ones to a trash you can restore from | relevance-searched at recall time for *older* turns related to what was just said |
| **Facts** | short durable notes G2 chose to keep ("Their name is Sam.") | the top `G2_MEMORY_MAX_FACTS` (by recency of creation/use) are injected every turn |

### Importance, core facts, sightings, consolidation (2026-10-05)

Design notes: [`docs/research/robot-memory-patterns.md`](../../docs/research/robot-memory-patterns.md).

* **Importance.** The `remember` tool takes an `importance` (1-5; 5 = names, who lives here, pets, how G2 looks). Injected facts are
  ranked by importance plus a recency bonus that halves every two weeks, so a name outranks a passing remark when the 30-slot cap bites.
* **Core facts** (`core` flag, set by Claude for identity-level facts or by you with `python -m pi_pipeline.memory pin <id>`): always
  injected in their own block ("About you and your people"), up to `G2_MEMORY_CORE_MAX` (12), never rotated out. "I look like ..." is
  always core, importance 5, and is a single slot (the newest replaces the older).
* **Sightings.** When G2 looks, his spoken description and the detector's labels are kept as a sighting (text only, date only, no
  picture), searchable, pruned after `G2_OBSERVATION_DAYS` (30). They join the prompt only when you ask about the past ("what did you see
  earlier", "did you notice...", "last time"). `python -m pi_pipeline.memory sightings`. "Forget that" removes the session's sightings too.
* **Consolidation.** When G2 has been idle `G2_CONSOLIDATE_IDLE_S` (20 min) or you tell him to go to sleep, and at least
  `G2_CONSOLIDATE_MIN_EXCHANGES` (6) new exchanges have happened, one Claude call merges duplicate facts, drops clearly trivial ones
  (importance 1-2), and may write up to 3 reflections ("It seems ...", stored with source `reflection`, no dates or routines). At most
  one pass per `G2_CONSOLIDATE_MIN_INTERVAL_S` (6 h) per run of the service. Core facts are never dropped, at most 5 facts are removed per
  pass, and every change is logged (old text included) to `~/.local/share/g2/memory_consolidation.jsonl`. Try it first with
  `python -m pi_pipeline.memory consolidate` (a dry run); add `--apply` to do it. `G2_CONSOLIDATE=0` turns it off. The call is counted in
  `python -m pi_pipeline.voice.usage`.

* **Which memory shaped a reply** (`python -m pi_pipeline.memory usage`). Per fact it counts how often it was injected, how often G2 named it
  (`declared`) and how often the reply echoed its content words (`matched`), plus the share of turns where memory was used and a list of
  facts injected 20+ times that never mattered. Counters only: no conversation text is stored. `G2_MEMORY_USE_LOG=match` (default) is
  free: the code compares each reply with the notes it was given. `declare` also tags every note ([#12] fact, [s3] sighting) and gives G2 a
  `memory_used` tool to name the notes that mattered: richer (it sees influence with no shared words), but in a measured test the model
  skipped speaking more often (the words-only retry fired on about 3 of 8 question turns), which costs extra API calls: use it for a trial
  window and watch `python -m pi_pipeline.voice.usage`. `off` records nothing.

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

Or a local web UI (stdlib only, binds 127.0.0.1):

```bash
python -m pi_pipeline.memory.webui        # http://127.0.0.1:8899
```

Or open the DB directly: `sqlite3 pi_pipeline/memory/data/g2_memory.db`.

**In conversation:** saying **"forget that"** deletes everything recorded since
the wake word (`Memory.mark_session_start` / `forget_session`, driven by
`voice/loop.py`). Nothing is stored until the wake word fires in the first place.

## Later

- Semantic recall (embeddings) if FTS keyword matching feels too literal —
  weigh the model/latency cost on the Pi first.
- Exercise it across real multi-session conversations once the voice loop runs
  live, and re-check whether recall quality / the fact cap / decay ordering feel
  right on genuine history.
