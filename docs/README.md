# docs/

| Start here | |
|---|---|
| [`project-plan.md`](project-plan.md) | The living roadmap and decision log — read before starting work in any area. |
| [`how-it-works.md`](how-it-works.md) | Plain-language tour of all five parts (walking, voice, memory, vision, link). |
| [`hardware-readiness.md`](hardware-readiness.md) | State of everything before hardware arrives + the day-1 checklist. |
| [`behavior-ideas.md`](behavior-ideas.md) | Backlog of behaviors to explore (IDs B1…) — the "what should we work on next" list. |

## `reference/` — how-to

| | |
|---|---|
| [`commands.md`](reference/commands.md) | Every runnable command, full step sequences. |
| [`cheatsheet.md`](reference/cheatsheet.md) | Short curated quick-reference. |
| [`automated-testing-loop.md`](reference/automated-testing-loop.md) | Runbook for unattended RL reward iteration. |

## `research/` — external research notes

| | |
|---|---|
| [`hardware-specs.md`](research/hardware-specs.md) | Vendor-doc specs for every part + "why it matters" (IMU has no magnetometer, vision module can't stream frames + detections at once, PiSugar S has no battery readout, …). |
| [`pi-power.md`](research/pi-power.md) | Powering the Pi (PiSugar S; wire BiBoard data-only). |
| [`self-righting-research.md`](research/self-righting-research.md) | Bittle's built-in self-right — limited; no BiBoard-V1 IR trigger. |

## `rl-runs/` — gait training history

| | |
|---|---|
| [`gait-benchmark.md`](rl-runs/gait-benchmark.md) | Learned vs. scripted `wkF` head-to-head. |
| `auto-iteration-log*.md` | Per-round logs — Run 2–7, the level-ground loop, the resid line. |
| `auto-iteration-report-*.md` | Wrap-up reports for those loops. |
