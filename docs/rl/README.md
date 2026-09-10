# docs/rl/

Reinforcement-learning gait work: the conclusions that still matter, the
backlogs, and the specs for anything deferred. Sim locomotion is **done pending
the real-robot H1 head-to-head** — see `../project-plan.md` Phase 3.

| | |
|---|---|
| [`hardware-gated-backlog.md`](hardware-gated-backlog.md) | RL/gait work deferred to hardware (H1–H12), each with a concrete trigger. |
| [`h1-rubric.md`](h1-rubric.md) | The real-robot learned-vs-scripted comparison — methodology, course, decision rule. |
| [`vision-in-gait.md`](vision-in-gait.md) | The vision-in-the-gait campaign (Phases A–F) — **closed**: what was tried, the verdict, what's built and dormant. |
| [`refinement-regimen.md`](refinement-regimen.md) | The staged pre-hardware robustness push (concluded). |
| [`robustness-backlog.md`](robustness-backlog.md) | Categorised real-world scenarios for future training. |
| [`skill-learning-method.md`](skill-learning-method.md) | The agreed recipe for teaching G2 a new motor skill. |
| [`adapter-skill-probe-spec.md`](adapter-skill-probe-spec.md) | Frozen base + small trained skill modules — specced, deferred. |
| [`phase4-decision-log.md`](phase4-decision-log.md) | Phase 4 stance-recovery decisions. |
| [`getup-sim-replay.md`](getup-sim-replay.md) | Replaying firmware `rc`/`rl` get-up in PyBullet (0/2 recover — sim can't validate it). |
| [`gait-benchmark.md`](gait-benchmark.md) | Learned vs. scripted `wkF` head-to-head (sim). |

The per-round training logs (Runs 2–7, the automated loops, the survive loop)
were removed 2026-09-10; their conclusions are condensed in `../project-plan.md`
"Training history" and git history has the full text.
