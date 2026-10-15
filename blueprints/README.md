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
| [`wiring/g2-wiring-guide.html`](wiring/g2-wiring-guide.html) | The wiring reference in one page: Part 1 PiSugar to Pi to BiBoard (stack diagram, exact pins, power-on checklist), Part 2 everything wired into the Pi (40-pin header map, color-coded wire map, mic and amp, the AI head on BiBoard G1). Open it directly in a browser. |
| [`mounting.md`](mounting.md) | How the Pi + PiSugar stack mounts on the frame: the standoff clip and its history, screws, the mount investigation and decision, assembled-stack diagrams, and the modified-clip STLs (`cad/`). |
| [`calibration.md`](calibration.md) | Real servo calibration procedure (bracket alignment per leg + `kbalance` verification), done post-firmware-reflash 2026-09-29 — includes the finding that the bracket step targets frame-relative perpendicularity, not floor contact. |

Bittle X and the camera module have arrived and are assembled (2026-09-28/29):
frame assembled, camera mounted + connected to BiBoard's G1 Grove socket
(tight fit at the head), BiBoard's 5-pin Pi header soldered, servo
calibration done for real and `kbalance`-verified post-reflash (see
`calibration.md`). Still open: the actual Pi↔BiBoard jumper wiring
(Step 3). Step 5 (Pi+PiSugar mount) has an interim solution — PiSugar's
own official case velcroed to the outside of a modified back cover, not
enclosed inside it (the case is thicker than the cover's internal cavity)
— not the final mount; see [`mounting.md`](mounting.md).
