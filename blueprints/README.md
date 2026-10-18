# Build record (blueprints)

The physical build record for G2: how the hardware was assembled and wired, with enough detail to reproduce it. Specs, research and the current parts list are in [`../docs/hardware/`](../docs/hardware/README.md) (start with [`as-built.md`](../docs/hardware/as-built.md)); this folder is the how.

| | |
|---|---|
| [`assembly-sequence.md`](assembly-sequence.md) | **Start here.** The build in order, each step linking to its record. |
| [`wiring/g2-wiring-guide.html`](wiring/g2-wiring-guide.html) | The wiring reference in one page: Part 1 PiSugar to Pi to BiBoard (stack, exact pins, power-on checklist), Part 2 everything wired into the Pi (40-pin header map, wire map, mic and amp, the AI head). Open it in a browser. A printable PDF is [`wiring/g2-wiring-guide.pdf`](wiring/g2-wiring-guide.pdf); the page is also published as a [live Artifact](https://claude.ai/artifact/EYPDHBAgbLyTk9qSvaP6rB). |
| [`mounting.md`](mounting.md) | How the Pi stack, camera, speaker and microphone are attached (interim mount; sections still to be recorded), the measurements a mount must respect, and the case design now in progress. |
| [`calibration.md`](calibration.md) | The servo calibration procedure (bracket alignment per leg, `kbalance` verification) and what to redo after a servo replacement. |

The dated build logs (the Pi, PiSugar and BiBoard connection; the microphone and speaker) are in [`../docs/hardware/build-logs/`](../docs/hardware/README.md#build-logs).

Bittle X, the camera module and the Pi + PiSugar stack are assembled and in use. What works and what is open: [`../docs/STATUS.md`](../docs/STATUS.md). The first mounting research (an abandoned clip design) is archived in [`../docs/archive/mounting-research-2026-09.md`](../docs/archive/mounting-research-2026-09.md).
