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

A written recipe (this doc, filled in at that point) naming the exact
constants changing from today's defaults, the reasoning per change (with a
citation back to the specific campaign/round that justified it), whether a
bridge validation round is needed and why, and the final go-ahead plan for
the fresh 20M run itself (tag, expected duration, comparison baseline(s),
and which benchmarks it needs to clear — the resiliency composite score
from `benchmark_resiliency.py` and the standard decathlon/keep-revert bar
both, since this is a deliberate tradeoff being made with eyes open, not a
blind win).

## Status

Not started — waiting on resid30, gait-friction, and resiliency campaigns
to finish. This doc gets filled in, not replaced, once that's true.
