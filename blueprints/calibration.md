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
Petoi's assembly guide.

## After the front-left shoulder servo was replaced

The front-left shoulder servo (servo 8) was replaced on 2026-10-06 and the
joint calibration was redone afterwards; the date of the second calibration was
not recorded. The walking evidence for the swap (drift fell from about 140 to
about 40 degrees per 12.5 s). The walk logs record it.
Re-run the procedure above and the `kbalance` check after any servo
replacement.

## Offsets before the arm firmware

Read from the Petoi Desktop App's Joint Calibrator on the stock Bittle X firmware, with the AI head build, just before the swap to the Petoi robot arm and the Bittle
X+Arm reflash (a reflash can reset the calibration). The arm's servo cables were unplugged from the BiBoard for the reading. Petoi's labels: "Arm" is the upper leg
joint, "Shoulder" (4 to 7) is unused on Bittle.

- **0 head pan**: Offset: 0; Joint: 2 tail pan; Offset: 0
- **1 head tilt**: Offset: 0; Joint: 3 (N/A); Offset: 0
- **8 left front upper leg**: Offset: -1; Joint: 12 left front knee; Offset: 2
- **9 right front upper leg**: Offset: 0; Joint: 13 right front knee; Offset: 5
- **10 right back upper leg**: Offset: 5; Joint: 14 right back knee; Offset: -4
- **11 left back upper leg**: Offset: -6; Joint: 15 left back knee; Offset: 4
- **4 to 7 shoulders**: Offset: 0

If the arm firmware's calibration starts from zero, these are the leg values to enter before the `c-2` claw calibration; the calibration pose then shows whether
any leg needs a touch-up.

## Bittle X+Arm calibration (2026-10-24, about 10:10 PM)

After the Petoi robot arm replaced the AI head and the BiBoard was flashed with Petoi's Bittle X+Arm firmware (software B10_260527, written with the Desktop App's
own esptool command and files; the app's port list could not show the BiBoard's `cu.usbmodem` port). The flash kept the stored calibration: no first-boot
questions, and every leg offset above was unchanged. In the arm build the calibrator names joints 0 to 2 Claw Pan (the neck servo), Claw Lift and Claw Open.

- **0 claw pan**: -14
- **1 claw lift**: 0
- **2 claw open**: 1 (Auto)
- **8 to 15 legs**: as in the table above

## After the legs were removed and refitted

The legs came off for the wide-shoulder and paw fitting, which meant unplugging their servo cables. After refitting, the calibration pose looked right on all four
legs, but Stand folded both right legs up toward the body and jammed them against the frame, while the left legs stood normally.

Cause: on both right legs the upper-leg and knee cables were plugged into each other's sockets (9 and 13 swapped on the front right, 10 and 14 on the back right).
The calibration pose hides this because it puts every joint at 0 degrees, so a swapped pair still looks correct. Stand sends different angles to the upper leg and
the knee, so each right servo got the other one's angle. With gyro balance off, the stand pose measured a 31 degree roll even though the commanded angles were
symmetric left to right.

How it was found: G2 on his feet, one joint moved at a time (`m<socket> <angle>`, 10 degrees for 1.5 s, then back) in the order 8, 12, 9, 13, 11, 15, 10, 14.
On the left the upper leg moved first and then the knee. On the right the knee moved first and then the upper leg.

Fix: swap the cables back (9 and 13, 10 and 14), then redo the right legs in the Joint Calibrator, because offsets entered while the cables were swapped went to the
wrong servos.

Socket map to check after any leg comes off:

- **Front left**: Upper leg socket: 8; Knee socket: 12
- **Front right**: Upper leg socket: 9; Knee socket: 13
- **Back right**: Upper leg socket: 10; Knee socket: 14
- **Back left**: Upper leg socket: 11; Knee socket: 15

If the calibration pose looks right but Stand does not, check the cables before changing any offset.
