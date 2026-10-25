# Servo calibration (post-reflash), 2026-09-29

Real joint calibration on G2's BiBoard, done after the firmware reflash
wiped the previous coarse/factory calibration (see
[`docs/hardware/petoi-firmware-reference.md`](../docs/hardware/petoi-firmware-reference.md) for the reflash itself).

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
a per-leg zero-point offset while chasing the `vtF` stumble; see
[`../docs/plan-detail/phase4-hardware-assembly.md`](../docs/plan-detail/phase4-hardware-assembly.md)
for that investigation.

## After the front-left shoulder servo was replaced (2026-10-06)

The front-left shoulder servo (servo 8) was replaced on 2026-10-06 and the
joint calibration was redone afterwards; the date of the second calibration was
not recorded. The walking evidence for the swap (drift fell from about 140 to
about 40 degrees per 12.5 s) is in [`../docs/rl/real-walk-log.md`](../docs/rl/real-walk-log.md).
Re-run the procedure above and the `kbalance` check after any servo
replacement.

## Offsets before the arm firmware (2026-10-24)

Read from the Petoi Desktop App's Joint Calibrator on the stock Bittle X firmware, with the AI head build, just before the swap to the Petoi robot arm and the Bittle
X+Arm reflash (a reflash can reset the calibration). The arm's servo cables were unplugged from the BiBoard for the reading. Petoi's labels: "Arm" is the upper leg
joint, "Shoulder" (4 to 7) is unused on Bittle.

| Joint | Offset | | Joint | Offset |
|---|---|---|---|---|
| 0 head pan | 0 | | 2 tail pan | 0 |
| 1 head tilt | 0 | | 3 (N/A) | 0 |
| 8 left front upper leg | -1 | | 12 left front knee | 2 |
| 9 right front upper leg | 0 | | 13 right front knee | 5 |
| 10 right back upper leg | 5 | | 14 right back knee | -4 |
| 11 left back upper leg | -6 | | 15 left back knee | 4 |
| 4 to 7 shoulders | 0 | | | |

If the arm firmware's calibration starts from zero, these are the leg values to enter before the `c-2` claw calibration; the calibration pose then shows whether
any leg needs a touch-up.

## Bittle X+Arm calibration (2026-10-24, about 10:10 PM)

After the Petoi robot arm replaced the AI head and the BiBoard was flashed with Petoi's Bittle X+Arm firmware (software B10_260527, written with the Desktop App's
own esptool command and files; the app's port list could not show the BiBoard's `cu.usbmodem` port). The flash kept the stored calibration: no first-boot
questions, and every leg offset above was unchanged. In the arm build the calibrator names joints 0 to 2 Claw Pan (the neck servo), Claw Lift and Claw Open.

| Joint | Offset |
|---|---|
| 0 claw pan | -14 |
| 1 claw lift | 0 |
| 2 claw open | 1 (Auto) |
| 8 to 15 legs | as in the table above |
