# Walking and training (RL)

Reinforcement-learning gait work that is part of the current build: how the deployed gait is trained, scored and logged on the real robot. Which policy is deployed
and what has been tested on G2: [`../STATUS.md`](../STATUS.md). Roadmap: [`../project-plan.md`](../project-plan.md) Phase 3.

| | |
|---|---|
| [`walking-policy.md`](walking-policy.md) | What the learned gait does and its limits. |

### How it is trained

| | |
|---|---|
| [`training-pipeline.md`](training-pipeline.md) | **Start here for training.** The pipeline end to end: profile and levers, chains, train, score, export, promote, feed real data back. |
| [`training-upgrade-2026-10.md`](training-upgrade-2026-10.md) | The trainer behind the V4 to V6 chains: frontier curriculum, levers, bugs fixed, measurements, pitfalls. |
| [`results-index.md`](results-index.md) | Every tracked result file under `trained/` with the docs that cite it (generated). |

### On the real robot

| | |
|---|---|
| [`real-walk-log.md`](real-walk-log.md) | Real-robot walks and servo troubleshooting (10/01 on), with the end-of-session state list. Raw data: [`real-walk-data/`](real-walk-data/). What each hardware log carries: [`hardware-logging.md`](hardware-logging.md). |
| [`hardware-logging.md`](hardware-logging.md) | What rungait.py --log writes, what the firmware can and cannot provide, and what is worth using as training evidence. Written 2026-10-07. |
| [`carpet-findings-2026-10-20.md`](carpet-findings-2026-10-20.md) | The carpet work of 2026-10-20: the failure, the sim carpet model, every probe and real walk, what helped, what did not, and what to try next. Read before touching carpet again. |
| [`real-data-pipeline.md`](real-data-pipeline.md) | Always-on capture, ingest gates and sim calibration snapshots. |
| [`sysid-capture-plan.md`](sysid-capture-plan.md) | The system-identification capture sessions. |

### History and method

| | |
|---|---|
| [`hw1-log.md`](hw1-log.md) | Training under the real control path (5 Hz IMU, command timing); the policy lineage and benchmark fixes. |
| [`skill-learning-method.md`](skill-learning-method.md) | The agreed recipe for teaching G2 a new motor skill. |
| [`passability-audit.md`](passability-audit.md) | Standing rule: difficulty never ramps above what a capable policy can pass; the audit that measures each hazard's top threshold. |
| [`getup-sim-replay.md`](getup-sim-replay.md) | Replaying firmware `rc`/`rl` get-up in PyBullet (the sim cannot validate it). |
| [`h1-rubric.md`](h1-rubric.md) | The learned-vs-scripted real-robot comparison method. |

Training plans for the V5 and V6 chains: [`../plan-detail/v5-training-plan.md`](../plan-detail/v5-training-plan.md), [`../plan-detail/v6-staged-training-plan.md`](../plan-detail/v6-staged-training-plan.md).
Deferred RL work and backlogs: [`../planned/`](../planned/README.md). Closed campaigns and old sim logs: [`../archive/`](../archive/README.md).

Scripts for closed campaigns (vision goal, climbing and foot probing, the resilience, friction and slope sweeps, the old hardware-IMU retrain chains) were removed from the working tree on 2026-10-17; recover one with `git show archive/rl-campaign-scripts-2026-10-17:rl_training/opencat-gym/<name>.py`.
