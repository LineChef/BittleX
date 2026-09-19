# Final synthesis: from testing to a fresh 20M training run

Queued last, after every other campaign in this testing cycle is complete:
resid30 (`resid30-log.md`), gait-friction (`gait-friction-log.md`), and
resiliency (`resiliency-log.md`). This is the step where findings become a
concrete training recipe, not another round of exploration.

## Purpose

Everything up to this point is characterization: does X matter, by how
much, at what severity. This phase turns "here's what we found" into "here's
what we're actually training." Explicitly two parts:

1. **Analysis** — review every campaign's logged rounds and decide, with
   the real data in hand, which specific changes are justified: which
   reward-term rebalances, which curriculum/DR knobs to enable or expand,
   what `RESIDUAL_SCALE_DEG` should actually be, whether `FAC_NOSTALL`
   earned a permanent place in the recipe, etc. Not everything tested will
   turn out worth keeping — a clean writeup says what didn't pan out too,
   not just what did.
2. **Bridge plan** — before committing a full 20M run to a combined recipe,
   assess whether any of the decided changes need one more short validation
   round *together* first. Several small changes that each tested fine in
   isolation don't automatically combine cleanly (this is exactly the
   pattern already documented in `robustness-backlog.md`'s own method:
   "more domain randomisation is not monotonically better... every knob
   competes for policy capacity"). If two or more of the kept changes
   plausibly interact (e.g. a reward rebalance + a new curriculum knob both
   touching how much the gait deviates from the reference), a short 2-3M
   combined-recipe check comes before the 20M commitment, not after.

## What this step is not

Not a place to introduce new untested ideas. Anything proposed here should
trace back to a specific logged finding in one of the three campaign docs
— if it doesn't have a round/result to point to, it belongs in a future
campaign's backlog, not in this recipe.

## Deliverable

Two parts, both in this doc, filled in once all three campaigns are done:

1. **Round-by-round summary, every campaign.** For each round that actually
   ran (resid30, gait-friction, resiliency alike): what was being tested,
   what the result was, and what it means -- a plain narrative recap, not
   just a link back to the individual campaign logs. Someone reading only
   this doc should come away understanding the whole testing journey, not
   just the final answer. The per-round detail still lives in each
   campaign's own log; this is the readable summary layer on top.
2. **The recipe itself** -- naming the exact constants changing from
   today's defaults, the reasoning per change (with a citation back to the
   specific campaign/round that justified it), whether a bridge validation
   round is needed and why, and the final go-ahead plan for the fresh 20M
   run itself (tag, expected duration, comparison baseline(s), and which
   benchmarks it needs to clear -- the resiliency composite score from
   `benchmark_resiliency.py` and the standard decathlon/keep-revert bar
   both, since this is a deliberate tradeoff being made with eyes open, not
   a blind win).

## Hard checkpoint before the 20M run (user, 2026-09-18)

**Do not launch the final 20M run without explicit user go-ahead**, even
though every other round this cycle has been run autonomously per
standing instruction. The user wants to review all three campaigns'
results together, in one pass, before the recipe/launch decision gets
made -- this overrides the general "don't stop testing" autonomy for this
one specific transition. Everything up through finishing the analysis and
writing the recipe (the two deliverable parts above) can proceed
unattended as normal; the line is launching the actual 20M run itself.

## Status

Not started — waiting on resid30, gait-friction, and resiliency campaigns
to finish. This doc gets filled in, not replaced, once that's true.
