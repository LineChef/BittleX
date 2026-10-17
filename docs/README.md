# docs/

## Start here

| | |
|---|---|
| [`STATUS.md`](STATUS.md) | **What is true right now** — what is deployed, what has run on the robot, open problems, next steps. The only place for current state. |
| [`project-plan.md`](project-plan.md) | The roadmap and decision log: phase checklists with statuses and links. Full per-phase detail is in [`plan-detail/`](plan-detail/); the next hardware session is [`plan-detail/hardware-session-plan-2026-10-09.md`](plan-detail/hardware-session-plan-2026-10-09.md). |
| [`backlog.md`](backlog.md) | Open work by ID (H#, R#, B#) — generated from the item headings. |
| [`capabilities.md`](capabilities.md) | Inventory of everything G2 can do, with status — the "what we've built" list. |
| [`architecture.md`](architecture.md) | How the pieces fit together: the robot, the Pi and the dev machine, the subsystems and their seams, how a walk happens and how training reaches the robot. |
| [`code-map.md`](code-map.md) | Where each code package is documented: its README next to the code, and the docs pages that explain it. |
| [`how-it-works.md`](how-it-works.md) | Plain-language tour of the parts (walking, voice, memory, vision, behavior, link). |

## Where to update what

One home per fact; everything else links. Don't restate the deployed policy, a status, or a test count anywhere else —
`python tools/check_docs.py` (run by the pre-commit hook) fails on broken links, hard-coded test counts, and the policy name in the wrong page.

| When this happens | Write it here — and only here |
|---|---|
| A run, test or measurement | the relevant dated log: [`rl/real-walk-log.md`](rl/real-walk-log.md) (real robot; what each hardware log carries: [`rl/hardware-logging.md`](rl/hardware-logging.md)), [`rl/hw1-log.md`](rl/hw1-log.md) (training), other `rl/*` logs; raw data goes in `rl/real-walk-data/` |
| A state change (new policy deployed, hardware fixed or broken, something tested for the first time) | [`STATUS.md`](STATUS.md) — plus a line in the log that holds the detail |
| A capability lands or is parked | [`capabilities.md`](capabilities.md) (and [`STATUS.md`](STATUS.md) if it changes what is deployed) |
| A decision is made or a phase item is done | the entry in [`project-plan.md`](project-plan.md) (checkbox + one line + link to the detail) |
| A backlog item changes status | its own heading in `planned/hardware-gated-backlog.md`, `planned/robustness-backlog.md` or `planned/behavior-ideas.md`, then `python tools/gen_backlog.py` ([`backlog.md`](backlog.md) is generated) |
| The deployed policy changes | `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py` and [`STATUS.md`](STATUS.md); nowhere else names it |
| Wiring, pinouts, assembly | [`../blueprints/README.md`](../blueprints/README.md); vendor specs in [`hardware/specs.md`](hardware/specs.md); firmware tokens in [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md) |
| Scratch / temp files pile up (Mac or Pi) | `python tools/g2_cleanup.py` (`g2clean`): dry run lists them, `--apply` deletes by exact path and cleans the Pi's `trained/` folder; a hook reminds on every prompt and the pre-commit hook warns about leftovers and blocks adds of >150 files or >5 MB |
| A command worth remembering | [`guides/cheatsheet.md`](guides/cheatsheet.md) (grouped by task) |
| A research question or vendor evaluation | [`research/`](research/) |

## `guides/` — how to do a thing

See [`guides/README.md`](guides/README.md) for the index.

## `vision/` — camera, detection model, capture

See [`vision/README.md`](vision/README.md) for the index (the reproducible custom-model recipe, capture tracker and checklist, detection layer,
person recognition, on-device detector measurements).

## `hardware/` — specs + hardware research

See [`hardware/README.md`](hardware/README.md) for the index.

## Hardware build blueprints

The physical assembly record (wiring, soldering, mounting, calibration, real measurements, the I2S audio and Pi-to-BiBoard build logs) and the wiring diagrams live in
[`/blueprints`](../blueprints/README.md) at the repo root — separate from `hardware/`'s specs and research.

## `research/` — community projects, external findings

See [`research/README.md`](research/README.md) for the index.

## `rl/` — gait training: conclusions, backlogs, specs, real-robot logs

See [`rl/README.md`](rl/README.md) for the index.

## `planned/` — not built yet

Ideas, plans and parked work that are not part of the running build: the Petoi AI Head ([`planned/ai-head/`](planned/ai-head/README.md)), the robot-arm
module, place memory, reflection, a BiBoard firmware fork, hardware-gated and robustness backlogs, and the behavior ideas. See [`planned/README.md`](planned/README.md).

## `archive/` — closed work, kept for the record

Closed campaigns (v2.2, V3, the 2026-09 sim logs), finished phase write-ups, the old narrative history, and their data. Nothing here describes the current build.
See [`archive/README.md`](archive/README.md).
