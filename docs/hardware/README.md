# Hardware

Specs, reference and research for the hardware that is installed. The physical assembly record (wiring, soldering, mounting, calibration, build logs) is in [`../../blueprints/`](../../blueprints/README.md).

| | |
|---|---|
| [`as-built.md`](as-built.md) | **Start here.** What G2 is made of now: parts, connections, mass and balance, known characteristics. |
| [`specs.md`](specs.md) | Vendor-doc specs for every part + "why it matters". |
| [`parts-and-decisions.md`](parts-and-decisions.md) | The finalized parts list, resolved/open hardware questions, power-awareness plan. |
| [`diagnostics.md`](diagnostics.md) | Black-box logging + watchdog design (Phase 1 + non-HW Phase 2 built). |
| [`servo-thermal.md`](servo-thermal.md) | Servo overheat risk + the layered mitigation (Layer 1+2 built). |
| [`pi-power.md`](pi-power.md) | Powering the Pi (PiSugar S; BiBoard data-only) + power-management levers. |
| [`self-righting.md`](self-righting.md) | Bittle's built-in self-right — limited; no BiBoard-V1 IR trigger. |
| [`petoi-firmware-reference.md`](petoi-firmware-reference.md) | How OpenCat gaits are structured, Confirmed-from-source serial tokens, IMU thresholds, skill format. |
| [`petoi-skills-survey.md`](petoi-skills-survey.md) | Which OpenCat built-in skills are worth pulling into G2. |
| [`calibration-and-bringup-research.md`](calibration-and-bringup-research.md) | Petoi's official calibration/first-power-on docs, cross-checked against our bring-up plan. |
