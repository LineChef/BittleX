# Hardware

Specs, reference and research for the hardware that is installed. The physical assembly record (wiring, soldering, mounting, calibration) is in [`../../blueprints/`](../../blueprints/README.md).

| | |
|---|---|
| [`as-built.md`](as-built.md) | **Start here.** What G2 is made of now: parts, connections, mass and balance, known characteristics. |
| [`specs.md`](specs.md) | Vendor-doc specs for every part + "why it matters". |
| [Bittle X platform and Pi add-on](https://beetlebugorg.github.io/bittlex/) | The case design on G2 since 2026-10-17: project page, 3D viewer, print files and build guide (a separate project; the record is [`../../blueprints/mounting.md`](../../blueprints/mounting.md)). |
| [`parts-and-decisions.md`](parts-and-decisions.md) | The finalized parts list, resolved/open hardware questions, power-awareness plan. |

### Systems

| | |
|---|---|
| [`pi-power.md`](pi-power.md) | Powering the Pi (PiSugar S; BiBoard data-only) + power-management levers. |
| [`servo-thermal.md`](servo-thermal.md) | Servo overheat risk + the layered mitigation (Layer 1+2 built). |
| [`diagnostics.md`](diagnostics.md) | Black-box logging + watchdog design (Phase 1 + non-HW Phase 2 built). |
| [`self-righting.md`](self-righting.md) | Bittle's built-in self-right — limited; no BiBoard-V1 IR trigger. |

### Reference

| | |
|---|---|
| [`petoi-firmware-reference.md`](petoi-firmware-reference.md) | How OpenCat gaits are structured, Confirmed-from-source serial tokens, IMU thresholds, skill format. |
| [`petoi-skills-survey.md`](petoi-skills-survey.md) | Which OpenCat built-in skills are worth pulling into G2. |
| [`calibration-and-bringup-research.md`](calibration-and-bringup-research.md) | Petoi's official calibration/first-power-on docs, cross-checked against the bring-up plan. |

### Build logs

| | |
|---|---|
| [`build-logs/pi-biboard-build-notes.md`](build-logs/pi-biboard-build-notes.md) | Step-by-step history of connecting PiSugar, the Pi Zero 2 W and BiBoard. |
| [`build-logs/i2s-audio-build-log.md`](build-logs/i2s-audio-build-log.md) | The microphone and speaker build: connectors, header pins, the BCLK/LRCLK splice, bring-up, the exact overlay. |
