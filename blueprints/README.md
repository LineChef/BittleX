# blueprints/

The physical build record for G2's hardware and the wiring references that go
with it: wiring, soldering, mounting, calibration, and the real measurements
taken along the way — as opposed to `docs/hardware/`, which holds specs and
pre-build research (why a part or approach was chosen). Moved out from under
`docs/` to its own top-level folder so it's easy to find on its own.

Each entry documents one build step with enough detail to reproduce it:
what was connected to what, exact settings/commands used, real photos or
measurements, and anything that differed from the original plan.

## Entries

| | |
|---|---|
| [`wiring/g2-wiring-guide.html`](wiring/g2-wiring-guide.html) | The wiring reference in one page: Part 1 PiSugar to Pi to BiBoard (stack diagram, exact pins, power-on checklist), Part 2 everything wired into the Pi (40-pin header map, color-coded wire map, mic and amp, the AI head on BiBoard G1). Open it directly in a browser. Also published as a [live Artifact](https://claude.ai/artifact/EYPDHBAgbLyTk9qSvaP6rB) with the same content. |
| [`mounting.md`](mounting.md) | How the Pi + PiSugar stack mounts on the frame: the standoff clip and its history, screws, the mount investigation and decision, assembled-stack diagrams, and the modified-clip STLs (`cad/`). |
| [`calibration.md`](calibration.md) | Real servo calibration procedure (bracket alignment per leg + `kbalance` verification), done post-firmware-reflash 2026-09-29 — includes the finding that the bracket step targets frame-relative perpendicularity, not floor contact. |

Bittle X, the camera module and the Pi + PiSugar stack are assembled and in use: the Pi
talks to BiBoard over its 5-pin header, the mic and amp are wired to the Pi's header, and
servo calibration is done and `kbalance`-verified (see `calibration.md`). Current hardware
status is in [`docs/STATUS.md`](../docs/STATUS.md). The Pi + PiSugar mount is an interim
solution: PiSugar's own official case is velcroed to the outside of a modified back cover,
not enclosed inside it (the case is thicker than the cover's internal cavity). It is not
the final mount; see [`mounting.md`](mounting.md).
