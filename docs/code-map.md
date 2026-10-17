# Code map: the docs and the packages

Where each part of the code is documented. Each package has its own README next to the code; the docs pages explain how to use and operate the part. How the pieces fit: [`architecture.md`](architecture.md).

## `pi_pipeline/`: runs on the Pi

| Package | Does | Code README | Docs |
|---|---|---|---|
| `voice/` | Wake word, speech to text, Claude, text to speech; local commands; sounds | [`voice/README.md`](../pi_pipeline/voice/README.md) | [`guides/voice-commands.md`](guides/voice-commands.md), [`guides/settings-switches.md`](guides/settings-switches.md), [`guides/swappable-llm.md`](guides/swappable-llm.md), [`guides/models.md`](guides/models.md) |
| `personality/` | Traits that shape the prompt, behavior and cues | [`personality/README.md`](../pi_pipeline/personality/README.md) | [`how-it-works.md`](how-it-works.md) |
| `memory/` | Exchange log, facts, consolidation, review UI | [`memory/README.md`](../pi_pipeline/memory/README.md) | [`plan-detail/phase9-memory.md`](plan-detail/phase9-memory.md) |
| `reflection/` | Session recaps and reflection notes | [`reflection/README.md`](../pi_pipeline/reflection/README.md) | [`planned/reflection-plan.md`](planned/reflection-plan.md) |
| `behavior/` | The driver, exploration, idle, sleep, wall avoidance | [`behavior/README.md`](../pi_pipeline/behavior/README.md) | [`guides/exploration-mode.md`](guides/exploration-mode.md) |
| `vision/` | Camera, detections, pictures, wall distance, recognition | [`vision/README.md`](../pi_pipeline/vision/README.md) | [`vision/README.md`](vision/README.md), [`vision/picture-library.md`](vision/picture-library.md) |
| `gait/` | The 80 Hz loop, steering, stand-up, guards, tools | [`gait/README.md`](../pi_pipeline/gait/README.md) | [`guides/gait-deployment.md`](guides/gait-deployment.md), [`rl/walking-policy.md`](rl/walking-policy.md) |
| `link/` | The serial link to the BiBoard | [`link/README.md`](../pi_pipeline/link/README.md) | [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md) |
| `app/` | The whole robot as one program | [`app/README.md`](../pi_pipeline/app/README.md) | [`guides/operating-g2.md`](guides/operating-g2.md) |
| `diag/` | Event log, ring buffer, watchdog, crash reports | [`diag/README.md`](../pi_pipeline/diag/README.md) | [`hardware/diagnostics.md`](hardware/diagnostics.md) |
| `power/` | Pi power levers, battery watch, runtime, sleep | [`power/README.md`](../pi_pipeline/power/README.md) | [`hardware/pi-power.md`](hardware/pi-power.md) |
| `telemetry/` | Automatic walk logs, floors, epochs, labels | [`telemetry/README.md`](../pi_pipeline/telemetry/README.md) | [`rl/real-data-pipeline.md`](rl/real-data-pipeline.md) |
| `head/` | MCP tool server for the AI Head (not in the build) | [`head/README.md`](../pi_pipeline/head/README.md) | [`planned/ai-head/`](planned/ai-head/README.md) |
| `util/` | Disk warning, log tidy, worker supervisor | [`util/README.md`](../pi_pipeline/util/README.md) | |

Package-level overview, setup and the list of modules built but not yet wired in: [`../pi_pipeline/README.md`](../pi_pipeline/README.md).

## Other code

| Folder | Does | Docs |
|---|---|---|
| `rl_training/opencat-gym/` | Simulation training, benchmarks and export of the walking policy | [`rl/README.md`](rl/README.md), [`rl/training-upgrade-2026-10.md`](rl/training-upgrade-2026-10.md) |
| `tools/` | Docs checks, Mac-to-Pi operations, real-data pipeline, vision dataset tools, git hooks | [`../tools/README.md`](../tools/README.md), [`guides/shell-helpers.md`](guides/shell-helpers.md) |
| `blueprints/` | The physical build: assembly order, wiring, mounting, calibration | [`../blueprints/README.md`](../blueprints/README.md) |
