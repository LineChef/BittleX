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

Everything else is not yet started — Bittle X and the camera module haven't
arrived. Next entries will cover Pi provisioning, servo calibration, and the
camera mount.
