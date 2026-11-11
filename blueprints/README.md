# Build record (blueprints)

The physical build record for G2: how the hardware was assembled and wired, with enough detail to reproduce it. Specs, research and the current parts list are in [`../docs/hardware/`](../docs/hardware/README.md) (start with [`as-built.md`](../docs/hardware/as-built.md)); this folder is the how. The pages carry the renders and diagrams of the build, and each links to the 3D viewer and the print files.

- [`assembly-sequence.md`](assembly-sequence.md): Start here. The build in order, each step linking to its record.
- [`wiring.md`](wiring.md): Part 1 the PiSugar to Pi to BiBoard stack (exact pins, power-on checklist), Part 2 everything wired into the Pi (40-pin header map, wire map, mic and amp, the AI head), with the wire diagrams.
- [`mounting.md`](mounting.md): The case: the Bittle X platform and Pi add-on pod (installed), where the Pi stack, camera, speaker and microphone sit, the pins, the measurements a mount must respect, the open items, and the renders of the pod and the platform.
- [`paws-and-wide-shoulders.md`](paws-and-wide-shoulders.md): The printed 0.2 in wide shoulder parts and the hinged clip-on paws (printing, not yet installed): design, simulator evidence, install checklist, what is unknown.
- [`calibration.md`](calibration.md): The servo calibration procedure (bracket alignment per leg, `kbalance` verification) and what to redo after a servo replacement.

Bittle X, the camera module and the Pi + PiSugar stack are assembled and in use. What works and what is open: [`../docs/STATUS.md`](../docs/STATUS.md).
