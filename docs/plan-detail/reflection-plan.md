# Reflection plan: G2 looks back on his memories and experiences

Approved by the user 2026-10-10 (levels 1 to 3; level 4, reflection that changes behavior, is B23 in [`../behavior-ideas.md`](../behavior-ideas.md) and stays a separate, later decision). Data will grow as the hardware is tested. State: [`../STATUS.md`](../STATUS.md).

## The three levels (built 2026-10-10)

| Level | What | Where | API |
|---|---|---|---|
| 1 Recap | At the end of each exploration session: duration, why it ended, turns away from walls, hits, falls, survey stops, what the camera saw at the stops, the closest wall, and (from place memory P2) the rooms. One JSON line per session in `~/.local/share/g2/experiences.jsonl` on the Pi. | `reflection/recap.py`, written by `explore_session.py` | none |
| 2 Notes | While idle, one Claude call over the last 3 recaps writes at most 3 short first-person notes about his own experience. Saved as facts with source "experience" (importance 1 to 2, never core): visible and deletable in `g2pimem`, and in his prompt when a conversation touches them. | `reflection/reflect.py` | one call per new session |
| 3 Speaking | "What did you do?" / "How was your exploration?" reads the latest recap; "What have you learned?" reads the notes. Both are local voice commands. ("How was your day?" stays an ordinary conversation.) | `voice/commands.py`, `voice/loop.py` | none |

## Guardrails

- **One memory-processing Claude call per session** (user, 2026-10-10), across the memory tidy-up and the reflection together: `MemoryCallGate` (`memory/call_log.py`). The pass that asks first gets it; the other waits. The gate reopens when someone talks to G2 again or the voice service restarts (every exploration hand-over restarts it).
- **A record of every attempt**: `~/.local/share/g2/memory_calls.jsonl` (kind, called / skipped / failed, mode, counts, reason). `python -m pi_pipeline.memory calls [--days N]` prints calls per day. The billed request is also in the API log (sources `consolidate`, `reflect`).
- **Dry run first**: `G2_REFLECT=dry` is the default. The call is made, the notes it would save go to `reflections_dry.jsonl`, nothing is saved. Read them (`python -m pi_pipeline.memory reflect` shows a fresh dry run), then set `G2_REFLECT=on` in the Pi's `.env`, or save one pass with `reflect --apply`.
- **Notes pass two filters**: the ordinary fact filter (no dates, times, schedules) and a stricter one: the note must be about G2 ("I ..."), short, not a time of day or routine, not a near-duplicate of one he has. Nothing about where or when a person was.
- Recaps and notes stay on the Pi (the recap file is not in the repo). Safety logic is never reachable from reflection.

## Next as data arrives

- Room names in the recap and notes once place memory P2 guesses rooms.
- Judge the dry-run notes after a few sessions: specific and true, or generic? Tune the prompt before switching to `on`.
- Level 4 (B23): only after the notes have been good for a while; shadow mode first.
