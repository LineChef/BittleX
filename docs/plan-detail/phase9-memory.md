# Phase 9 — Memory system (detail)

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> Phase 9. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## Phase 9 — Memory system

**Status:** built and tested on the dev machine — `pi_pipeline/memory/`, wired
into the voice loop through the `Memory.recall` / `Memory.record` seam.

- [x] **Persistent store** — SQLite (`memory/data/g2_memory.db`, gitignored;
      stdlib `sqlite3`, inspectable, light for the Pi). Two kinds: an
      `exchanges` log (every turn, mirrored to an FTS5 index) and `facts` (short
      durable notes). Chose SQLite over plain JSON (retrieval wouldn't need a
      full load) and over a vector store (an embedding model/API per turn is too
      heavy/costly for v1).
- [x] **Retrieval** — `recall(user_text)` injects the current fact set plus up
      to `G2_MEMORY_RECALL` older exchanges that match the input (BM25 via FTS5),
      excluding the recent turns `conversation.py` still holds in-context. A
      `remember` tool lets G2 choose what facts to keep (no extra API call).
      Surfacing a fact bumps its `last_recalled`, so stale facts fall off the
      injected set once it hits `G2_MEMORY_MAX_FACTS` — a light decay without a
      scheduler.
- [x] **Kept separate** — Memory only touches the voice loop via one seam;
      nothing in movement or vision imports it.
- [ ] Semantic recall (embeddings) if FTS keyword matching feels too literal —
      weigh model/latency cost on the Pi first.
- [x] **Small web UI to browse / prune memory — BUILT 2026-09-10.**
      `pi_pipeline/memory/webui.py` (`python -m pi_pipeline.memory.webui`,
      stdlib `http.server`, no deps, binds 127.0.0.1): facts list with
      add / delete, searchable conversation log (FTS), a `recall()` preview,
      and a confirm-gated wipe. HTML-escaped. 8 tests (page render + a live
      server round-trip). The CLI still covers everything headless:
      `python -m pi_pipeline.memory {facts,log,search,recall,remember,forget,wipe}`.
- [ ] Exercise it across real multi-session conversations once the voice loop
      runs live (needs an API key / hardware) — and at that point re-check
      whether recall quality, the fact cap, and the decay ordering feel right on
      genuine history rather than test data.
- [ ] **Back up the memory DB off the robot — NOTED 2026-10-02, NOT IMPLEMENTED.**
      On the robot the whole memory is one SQLite file on the Pi's SD card (default
      `~/.local/share/g2/g2_memory.db`, set by `G2_MEMORY_DB`), so a failed or
      corrupted card loses every fact and exchange, and nothing copies it anywhere.
      Idea: a periodic copy to the dev machine (use SQLite's online backup /
      `.backup`, not a plain `cp` of a live file), kept outside the repo like the DB
      itself, with a restore step. Decide frequency and where it lands when the voice
      loop starts running live. Related: if the Petoi AI head ever replaces the Pi,
      memory would live in that vendor's backend (or on our own server) instead -- see
      `docs/research/petoi-ai-head-evaluation.md`.
