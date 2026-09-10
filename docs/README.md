# docs/

| Start here | |
|---|---|
| [`project-plan.md`](project-plan.md) | The living roadmap and decision log — read before starting work in any area. |
| [`how-it-works.md`](how-it-works.md) | Plain-language tour of the parts (walking, voice, memory, vision, link). |
| [`behavior-ideas.md`](behavior-ideas.md) | Backlog of behaviours to explore (IDs B1…) — the "what next" list. |
| [`SOLO.md`](SOLO.md) | Working-solo notes. |

## `guides/` — how to do a thing

| | |
|---|---|
| [`cheatsheet.md`](guides/cheatsheet.md) | Curated quick-reference — command tables + full step sequences. |
| [`pi-bring-up.md`](guides/pi-bring-up.md) | Headless Pi Zero 2 W OS setup runbook. |
| [`gait-deployment.md`](guides/gait-deployment.md) | The sim→real path for `run20m_ppo` (ONNX, on-robot loop, bring-up steps). |
| [`train-vision-model.md`](guides/train-vision-model.md) | The SenseCraft capture→train→deploy flow. |
| [`api-setup.md`](guides/api-setup.md) | Anthropic API key, workspace + spend-limit checklist. |
| [`feature-flags.md`](guides/feature-flags.md) | `G2_FEATURES` staged-bring-up flags. |
| [`automated-testing-loop.md`](guides/automated-testing-loop.md) | Runbook for unattended RL reward iteration. |

## `vision/` — camera, detection model, capture

| | |
|---|---|
| [`custom-model-recipe.md`](vision/custom-model-recipe.md) | **The reproducible custom-detection-model recipe** — the frozen-firmware constraint, `ultralytics==8.2.8` + local export, `tools/gv2/`. |
| [`capture-progress.md`](vision/capture-progress.md) | Capture / dataset tracker + the diagnostic-logging shot list. |
| [`capture-checklist.md`](vision/capture-checklist.md) | Per-session capture routine. |
| [`detection-layer.md`](vision/detection-layer.md) | The one-model-slot architecture (safety / interaction / objects). |
| [`person-recognition.md`](vision/person-recognition.md) | B15 recognition + enrollment design. |
| [`detector-bench.md`](vision/detector-bench.md) | Measured on-device detector behaviour + firmware facts. |

## `hardware/` — specs + hardware research

| | |
|---|---|
| [`specs.md`](hardware/specs.md) | Vendor-doc specs for every part + "why it matters". |
| [`diagnostics.md`](hardware/diagnostics.md) | Black-box logging + watchdog design (Phase 1 + non-HW Phase 2 built). |
| [`servo-thermal.md`](hardware/servo-thermal.md) | Servo overheat risk + the layered mitigation (Layer 1+2 built). |
| [`pi-power.md`](hardware/pi-power.md) | Powering the Pi (PiSugar S; BiBoard data-only) + power-management levers. |
| [`self-righting.md`](hardware/self-righting.md) | Bittle's built-in self-right — limited; no BiBoard-V1 IR trigger. |
| [`petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md) | Confirmed-from-source serial tokens, IMU thresholds, skill format. |
| [`petoi-skills-survey.md`](hardware/petoi-skills-survey.md) | Which OpenCat built-in skills are worth pulling into G2. |

## `rl/` — gait training: conclusions, backlogs, specs

| | |
|---|---|
| [`hardware-gated-backlog.md`](rl/hardware-gated-backlog.md) | RL/gait work deferred to hardware (H1–H12), each with a trigger. |
| [`h1-rubric.md`](rl/h1-rubric.md) | The real-robot learned-vs-scripted comparison rubric. |
| [`vision-in-gait.md`](rl/vision-in-gait.md) | The vision-in-the-gait campaign (Phases A–F) — **closed**; why, and what was built. |
| [`refinement-regimen.md`](rl/refinement-regimen.md) | The pre-hardware robustness push (concluded). |
| [`robustness-backlog.md`](rl/robustness-backlog.md) | Categorised real-world scenarios for future training. |
| [`skill-learning-method.md`](rl/skill-learning-method.md) | The agreed recipe for a new G2 motor skill. |
| [`adapter-skill-probe-spec.md`](rl/adapter-skill-probe-spec.md) | Frozen-base + small trained skill modules — specced, deferred. |
| [`phase4-decision-log.md`](rl/phase4-decision-log.md) | Phase 4 stance-recovery decisions. |
| [`getup-sim-replay.md`](rl/getup-sim-replay.md) | Replaying the firmware `rc`/`rl` get-up in PyBullet (0/2 recover). |
| [`gait-benchmark.md`](rl/gait-benchmark.md) | Learned vs. scripted `wkF` head-to-head. |

Per-round training logs (Runs 2–7, the automated loops, the survive loop) were
removed 2026-09-10 — their conclusions are in `project-plan.md` "Training history"
and the backlogs; git history has the full text.
