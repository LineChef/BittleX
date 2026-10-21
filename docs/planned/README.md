# Planned (not built)

Work that is **not part of the running build**: ideas, plans and parked projects. Nothing here is deployed on G2. What is deployed: [`../STATUS.md`](../STATUS.md); what is built: [`../capabilities.md`](../capabilities.md).

| | |
|---|---|
| [`ai-head/`](ai-head/README.md) | The Petoi AI Head: evaluation, the hybrid plan and the staged implementation. |
| [`robot-arm.md`](robot-arm.md) | Petoi's Bittle X+Arm gripper module: install, claw calibration, skill tokens, voice commands, open questions. |
| [`place-memory-plan.md`](place-memory-plan.md) | Remembering places seen during exploration. |
| [`reflection-plan.md`](reflection-plan.md) | Reflection over memory (sleep-time consolidation). |
| [`exploration-object-learning-plan.md`](exploration-object-learning-plan.md) | Exploration survey pictures, naming objects by voice, recognition, "what am I looking at?". |
| [`firmware-fork-case.md`](firmware-fork-case.md) | What forking the BiBoard (or AI Head) firmware would unblock, with pros, cons and decision triggers. |
| [`behavior-ideas.md`](behavior-ideas.md) | The behavior ideas (B#), the "what next" reference. |
| [`hardware-gated-backlog.md`](hardware-gated-backlog.md) | RL/gait work deferred until the real robot can supply data (H#), each with a trigger. |
| [`robustness-backlog.md`](robustness-backlog.md) | Categorised real-world scenarios for future training (R#). |
| [`heavy-load-training-plan.md`](heavy-load-training-plan.md) | A new policy that stays stable carrying up to 1 lb (slower is fine): measure, train, judge. |
| [`adapter-skill-probe-spec.md`](adapter-skill-probe-spec.md) | Frozen base walk plus small trained skill modules: specced, deferred. |

Statuses roll up into the generated [`../backlog.md`](../backlog.md) (`python tools/gen_backlog.py` after changing an item's heading).
A high-step gait is still a wanted goal; both training attempts are closed, see [`../archive/plan-detail/high-step-creep-training-plan.md`](../archive/plan-detail/high-step-creep-training-plan.md).
