# docs/build/

The physical assembly record for G2's hardware: wiring, soldering, mounting,
calibration, and the real measurements taken along the way — as opposed to
`docs/hardware/`, which holds specs and pre-build research (why a part or
approach was chosen).

Each entry documents one build step with enough detail to reproduce it:
what was connected to what, exact settings/commands used, real photos or
measurements, and anything that differed from the original plan.

## Entries

| | |
|---|---|
| [`biboard-pi-connector.md`](biboard-pi-connector.md) | Pi + PiSugar + BiBoard: the wiring build manual (steps 1-4, annotated real board photos) plus the standoff clip mounting investigation, mm-accurate installation diagram, and the modified-clip STLs (`cad/`) — kept together as one build reference rather than split from the pre-build research, since it's what gets used at the bench. |
| [`calibration.md`](calibration.md) | Real servo calibration procedure (bracket alignment per leg + `kbalance` verification), done post-firmware-reflash 2026-09-29 — includes the finding that the bracket step targets frame-relative perpendicularity, not floor contact. |

Bittle X and the camera module have arrived and are assembled (2026-09-28/29):
frame assembled, camera mounted + connected to BiBoard's G1 Grove socket
(tight fit at the head), BiBoard's 5-pin Pi header soldered, servo
calibration done for real and `kbalance`-verified post-reflash (see
`calibration.md`). Still open: the actual Pi↔BiBoard jumper wiring
(Step 3). Step 5 (Pi+PiSugar mount) has an interim solution — PiSugar's
own official case velcroed to the outside of a modified back cover, not
enclosed inside it (the case is thicker than the cover's internal cavity)
— not the final mount; see [`biboard-pi-connector.md`](biboard-pi-connector.md).
