# Current status

**The one place for "what is true right now."** Last verified 2026-10-02. Everything volatile — what is deployed, what has
been exercised on the robot, open problems, next steps — lives here; the README, capabilities list and plan link to this
file instead of restating it. History and data live in the dated logs, not here. Update rules: [`README.md`](README.md#where-to-update-what).

## The robot

| Part | State |
|---|---|
| Bittle X V2 body, BiBoard V1_0, alloy feedback servos | Assembled, calibrated, running current official firmware (OpenCat B10_260527). Firmware module flags set: Serial-2 (`XS`) and the onboard voice module. The IMU is calibrated (`gc`); both persist across power cycles. See [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md) |
| Raspberry Pi Zero 2 W + PiSugar S | Mounted temporarily (the payload can shift). Talks to the BiBoard over UART (`/dev/serial0`, 115200); IMU stream is the stock **5.0 Hz**. Powered by the PiSugar, not the BiBoard. Build record: [`blueprints/`](../blueprints/README.md) |
| Camera (Grove Vision AI V2) | On the Pi's USB (`/dev/ttyACM0`), mounted rotated 90°, so the module has to be turned upright for the model to fire. Custom 3-class detector deployed on the camera. Vision-based navigation is gated **off** (`features.vision`, default False). See [`vision/`](vision/) |
| Microphone + speaker | Parts ordered, not yet wired. Pinout and wiring: [`blueprints/biboard-pi-connector.md`](../blueprints/biboard-pi-connector.md) |
| Petoi AI Head | Ordered, arriving ~2026-10-10; whether it replaces the Pi is an open decision — [`research/petoi-ai-head-evaluation.md`](research/petoi-ai-head-evaluation.md) |
| Battery | Reads ~7.6–7.8 V (roughly half charge for the 2-cell pack) |

## What is deployed

- **Walking policy:** `Release_CandidateV2.1` (the name is `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py`), exported with a
  sidecar that makes the loop send a joint command every 3rd tick. Earlier policies and why: [`rl/hw1-log.md`](rl/hw1-log.md).
- The Pi code is pushed with `rsync` (never `git clone`), see [`guides/pi-bring-up.md`](guides/pi-bring-up.md).

## What has been exercised on the real robot

- **Hard-floor walking (V2.1):** six clean 10-cycle runs, ~0.118 m/s, steady; drifts right and rolls ~±6° ([`rl/real-walk-log.md`](rl/real-walk-log.md)).
- **Firmware step gait (`vtF`):** steady after the IMU calibration. **Pi serial link, 5 Hz IMU, fall guard, camera feed:** working.
- **Not yet run on the robot:** the full app (`python -m pi_pipeline.app --serial`), live voice (no audio hardware yet), live memory, the
  behavior runtime, and vision-based reflexes. `CliffGuard` and `Avoider` are not wired into the app (deliberately; see the plan).

## Open problems

1. **Front-left shoulder servo (servo 8) is faulty or mis-sensing:** sticks near 42° and misses its commands; the FR shoulder shows
   occasional glitch readings. Findings and ordered next steps: [`rl/real-walk-log.md`](rl/real-walk-log.md) ("Servo troubleshooting").
2. **Carpet:** every gait tried (V2.1, scripted, lift/stride variants) fails on ~1/4 in pile; falls are sideways to the right.
3. **Heading drift to the right** and a large roll swing while walking; the FR leg sags after the servos relax at rest.
4. The scripted-vs-learned comparison (H1) is unanswered, and the 2026-10-01 walks all ran with the FL shoulder ~8° low.

## Decisions pending

- **Petoi AI Head vs the Raspberry Pi** — criteria and test steps in the evaluation doc above; do not remove the Pi before the scorecard is filled.

## Next steps (in order)

1. Diagnose the FL shoulder servo (wiggle test, reseat, swap 8 and 9, full-battery rerun), then re-run the walk comparisons.
2. Hard-floor controls for the lift/stride variants, then carpet; hands-off drift runs in a larger space.
3. When the AI Head arrives: run the evaluation steps, then decide.
4. Install the microphone and speaker if the Pi stays; first full-app run on the robot.

Open work by item ID: [`backlog.md`](backlog.md). Roadmap and decisions: [`project-plan.md`](project-plan.md).
