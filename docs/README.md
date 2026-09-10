# docs/

| Start here | |
|---|---|
| [`project-plan.md`](project-plan.md) | The living roadmap and decision log — read before starting work in any area. |
| [`how-it-works.md`](how-it-works.md) | Plain-language tour of the parts (walking, voice, memory, vision, link). |
| [`hardware-readiness.md`](hardware-readiness.md) | State of everything before hardware arrives + the day-1 checklists. |
| [`behavior-ideas.md`](behavior-ideas.md) | Backlog of behaviours to explore (IDs B1…) — the "what next" list. |
| [`gait-deployment.md`](gait-deployment.md) | The sim→real path for `run20m_ppo` (ONNX, on-robot loop, bring-up steps). |
| [`feature-flags.md`](feature-flags.md) | `G2_FEATURES` staged-bring-up flags. |
| [`train-a-visual-model.md`](train-a-visual-model.md) | The SenseCraft single-class capture→train→deploy flow. |
| [`SOLO.md`](SOLO.md) | Working-solo notes. |

## `reference/` — how-to

| | |
|---|---|
| [`cheatsheet.md`](reference/cheatsheet.md) | Curated quick-reference — command tables + full step sequences. |
| [`automated-testing-loop.md`](reference/automated-testing-loop.md) | Runbook for unattended RL reward iteration. |
| [`api-setup.md`](reference/api-setup.md) | Anthropic API key + spend-limit checklist. |

## `research/` — external research notes

| | |
|---|---|
| [`hardware-specs.md`](research/hardware-specs.md) | Vendor-doc specs for every part + "why it matters". |
| [`grove-vision-v2-custom-model.md`](research/grove-vision-v2-custom-model.md) | **The reproducible custom-detection-model recipe** — frozen firmware constraint, `ultralytics==8.2.8` + local export, `tools/gv2/`. |
| [`capture-progress.md`](research/capture-progress.md) | Vision capture / dataset tracker + the diagnostic-logging shot list. |
| [`capture-session-checklist.md`](research/capture-session-checklist.md) | Per-session capture routine. |
| [`detection-layer.md`](research/detection-layer.md) | The one-model-slot architecture (safety / interaction / objects). |
| [`vision-detector-bench.md`](research/vision-detector-bench.md) | Measured on-device detector behaviour + firmware facts. |
| [`person-recognition.md`](research/person-recognition.md) | B15 recognition + enrollment design. |
| [`petoi-firmware-reference.md`](research/petoi-firmware-reference.md) | Confirmed-from-source serial tokens, IMU thresholds, skill format. |
| [`petoi-skills-survey.md`](research/petoi-skills-survey.md) | Which OpenCat built-in skills are worth pulling into G2. |
| [`servo-thermal.md`](research/servo-thermal.md) | Servo overheat risk + the layered mitigation (Layer 1+2 built). |
| [`hardware-diagnostics.md`](research/hardware-diagnostics.md) | Black-box logging + watchdog design (Phase 1 + non-HW Phase 2 built). |
| [`pi-power.md`](research/pi-power.md) | Powering the Pi (PiSugar S; BiBoard data-only) + power-management levers. |
| [`pi-set-up.md`](research/pi-set-up.md) | Headless Pi Zero 2 W OS setup steps. |
| [`self-righting-research.md`](research/self-righting-research.md) | Bittle's built-in self-right — limited; no BiBoard-V1 IR trigger. |
| [`bittle-rl-projects.md`](research/bittle-rl-projects.md) | Prior-art scan of Bittle RL projects. |

## `rl-runs/` — gait training history & specs

| | |
|---|---|
| [`hardware-gated-training-backlog.md`](rl-runs/hardware-gated-training-backlog.md) | RL/gait work deferred to hardware (H1–H12), each with a trigger. |
| [`gait-benchmark.md`](rl-runs/gait-benchmark.md) | Learned vs. scripted `wkF` head-to-head. |
| [`h1-head-to-head-rubric.md`](rl-runs/h1-head-to-head-rubric.md) | The real-robot learned-vs-scripted comparison rubric. |
| [`vision-goal-locomotion-plan.md`](rl-runs/vision-goal-locomotion-plan.md) | The vision-in-the-gait campaign (Phases A–F) — **closed**. |
| [`getup-sim-replay.md`](rl-runs/getup-sim-replay.md) | Replaying the firmware `rc`/`rl` get-up in PyBullet (0/2 recover). |
| [`skill-learning-method.md`](rl-runs/skill-learning-method.md) | The agreed recipe for a new G2 motor skill. |
| [`adapter-skill-probe-spec.md`](rl-runs/adapter-skill-probe-spec.md) | Frozen-base + small trained skill modules — specced, deferred. |
| [`refinement-regimen.md`](rl-runs/refinement-regimen.md) | The pre-hardware robustness push (concluded). |
| [`robustness-backlog.md`](rl-runs/robustness-backlog.md) | Categorised real-world scenarios for future training. |
| [`phase4-decision-log.md`](rl-runs/phase4-decision-log.md) | Phase 4 stance-recovery decisions. |
| `auto-iteration-log*.md` / `auto-iteration-report-*.md` | Per-round logs + wrap-ups — Runs 2–7, the level-ground loop, the resid line, the survive loop. |
