# Memory patterns for robots and companion agents: what fits G2

Researched 2026-10-04 (web). The question: which proven memory designs would help G2 build persistent memory and have it shape his answers?
G2's memory today is described in [`pi_pipeline/memory/README.md`](../../pi_pipeline/memory/README.md): SQLite with an exchange log searched by
BM25 for older relevant turns, plus short facts G2 saves himself with the `remember` tool, the newest 30 injected on every turn.

## The patterns, and where G2 stands

| Pattern | Source | What it is | G2 today |
|---|---|---|---|
| Memory stream with scored retrieval | [Generative Agents](https://agentpatterns.ai/agent-design/generative-agents-memory-stream/) | Every memory carries a time and an importance score; retrieval ranks by recency (decay), importance (the model rates it 1-10) and relevance | Facts rank by recency only; no importance score; exchanges rank by BM25 relevance only |
| Reflection | Generative Agents | Periodically, when enough important things accumulate, the agent writes higher-level conclusions ("they seem to enjoy mornings with the dog") and stores those | None: facts are only what G2 chose to save mid-conversation |
| Tiers: core / recall / archival | [MemGPT / Letta](https://docs.letta.com/guides/agents/architectures/memgpt) | A small always-in-prompt core block (a Human block and a Persona block), a searchable conversation log, and a larger archive the agent queries; the agent itself edits the tiers with tool calls | Two tiers already: injected facts (core-like) and the searchable exchange log (recall-like). No separate persona/self block, no archive |
| Sleep-time consolidation | [Letta memory blocks and sleep-time compute](https://learn.traeai.com/t/ai-engineering/phases/14-agent-engineering/08-memory-blocks-sleep-time-compute.html) | While idle, a background pass cleans, merges and rewrites memory so the foreground stays fast | G2 has a sleep mode and an idle state that nothing uses for memory work |
| Forgetting curve with rehearsal | [MemoryBank](https://arxiv.org/pdf/2305.10250) | Memories fade over time unless recalled; recalling strengthens them; also builds a user-personality summary | `last_recalled` is touched whenever a fact is injected, which gives light decay only once the 30-fact cap is hit |
| Episodic versus semantic memory | [Long-term memory for social robots](https://arxiv.org/pdf/1811.10758) | Semantic = facts; episodic = events with context (where, when, who, feelings); a companion needs both, plus consolidation and forgetting | Semantic facts yes; episodes only as the raw exchange log |
| Spatio-temporal observation memory | [ReMEmbR](https://arxiv.org/abs/2409.13682) | The robot captions what it sees every few seconds and stores caption + time + position as text; an LLM agent searches it to answer "where did I see X / when" | Looks produce a spoken description that lands in the exchange log; no time/place structure, no search by "what did you see earlier" |

## What looks useful for G2, most valuable first

1. **An importance score on facts** (Generative Agents). One extra field on the `remember` tool ("how much will this matter later, 1-5"). Rank injected facts by importance + recency instead of recency alone, so a name outranks a passing remark when the 30-slot cap bites. Cheap: no extra API call.
2. **A pinned core block** (MemGPT). Keep a small, always-present "about me" and "about my people" block, separate from the 30-fact rotation: how G2 looks (the single "I look like" slot already behaves this way), who lives here, the dog and cat. Nothing in it should ever rotate out.
3. **Sleep-time consolidation** (Letta, MemoryBank, Generative Agents' reflection). When G2 goes to sleep or has been idle for a while, run one batched Claude call over the day's exchanges to merge near-duplicates, write a few reflections, and drop what is trivial. It costs a call or two a day, off the conversational path.
4. **A text-only observation log from looks** (ReMEmbR). When G2 looks, store caption + time (+ the detector's labels) as a searchable record. "What did you see earlier?" then works from text, with no pictures kept, which also fits the privacy stance. Place can be added later if G2 gets odometry.
5. **Better retrieval of old moments.** Today it matches the person's words, which speech recognition garbles ("being", "today"). Options: search the assistant's side more, require two matching words, or have Claude rewrite the query. Embeddings (semantic search) are the standard answer but are heavy on a Pi Zero 2 W; hold them back until the cheaper fixes are measured.
6. **Make memory visibly shape answers.** Memory is only useful if it is used: keep the instruction that facts are for natural use, and add a "did this fact come up" log line per turn to see which facts are actually influencing replies (it also finds facts that never matter).

## Status (2026-10-05)
Items 1-4 are built (importance, pinned core block, sleep-time consolidation, text-only sightings log); see `pi_pipeline/memory/README.md`.
Items 5 (retrieval of old moments) and 6 (a log of which facts shape answers) are not built.

## Cautions that apply here
* Importance and reflection add API calls; track them with `python -m pi_pipeline.voice.usage` before and after.
* Reflections are model-written conclusions about people: keep them labelled as inferred, easy to see (`python -m pi_pipeline.memory facts`) and easy to delete ("forget that"), and never infer schedules or whereabouts (the existing rule in the `remember` tool).
* Everything personal stays in the gitignored database, never in the repo.
