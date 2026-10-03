# Forking the firmware — what it would unblock, and what it would cost

Reference for the "should we fork?" question (2026-10-03). The standing decision is **no fork** — the Pi stays an application layer on stock
firmware, and a fork is allowed only narrowly and later, if a capability truly can't be done Pi-side ([`../project-plan.md`](../project-plan.md)).
This page collects the evidence for revisiting that. Facts below come from our firmware notes ([`../hardware/petoi-firmware-reference.md`](../hardware/petoi-firmware-reference.md)),
the walk log ([`../rl/real-walk-log.md`](../rl/real-walk-log.md)) and a read of OpenCatEsp32 `main`; items marked *unverified* have not been tested.

## Which fork

| Fork | Licence | Status |
|---|---|---|
| **OpenCatEsp32** — the BiBoard firmware that runs G2's servos, IMU and serial protocol | MIT | public; Petoi ships frequent releases (G2 runs B10_260527) |
| **The AI Head's firmware** — XiaoZhi-based, on the head's ESP32-C3 | upstream xiaozhi-esp32 is MIT; Petoi's head build is not released yet | board definition and pin map unknown until Petoi publishes |

Both are separable decisions. Most of the list below needs only the first.

## What a BiBoard fork could fix or unblock

| # | Problem today | Today's workaround | What a patch would do | Expected value |
|---|---|---|---|---|
| 1 | **Camera mode deletes the IMU task** (`groveVisionSetup()`), persists across reboots; `Xc` does not restore it | Camera stays on the Pi's USB; only an erase + reflash recovers a camera-mode BiBoard | Recreate the IMU task when the camera is disabled (and optionally don't persist the flag) | High if the Pi goes away or the camera moves to the BiBoard; none while the camera stays on the Pi. Small patch |
| 2 | **Reflexes only fire while standing.** Push/lift/knock are scripted for a stationary robot; none fire mid-walk | None; the Pi's fall guard and thermal guard sit above the firmware | Allow the push reflex during gaits, or expose a hook | Medium. Pi-side reimplementation is possible but only at the 5 Hz IMU rate |
| 3 | **Firmware auto-recover vs the Pi's `RecoveryFSM`.** Flip → `rc` runs once and repeats with no retry/give-up logic | Keep the Pi's recovery off or accept both acting | A flag or handshake to hand recovery to the Pi, plus a retry limit | Medium. Removes a known conflict (flagged 2026-09-28) |
| 4 | **IMU is capped at 5 Hz and carries no angular rate.** `print6Axis()` returns early inside `PRINT6AXIS_MIN_INTERVAL` (200 ms); the raw-gyro print is dead code | The Pi differences consecutive frames; the policy is trained to expect 5 Hz | Print faster and add gyro rates | **Lower than it looks.** Sim says 5 Hz costs about nothing, and the earlier "80 Hz" lineage came from a stale-firmware misreading. Would force a retrain, and 115200 baud limits the stream. *Unverified on hardware* |
| 5 | **Servo position feedback only works over USB**, stops on any other command, ~112 ms per read (~9 Hz), `f` echoed only on one build | Foot-probing ideas (B13) done slowly over a cable | Expose feedback on the Pi's UART and faster or batched | Medium for the climb/probe skills and servo-fault diagnosis (e.g. the FL shoulder). Rate may be a servo-bus limit; *unverified* |
| 6 | **Joint-command timing.** `i` walks with ~55 ms lag; `m` doesn't walk | The sim models the lag; the policy sends every 3rd tick | A batched, fixed-latency joint-target command | Medium: narrows the sim-to-real gap for any learned gait |
| 7 | **Camera behaviors are generic.** The Grove Vision path in `camera.h` has no per-class logic | Pi-side detection handling | Class-aware reactions on the BiBoard | Low if the Pi stays |
| 8 | **UART2 is shared** by the Pi header, the voice module's socket and the head | Single master (the Pi) | A second command port, or arbitration for two masters | Only matters if the head controls motion |
| 9 | **Module state persists in NVS.** An erase resets the voice module to Chinese, camera mode re-enables on boot | Documented post-reflash steps (`XAa/XAb/XAc`) | Build correct defaults in | Low, convenience |
| 10 | **Demo reactions** (ultrasonic/IR modules) are random wander-style behaviors | Not installed | Replace with ledge/leash aware logic | Low; no sensors owned |

