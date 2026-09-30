# Servo calibration (post-reflash), 2026-09-29

Real joint calibration on G2's BiBoard, done after the firmware reflash
wiped the previous coarse/factory calibration (see
`docs/hardware/petoi-firmware-reference.md` for the reflash itself).

## Procedure used

1. Powered G2 on in its normal bootup posture, USB-connected to the dev
   Mac (`/dev/cu.usbmodem5AA90271591`).
2. Opened the Petoi Desktop App (v1.2.9), selected Product "Bittle X",
   Board "BiBoard_V1_0", connected on that port, opened the **Joint
   Calibrator**.
3. Used the L-shaped calibration bracket/ruler (shipped in the kit) one
   leg at a time: placed it against each leg per Petoi's diagram, nudged
   that leg's servo angle in the app until the leg's reference marks
   lined up with the ruler's openings.
4. Saved calibration in the app once all 8 leg joints were aligned.

## Finding: the bracket step doesn't put all four feet on the ground, and that's correct

While aligning each leg to the bracket, the two front feet sat slightly
off the ground while the two back feet touched, even though the
commanded angle read identically front-to-back. This looked like a
possible problem but isn't one — confirmed from Petoi's own
documentation:

- The Bittle calibration doc describes the bracket step as aligning each
  leg's reference marks to the ruler's openings — a per-leg, frame-
  relative check, nothing about the floor.
- The joint-calibration doc states the calib-posture target explicitly:
  legs sit "perpendicular to their nearby references **on the body
  frame**," not perpendicular to the ground.

Bittle X's front and rear hip mounts sit at slightly different points on
the chassis, so identical frame-relative joint angles don't have to put
all four feet at exactly the same height — a small front/back foot-height
difference during the bracket step is expected geometry, not a
miscalibration. The real invariant to check during the bracket step is
**left-right symmetry** (front-left vs front-right, back-left vs
back-right), not front-to-back floor contact.

## Verification: `kbalance`

The actual end-to-end confirmation used is the `kbalance` skill — it
commands all four legs to one shared, symmetric reference angle and
should show all four feet landing level with each other. Sent twice after
saving calibration
(`python -m pi_pipeline.link.check_serial send kbalance`, replies `G` then
`balance` — just different firmware ack text, not a functional
difference): **all four feet came down level both times.** Calibration
confirmed good.

This is the same pose used earlier (2026-09-28, pre-reflash) to rule out
a per-leg zero-point offset while chasing the `vtF` stumble — see
`project_hardware_arrived` memory / `docs/project-plan.md` Phase 4 for
that investigation.
