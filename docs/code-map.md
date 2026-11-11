---
audience: contributor
kind: reference
---

# Code map: the docs and the packages

Where each part of the code is documented. Each package has its own README next to the code; the docs pages explain how to use and operate the part. How the pieces fit: [`architecture.md`](architecture.md).

`pi_pipeline/`: runs on the Pi
------------------------------

- `voice/`: Does: Wake word, speech to text, Claude, text to speech; local commands; sounds; Code README: [`voice/README.md`](../pi_pipeline/voice/README.md); Docs: [`guides/voice-commands.md`](guides/voice-commands.md), [`guides/settings-switches.md`](guides/settings-switches.md), [`guides/swappable-llm.md`](guides/swappable-llm.md), [`guides/models.md`](guides/models.md)
- `personality/`: Does: Traits that shape the prompt, behavior and cues; Code README: [`personality/README.md`](../pi_pipeline/personality/README.md); Docs: [`how-it-works.md`](how-it-works.md)
- `memory/`: Does: Exchange log, facts, consolidation, review UI; Code README: [`memory/README.md`](../pi_pipeline/memory/README.md); Docs: [`how-it-works.md`](how-it-works.md)
- `reflection/`: Does: Session recaps and reflection notes; Code README: [`reflection/README.md`](../pi_pipeline/reflection/README.md)
- `goals/`: Does: Goal sessions: attempts judged on the Pi to change the next, journal, spoken suggestions, report; Code README: [`goals/README.md`](../pi_pipeline/goals/README.md); Docs: [`guides/goals.md`](guides/goals.md)
- `behavior/`: Does: The driver, exploration, idle, sleep, wall avoidance; Code README: [`behavior/README.md`](../pi_pipeline/behavior/README.md); Docs: [`guides/exploration-mode.md`](guides/exploration-mode.md)
- `vision/`: Does: Camera, detections, pictures, wall distance, recognition; Code README: [`vision/README.md`](../pi_pipeline/vision/README.md); Docs: [`vision/README.md`](vision/README.md), [`vision/picture-library.md`](vision/picture-library.md)
- `gait/`: Does: The 80 Hz loop, steering, stand-up, guards, tools; Code README: [`gait/README.md`](../pi_pipeline/gait/README.md); Docs: [`guides/gait-deployment.md`](guides/gait-deployment.md), [`rl/walking-policy.md`](rl/walking-policy.md)
- `link/`: Does: The serial link to the BiBoard; Code README: [`link/README.md`](../pi_pipeline/link/README.md); Docs: [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md)
- `app/`: Does: The whole robot as one program; Code README: [`app/README.md`](../pi_pipeline/app/README.md); Docs: [`guides/operating-g2.md`](guides/operating-g2.md)
- `diag/`: Does: Event log, ring buffer, watchdog, crash reports; Code README: [`diag/README.md`](../pi_pipeline/diag/README.md); Docs: [`hardware/diagnostics.md`](hardware/diagnostics.md)
- `power/`: Does: Pi power levers, battery watch, runtime, sleep; Code README: [`power/README.md`](../pi_pipeline/power/README.md); Docs: [`hardware/pi-power.md`](hardware/pi-power.md)
- `telemetry/`: Does: Automatic walk logs, floors, epochs, labels; Code README: [`telemetry/README.md`](../pi_pipeline/telemetry/README.md); Docs: [`rl/real-data-pipeline.md`](rl/real-data-pipeline.md)
- `head/`: Does: MCP tool server for the AI Head (not in the build); Code README: [`head/README.md`](../pi_pipeline/head/README.md); Docs: [`guides/attachments.md`](guides/attachments.md)
- `util/`: Does: Disk warning, log tidy, worker supervisor; Code README: [`util/README.md`](../pi_pipeline/util/README.md)

Package-level overview, setup and the list of modules built but not yet wired in: [`../pi_pipeline/README.md`](../pi_pipeline/README.md).

Other code
----------

- `rl_training/opencat-gym/`: Does: Simulation training, benchmarks and export of the walking policy; Docs: [`rl/README.md`](rl/README.md)
- `tools/`: Does: Docs checks, Mac-to-Pi operations, real-data pipeline, vision dataset tools, git hooks; Docs: [`../tools/README.md`](../tools/README.md), [`guides/shell-helpers.md`](guides/shell-helpers.md)
- `blueprints/`: Does: The physical build: assembly order, wiring, mounting, calibration; Docs: [`../blueprints/README.md`](../blueprints/README.md)
