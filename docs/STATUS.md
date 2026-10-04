# Current status

**The one place for "what is true right now."** Last verified 2026-10-03. Everything volatile — what is deployed, what has
been exercised on the robot, open problems, next steps — lives here; the README, capabilities list and plan link to this
file instead of restating it. History and data live in the dated logs, not here. Update rules: [`README.md`](README.md#where-to-update-what).

## The robot

| Part | State |
|---|---|
| Bittle X V2 body, BiBoard V1_0, alloy feedback servos | Assembled, calibrated, running current official firmware (OpenCat B10_260527). Firmware module flags set: Serial-2 (`XS`) and the onboard voice module. The IMU is calibrated (`gc`); both persist across power cycles. See [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md) |
| Raspberry Pi Zero 2 W + PiSugar S | Mounted temporarily (the payload can shift). Talks to the BiBoard over UART (`/dev/serial0`, 115200); IMU stream is the stock **5.0 Hz**. Powered by the PiSugar, not the BiBoard. Build record: [`blueprints/`](../blueprints/README.md) |
| Camera (Grove Vision AI V2) | On the Pi's USB (`/dev/ttyACM0`), mounted rotated 90°, so the module has to be turned upright for the model to fire. Custom 3-class detector deployed on the camera. Vision-based navigation is gated **off** (`features.vision`, default False). See [`vision/`](vision/) |
| Microphone + speaker | **Microphone wired and verified on the Pi (2026-10-03):** captures clear speech over I2S, left channel only. Speaker/amp not yet wired. Pinout, wiring and the bring-up record: [`blueprints/biboard-pi-connector.md`](../blueprints/biboard-pi-connector.md) |
| Petoi AI Head | Ordered, arriving ~2026-10-10. Petoi says it is an ESP32-C3 with a mic and speaker, firmware to be open-sourced, and expects it to complement the Pi, not replace it; whether to use it is open — [`research/petoi-ai-head-evaluation.md`](research/petoi-ai-head-evaluation.md) |
| Battery | Reads ~7.6–7.8 V (roughly half charge for the 2-cell pack) |

## What is deployed

- **Walking policy:** `Release_CandidateV2.1` (the name is `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py`), exported with a
  sidecar that makes the loop send a joint command every 3rd tick. Earlier policies and why: [`rl/hw1-log.md`](rl/hw1-log.md).
- The Pi code is pushed with `rsync` (never `git clone`), see [`guides/pi-bring-up.md`](guides/pi-bring-up.md).

## What has been exercised on the real robot

- **Hard-floor walking (V2.1):** six clean 10-cycle runs, ~0.118 m/s, steady; drifts right and rolls ~±6° ([`rl/real-walk-log.md`](rl/real-walk-log.md)).
- **Firmware step gait (`vtF`):** steady after the IMU calibration. **Pi serial link, 5 Hz IMU, fall guard, camera feed:** working.
- **Voice benchmark on the Pi (2026-10-03):** RAM fits, thermals fine, but Piper and Vosk both run slower than real time — numbers in [`guides/pi-bring-up.md`](guides/pi-bring-up.md) §8. Mic capture works; the Claude round-trip from the Pi is not measured yet.
- **Voice boot service (2026-10-03):** `g2-voice` is installed and enabled on the Pi, so the voice loop starts on every boot (print-only replies, no gait cap). G2 ran out of power before it could be tested after a power cycle; the BiBoard's own voice commands had also stopped responding. Resume notes: [`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md).
- **Voice → Claude → walk (2026-10-03):** wake word, speech-to-text, a Claude call and a real `walk_forward` on G2 all worked end to end (hard floor, 5 s gait cap, replies printed because there is no speaker yet). Speech recognition is the weak spot. Detail and findings: [`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md). The microphone is wired and verified ([`blueprints/biboard-pi-connector.md`](../blueprints/biboard-pi-connector.md)).
- **Not yet run on the robot:** the full app (`python -m pi_pipeline.app --serial`), spoken replies (no speaker yet), live memory, the
  behavior runtime, and vision-based reflexes. `CliffGuard` and `Avoider` are not wired into the app (deliberately; see the plan).

## Open problems

1. **Front-left shoulder servo (servo 8) is faulty or mis-sensing:** sticks near 42° and misses its commands; the FR shoulder shows
   occasional glitch readings. Findings and ordered next steps: [`rl/real-walk-log.md`](rl/real-walk-log.md) ("Servo troubleshooting").
2. **Carpet:** every gait tried (V2.1, scripted, lift/stride variants) fails on ~1/4 in pile; falls are sideways to the right.
3. **Heading drift to the right** and a large roll swing while walking; the FR leg sags after the servos relax at rest.
4. The scripted-vs-learned comparison (H1) is unanswered, and the 2026-10-01 walks all ran with the FL shoulder ~8° low.

## Decisions pending

- **How to stop a Claude-started walk, and who owns the voice:** G2's own offline voice module (switch: say "be quiet" / "play sound" to G2) versus the Pi + Claude path; options in [`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md).
- **Petoi AI Head vs the Raspberry Pi** — criteria and test steps in the evaluation doc above; do not remove the Pi before the scorecard is filled.

## Next steps (in order)

1. Diagnose the FL shoulder servo (wiggle test, reseat, swap 8 and 9, full-battery rerun), then re-run the walk comparisons.
2. Hard-floor controls for the lift/stride variants, then carpet; hands-off drift runs in a larger space.
3. When the AI Head arrives: run the evaluation steps, then decide.
4. Voice: finish the "rest" interrupt test (steps in [`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md), paused 2026-10-03), then wire the speaker and amp, then re-run the voice → Claude → walk test with spoken replies and the full app (first full-app run on the robot). Next week: re-evaluate the head once it arrives.

Open work by item ID: [`backlog.md`](backlog.md). Roadmap and decisions: [`project-plan.md`](project-plan.md).
