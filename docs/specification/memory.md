---
audience: contributor
kind: reference
---

# Memory

Claude has no memory between calls, so G2 keeps a local database of what was said and what is worth remembering, and puts the relevant part into each request.

Behaviour
---------

- Storage: SQLite with FTS5 on the Pi (`memory/data/g2_memory.db`, gitignored). It holds a full exchange log and a short list of facts.
- Recall: Before each Claude call, a short context block is assembled: a pinned core of the most important facts, the highest-ranked other facts (importance and recency), and older exchanges that look related to what was just said, found by a BM25 keyword search over the log.
- Facts: Claude decides what is durable and calls the `remember` tool, with no extra API call.
- Consolidation: When G2 has been idle for a while or is told to go to sleep, one consolidation call merges duplicate facts and drops trivial ones. Every change is logged.
- Exchange filtering: A turn that is only a short command and exact repeats within 10 minutes are not logged (`G2_MEMORY_LOG_COMMANDS=1` logs them).
- Places: Per room, counts only and no dates: things seen, falls and bumps, explorations and goal sessions held there, pictures and the floor. A room is told to G2 and lapses after 6 hours.

Interfaces
----------

- Voice loop: One function pair, `Memory.recall` and `Memory.record`. Memory is not coupled to movement or vision.
- Command line: `python -m pi_pipeline.memory` views, searches, adds, pins or prunes what G2 knows.

Constraints
-----------

- Local only: The database never leaves the Pi except through the Mac backup (`g2membackup`).
- Personal data: Nothing personal goes in a tracked file.
- Reflection: The optional reflection call is off. The recaps are still written locally.

Failure handling
----------------

- Missing database: It is created on first use.
- Command-line removal: "Forget that" removes the session's sightings too.

Verification
------------

- `pi_pipeline/.venv/bin/pytest pi_pipeline/tests -k memory` runs the memory tests with no network.
- Ask G2 to remember a fact, restart the service, and ask for it again.
