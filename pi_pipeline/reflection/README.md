# Reflection

G2 reflecting on his own experience. Design and levels: [`../../docs/planned/reflection-plan.md`](../../docs/planned/reflection-plan.md). The notes are stored as ordinary memory facts: [`../memory/README.md`](../memory/README.md).

| Module | Level | What it does |
|---|---|---|
| `recap.py` | 1 | A recap of each exploration session, counted from events the behavior layer already emits (turns away from a wall, hits, survey stops). No picture, no API call. The recap is appended to `experiences.jsonl` when a session ends |
| `reflect.py` | 2 | While G2 is idle, one Claude call reads the latest recaps and writes up to three short notes about himself ("I keep turning away from walls in the kitchen"). Saved as facts with source `experience`, importance 1 or 2, never core; guarded so a note is never about a person or about where or when anyone was |

`G2_REFLECT` sets the mode: `off`; `dry` (the default: the call is made and the notes it would save go to `reflections_dry.jsonl` for you to read; nothing is saved); `on` (saved). One memory-processing call per session is shared with the memory tidy-up, and every attempt is recorded (`python -m pi_pipeline.memory calls`).

```bash
python -m pi_pipeline.memory reflect            # a dry run now
python -m pi_pipeline.memory reflect --apply    # save the notes
```

"What did you do?" and "What have you learned?" are answered locally, with no API call.
