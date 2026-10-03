# docs/

## Start here

| | |
|---|---|
| [`STATUS.md`](STATUS.md) | **What is true right now** — what is deployed, what has run on the robot, open problems, next steps. The only place for current state. |
| [`project-plan.md`](project-plan.md) | The roadmap and decision log: phase checklists with statuses and links. Full per-phase detail is in [`plan-detail/`](plan-detail/). |
| [`backlog.md`](backlog.md) | Open work by ID (H#, R#, B#) — generated from the item headings. |
| [`capabilities.md`](capabilities.md) | Inventory of everything G2 can do, with status — the "what we've built" list. |
| [`how-it-works.md`](how-it-works.md) | Plain-language tour of the parts (walking, voice, memory, vision, link). |
| [`behavior-ideas.md`](behavior-ideas.md) | The behavior ideas themselves (B1…) — the "what next" reference; statuses roll up into the backlog. |
| [`history.md`](history.md) | Dated narrative moved out of the README; not current. |
| [`guides/SOLO.md`](guides/SOLO.md) | Working-solo notes. |

## Where to update what

One home per fact; everything else links. Don't restate the deployed policy, a status, or a test count anywhere else —
`python tools/check_docs.py` (run by the pre-commit hook) fails on broken links, hard-coded test counts, and the policy name in the wrong page.

| When this happens | Write it here — and only here |
|---|---|
| A run, test or measurement | the relevant dated log: [`rl/real-walk-log.md`](rl/real-walk-log.md) (real robot), [`rl/hw1-log.md`](rl/hw1-log.md) (training), other `rl/*` logs; raw data goes in `rl/real-walk-data/` |
| A state change (new policy deployed, hardware fixed or broken, something tested for the first time) | [`STATUS.md`](STATUS.md) — plus a line in the log that holds the detail |
| A capability lands or is parked | [`capabilities.md`](capabilities.md) (and [`STATUS.md`](STATUS.md) if it changes what is deployed) |
| A decision is made or a phase item is done | the entry in [`project-plan.md`](project-plan.md) (checkbox + one line + link to the detail) |
| A backlog item changes status | its own heading in `rl/hardware-gated-backlog.md`, `rl/robustness-backlog.md` or `behavior-ideas.md`, then `python tools/gen_backlog.py` ([`backlog.md`](backlog.md) is generated) |
| The deployed policy changes | `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py` and [`STATUS.md`](STATUS.md); nowhere else names it |
| Wiring, pinouts, assembly | [`../blueprints/`](../blueprints/README.md); vendor specs in [`hardware/specs.md`](hardware/specs.md); firmware tokens in [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md) |
| A command worth remembering | [`guides/cheatsheet.md`](guides/cheatsheet.md) (grouped by task) |
| A research question or vendor evaluation | [`research/`](research/) |

## `guides/` — how to do a thing

| | |
|---|---|
| [`cheatsheet.md`](guides/cheatsheet.md) | Curated quick-reference, grouped by task (setup, robot, BiBoard tokens, walking, deploying, camera, voice, sim/RL) — command tables + full step sequences. |
| [`voice-commands.md`](guides/voice-commands.md) | Every voice command G2 responds to — local commands + conversational skills. |
| [`pi-bring-up.md`](guides/pi-bring-up.md) | Headless Pi Zero 2 W OS setup runbook. |
| [`gait-deployment.md`](guides/gait-deployment.md) | The sim→real path (ONNX export, on-robot loop, bring-up steps). |
| [`train-vision-model.md`](guides/train-vision-model.md) | The SenseCraft capture→train→deploy flow. |
| [`api-setup.md`](guides/api-setup.md) | Anthropic API key, workspace + spend-limit checklist. |
| [`feature-flags.md`](guides/feature-flags.md) | `G2_FEATURES` staged-bring-up flags. |
| [`automated-testing-loop.md`](guides/automated-testing-loop.md) | Runbook for unattended RL reward iteration. |

| [`bring-up-sequence.md`](guides/bring-up-sequence.md) | The ordered day-1 hardware bring-up (executable version: `python -m pi_pipeline.bringup`). |

## `vision/` — camera, detection model, capture

See [`vision/README.md`](vision/README.md) for the index (the reproducible custom-model recipe, capture tracker and checklist, detection layer,
person recognition, on-device detector measurements).

## `hardware/` — specs + hardware research

| | |
|---|---|
| [`specs.md`](hardware/specs.md) | Vendor-doc specs for every part + "why it matters". |
| [`parts-and-decisions.md`](hardware/parts-and-decisions.md) | The finalized parts list, resolved/open hardware questions, power-awareness plan. |
| [`opencat-gait-structure.md`](hardware/opencat-gait-structure.md) | How OpenCat gaits are structured (reference). |
| [`diagnostics.md`](hardware/diagnostics.md) | Black-box logging + watchdog design (Phase 1 + non-HW Phase 2 built). |
| [`servo-thermal.md`](hardware/servo-thermal.md) | Servo overheat risk + the layered mitigation (Layer 1+2 built). |
| [`pi-power.md`](hardware/pi-power.md) | Powering the Pi (PiSugar S; BiBoard data-only) + power-management levers. |
| [`self-righting.md`](hardware/self-righting.md) | Bittle's built-in self-right — limited; no BiBoard-V1 IR trigger. |
| [`petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md) | Confirmed-from-source serial tokens, IMU thresholds, skill format. |
| [`petoi-skills-survey.md`](hardware/petoi-skills-survey.md) | Which OpenCat built-in skills are worth pulling into G2. |
| [`calibration-and-bringup-research.md`](hardware/calibration-and-bringup-research.md) | Petoi's official calibration/first-power-on docs, cross-checked against our bring-up plan. |

## Hardware build blueprints

The physical assembly record (wiring, soldering, mounting, calibration, real measurements) and the wiring diagrams live in
[`/blueprints`](../blueprints/README.md) at the repo root — separate from `hardware/`'s specs and research.

## `research/` — community projects, external findings

| | |
|---|---|
| [`petoi-ai-head-evaluation.md`](research/petoi-ai-head-evaluation.md) | The Petoi AI Head: whether it replaces the Pi — criteria, behavior inventory, test steps, scorecard. |
| [`community-projects.md`](research/community-projects.md) | Findings from reviewing other Bittle/Petoi community projects (BittleJuice, bittle-mujoco, MH-FLOCKE, TypeFly) + the incorporation plan. |

## `rl/` — gait training: conclusions, backlogs, specs, real-robot logs

See [`rl/README.md`](rl/README.md) for the index.
