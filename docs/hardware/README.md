# Hardware

Specs, reference and research for the hardware that is installed. The physical assembly record (wiring, soldering, mounting, calibration) is in [`../../blueprints/`](../../blueprints/README.md).

- [`as-built.md`](as-built.md): **Start here.** What G2 is made of now: parts, connections, mass and balance, known characteristics.
- [`specs.md`](specs.md): Vendor-doc specs for every part + "why it matters".
- [Bittle X platform and Pi add-on](https://beetlebugorg.github.io/bittlex/): The case design on G2: project page, 3D viewer, print files and build guide (a separate project; the record is [`../../blueprints/mounting.md`](../../blueprints/mounting.md)).

### Systems

- [`pi-power.md`](pi-power.md): Powering the Pi (PiSugar S; BiBoard data-only) + power-management levers.
- [`servo-thermal.md`](servo-thermal.md): Servo overheat risk + the layered mitigation (Layer 1+2 built).
- [`diagnostics.md`](diagnostics.md): Black-box logging + watchdog design (Phase 1 + non-HW Phase 2 built).
- [`self-righting.md`](self-righting.md): Bittle's built-in self-right — limited; no BiBoard-V1 IR trigger.

### Reference

- [`petoi-firmware-reference.md`](petoi-firmware-reference.md): How OpenCat gaits are structured, Confirmed-from-source serial tokens, IMU thresholds, skill format.

### Build logs