## What a head-firmware fork could fix (after Petoi releases it)

| Problem | What a patch would do |
|---|---|
| The Pi can't use the head's mic or speaker | Expose audio to the Pi (stream or I2S), so the head replaces the external mic and speaker |
| Cloud backend is Petoi's/XiaoZhi's | Point the head at a backend we control (Claude, our memory and personality) |
| "What do you see?" has no data | Add a tool that returns the Vision Module's detections |
| UART conflict with the Pi | Move motion commands to a different port, or turn them off |

## What a fork would not fix

The faulty front-left shoulder servo, carpet failures, payload shift on the mounts, the unproven learned-vs-scripted comparison (H1), the camera
model's frozen-firmware limits, and any sim-to-real gap not caused by the firmware's timing.

## Pros

- **Removes real firmware ceilings** (items 1–6) that no Pi-side code can get around.
- **MIT licence;** the code is public and already read by us (reaction thresholds, camera and module code are all understood).
- **Enables the Pi-less path** (item 1 plus the head) as a real option, not just a thought experiment.
- **Narrow patches are small:** most items are a few functions, and Petoi's own bugs (camera/IMU, buggy IR module) can be fixed rather than worked around.
- **Opens head integration** if Petoi's firmware ships: a backend we control instead of a cloud we don't.

## Cons

- **Maintenance:** Petoi releases often (we've already gone B10_251121 → B10_260527). Every upstream release means a rebase, retest and reflash.
- **Tooling:** Petoi's Desktop App uploads only official builds with the right partition layout. A fork needs an Arduino/PlatformIO or esptool toolchain
  we haven't set up, plus a repeatable way to reproduce Petoi's four-file flash. *Unverified: build time and effort.*
- **Risk to the robot:** firmware controls the servos and balance. A bad patch can break gyro balance, calibration or the reflexes G2 relies on today.
  BOOT-button recovery exists, but an erase wipes calibration and module flags (recalibrate, `gc`, voice fix).
- **Coupling:** IMU or timing changes invalidate the deployed policy and push us into another sim retrain and hardware validation cycle.
- **Many wins are unproven:** e.g. a faster IMU has no hardware evidence of helping; the policy comparison (H1) is still open. Forking before that adds work on a guess.
- **Solo upkeep:** every patch is ours to own, document and keep current, on a project that already has an open servo fault and untested pipeline.
- **Public repo rules** still apply: no personal data, no attribution, clean history.

## How to keep it cheap if we do it

- Keep a **small patch series on top of a pinned upstream tag** (not a long-lived diverging fork), so each Petoi release is a rebase.
- Start with the highest value-to-effort patches: **#1** (camera/IMU restore), then **#3** (recovery handoff), then **#2** (mid-walk reflex).
  Leave **#4** until the hardware comparison says a faster IMU would help.
- Prove the build and flash path on the BiBoard first (a no-op build flashed and `gc`-verified) before writing any patch.
- Record every patch with the problem, the change, and the on-robot check.

## Decision triggers to revisit

- The AI Head arrives and a Pi-less or camera-on-BiBoard build looks worthwhile (items 1, 8, head fork).
- The hardware H1 comparison shows the 5 Hz IMU or the joint-command timing is what limits the learned gait (items 4, 6).
- We want mid-walk reflexes or firmware/Pi recovery to coexist (items 2, 3) and the Pi-side version isn't good enough.
- Petoi publishes the head firmware.

Until one of these fires, the standing decision stays: no fork.
