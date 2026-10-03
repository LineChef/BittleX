# docs/rl/

Reinforcement-learning gait work: the conclusions that still matter, the
backlogs, and the specs for anything deferred. Sim locomotion is **done pending
the real-robot H1 head-to-head** — see [`../project-plan.md`](../project-plan.md) Phase 3. Which policy is deployed and what has been tested on
the robot: [`../STATUS.md`](../STATUS.md).

| | |
|---|---|
| [`real-walk-log.md`](real-walk-log.md) | **Real-robot walks and servo troubleshooting** (10/01–), with the where-we-left-off list; raw data in [`real-walk-data/`](real-walk-data/). |
| [`walking-policy.md`](walking-policy.md) | What the learned gait does and its limits (the original `run20m_ppo` description). |
| [`hw1-log.md`](hw1-log.md) | Training under the real control path (5 Hz IMU, `i` command timing), the policy lineage and benchmark fixes. |
| [`hardware-gated-backlog.md`](hardware-gated-backlog.md) | RL/gait work deferred to hardware (H#), each with a concrete trigger. Index of statuses: [`../backlog.md`](../backlog.md). |
| [`h1-rubric.md`](h1-rubric.md) | The real-robot learned-vs-scripted comparison — methodology, course, decision rule. |
| [`vision-in-gait.md`](vision-in-gait.md) | The vision-in-the-gait campaign (Phases A–F) — **closed**: what was tried, the verdict, what's built and dormant. |
| [`refinement-regimen.md`](refinement-regimen.md) | The staged pre-hardware robustness push (concluded). |
| [`robustness-backlog.md`](robustness-backlog.md) | Categorised real-world scenarios for future training. |
| [`skill-learning-method.md`](skill-learning-method.md) | The agreed recipe for teaching G2 a new motor skill. |
| [`adapter-skill-probe-spec.md`](adapter-skill-probe-spec.md) | Frozen base + small trained skill modules — specced, deferred. |
| [`phase4-decision-log.md`](phase4-decision-log.md) | Phase 4 stance-recovery decisions. |
| [`getup-sim-replay.md`](getup-sim-replay.md) | Replaying firmware `rc`/`rl` get-up in PyBullet (0/2 recover — sim can't validate it). |
| [`gait-benchmark.md`](gait-benchmark.md) | Learned vs. scripted `wkF` head-to-head (sim). |
| [`resid30-log.md`](resid30-log.md), [`gait-friction-log.md`](gait-friction-log.md), [`resiliency-log.md`](resiliency-log.md), [`slope-ceiling-log.md`](slope-ceiling-log.md) | The 2026-09 sim campaign logs (some superseded — each says so at the top). |
| [`final-synthesis-plan.md`](final-synthesis-plan.md) | How the campaign findings become a fresh 20M training recipe. |
| [`foot-probing-log.md`](foot-probing-log.md), [`crawl-climb-session-checkpoint.md`](crawl-climb-session-checkpoint.md) | Foot-probing and crawl-climb work (reference frames in [`reference-frames/`](reference-frames/)). |

The per-round training logs (Runs 2–7, the automated loops, the survive loop)
were removed 2026-09-10; their conclusions are condensed in
[`../plan-detail/phase3-rl-training.md`](../plan-detail/phase3-rl-training.md) "Training history" and git history has the full text.
