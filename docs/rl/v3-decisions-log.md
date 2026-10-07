# V3 retrain: decisions log

Decisions made while the V3 queue runs unattended (the user asked on 2026-10-07 for decisions to be made along the way and documented for later review). Newest last.
Plan and hand-off: [`v3-retrain-plan.md`](v3-retrain-plan.md). Each entry: what was decided, why, and what it changes.

## 2026-10-07

- **Replicate runs added after S3** (seeds 43 and 44: control, S1, S2 at each; then the combined S1+S2 recipe at seeds 42, 43, 44). Why: S1 and S2 each looked good against their own control at one seed, but one seed cannot separate a lever from run-to-run variation. A matching control at every seed is included because the controls C0 and C0b differed a lot in heading, and a lever can only be read against a control of the same kind. About 10 hours of runs. Not screens: they never feed K3's lever list.
- **`review_replicates` pause removed** (user, 2026-10-07): the queue now runs straight on through S4-S10, K3, the stage chain and the pre-20M report, and pauses only at `hardware_checkin` (which needs the user on G2). The 20M still starts only on the user's go.
- **Benchmark version 5** adds the difficulty-level ladder, matched to training's per-category levels, and a `report` job runs before the hardware check-in. See the plan's 2026-10-07 update.
