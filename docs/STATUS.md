# Current status

**The one place for "what is true right now."** Last verified 2026-10-04. Everything volatile — what is deployed, what has
been exercised on the robot, open problems, next steps — lives here; the README, capabilities list and plan link to this
file instead of restating it. History and data live in the dated logs, not here. Update rules: [`README.md`](README.md#where-to-update-what).

## The robot

| Part | State |
|---|---|
| Bittle X V2 body, BiBoard V1_0, alloy feedback servos | Assembled, calibrated, running current official firmware (OpenCat B10_260527). Firmware module flags set: Serial-2 (`XS`) and the onboard voice module. The IMU is calibrated (`gc`); both persist across power cycles. See [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md) |
| Raspberry Pi Zero 2 W + PiSugar S | Mounted temporarily (the payload can shift). Talks to the BiBoard over UART (`/dev/serial0`, 115200); IMU stream is the stock **5.0 Hz**. Powered by the PiSugar, not the BiBoard. Build record: [`blueprints/`](../blueprints/README.md). Wi-Fi: home network (priority 100) plus a phone hotspot saved as a backup (priority 50), managed with `g2wifi`; the failover itself is untested |
| Camera (Grove Vision AI V2) | On the Pi's USB (`/dev/ttyACM0`), mounted rotated 90°, so the module has to be turned upright for the model to fire. Custom 3-class detector deployed on the camera. Vision-based navigation is gated **off** (`features.vision`, default False). See [`vision/`](vision/) |
| Microphone + speaker | **Both installed (2026-10-04).** Mic verified 2026-10-03 (clear speech over I2S, left channel only). The Pi lists the speaker as playback card 0 (`Google voiceHAT SoundCard`). Spoken replies confirmed working (2026-10-04). Early-session `PortAudioError: Device unavailable` playback errors (18:22–18:26 Pi time, while the speaker was being installed) stopped on their own; later replies played cleanly. Mic and speaker do **not** contend: with the mic stream open, a separate playback opens fine at 22.05 kHz through the ALSA `default` device (the raw `hw:0,0` card only accepts 48 kHz S32 stereo, so playback must go through `default`). One uncaught playback error did crash the `g2-voice` service (exit 1; systemd restarted it) when it hit the "Sorry, I glitched" fallback after a failed Claude call; fixed in the repo (all direct `speak` calls are now guarded) but not yet rsynced to the Pi. Pinout, wiring and the bring-up record: [`blueprints/biboard-pi-connector.md`](../blueprints/biboard-pi-connector.md) |
| Petoi AI Head | Ordered, arriving ~2026-10-10. Petoi says it is an ESP32-C3 with a mic and speaker, firmware to be open-sourced, and expects it to complement the Pi, not replace it; whether to use it is open — [`research/petoi-ai-head-evaluation.md`](research/petoi-ai-head-evaluation.md) |
| Battery | Reads ~7.6–7.8 V (roughly half charge for the 2-cell pack) |

## What is deployed

- **Walking policy:** `Release_CandidateV2.1` (the name is `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py`), exported with a
  sidecar that makes the loop send a joint command every 3rd tick. Earlier policies and why: [`rl/hw1-log.md`](rl/hw1-log.md).
- **Confirmed on the Pi 2026-10-04:** `Release_CandidateV2.1_ppo.onnx` and its `.onnx.json` sidecar on the Pi are byte-identical to the repo's (md5 `0abe559b…` / `93fddbb3…`), and the Pi's `DEFAULT_POLICY` names it.
- The Pi code is pushed with `rsync` (never `git clone`), see [`guides/pi-bring-up.md`](guides/pi-bring-up.md).

## What has been exercised on the real robot

- **Hard-floor walking (V2.1):** six clean 10-cycle runs, ~0.118 m/s, steady; drifts right and rolls ~±6° ([`rl/real-walk-log.md`](rl/real-walk-log.md)).
- **Firmware step gait (`vtF`):** steady after the IMU calibration. **Pi serial link, 5 Hz IMU, fall guard, camera feed:** working.
- **Voice benchmark on the Pi (2026-10-03):** RAM fits, thermals fine, but Piper and Vosk both run slower than real time — numbers in [`guides/pi-bring-up.md`](guides/pi-bring-up.md) §8. Mic capture works; the Claude round-trip from the Pi is not measured yet.
- **Voice boot service (2026-10-03):** `g2-voice` is installed and enabled on the Pi, so the voice loop starts on every boot (print-only replies, no gait cap). G2 ran out of power before it could be tested after a power cycle; the BiBoard's own voice commands had also stopped responding. Resume notes: [`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md).
- **Voice → Claude → walk (2026-10-03):** wake word, speech-to-text, a Claude call and a real `walk_forward` on G2 all worked end to end (hard floor, 5 s gait cap, replies printed because there is no speaker yet). Speech recognition is the weak spot. Detail and findings: [`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md). The microphone is wired and verified ([`blueprints/biboard-pi-connector.md`](../blueprints/biboard-pi-connector.md)).
- **Milestone (2026-10-04):** with the mic and speaker installed, G2 walked, listened and talked together for the first time (wake word → speech-to-text → Claude → spoken reply → a real walk), run by the `g2-voice` boot service. That service runs `python -m pi_pipeline.voice --mode voice`, **not** the full app, and ignores the vision flags. **Vision while walking has not been tested.** Turn latency over 16 logged turns: speech-to-text wait median 1.0 s, first Claude token 1.2 s, to first move 3.1 s (p90 3.9), to first speech 3.8 s median but 9.4 s p90 (long replies; the first sentence is what matters). Spoken replies worked once the speaker was settled (see the mic/speaker row).
- **Right now (2026-10-04, until the stand is ready): G2 cannot move.** The `g2-voice` service runs with a systemd drop-in (`/etc/systemd/system/g2-voice.service.d/no-move.conf`) that swaps `--actuator serial` for `--actuator mock`. To restore movement: delete that file, `sudo systemctl daemon-reload && sudo systemctl restart g2-voice`.
- **Vision feed on the Pi (2026-10-04):** the camera feed opens on `/dev/ttyACM0` and polls cleanly with no serial link to the BiBoard; no detections in a 12 s test (nobody in view, module needs to be upright). The Pi's `.env` now has `G2_FEATURES=+vision,+vision_perception,-vision_safety,-explore,-avoidance_act,-object_gallery` (comma-separated; a bare `+vision` also turns on safety, explore and avoidance). The voice service ignores it; it takes effect only for `python -m pi_pipeline.app`. Backup of the old file: `~/bittleX/.env.bak-before-vision`.
- **Memory is live:** 36 exchanges logged on the Pi, 0 facts (G2 has not used `remember` yet). Recall works offline against a backup, but matches on single common words from garbled speech recognition ("being", "today"), so recall is noisy until recognition improves. `g2membackup` copies the DB to the Mac (first backup 2026-10-04).
- **Low-battery alert (2026-10-04):** the voice service reads G2's 2-cell pack voltage with the firmware's `P` command (real reading 7.89 V) at startup and every minute, and plays the `star_trek_red_alert` siren twice when it is **low (7.2 V or below, about 20%)**, repeating every 5 minutes, or **critical (6.6 V or below)**. An alert needs 3 consecutive low readings (the pack sags under load) and readings are skipped while a gait runs. Real voltage readings were verified on the Pi; the alert path (siren, then G2 says "My battery is low" in `metal`) is unit-tested but still has to be heard on G2 (a bug that silenced the siren was found and fixed 2026-10-04). Settings: `G2_BATTERY_WATCH`, `G2_BATTERY_LOW_V`, `G2_BATTERY_CRITICAL_V`, `G2_BATTERY_POLL_S`. The thresholds are estimates for a 2S Li-ion pack at rest (about 3.6 V per cell is 20%); adjust after seeing real discharge. The Pi's own PiSugar battery has no telemetry and is not watched. The watcher reads through its own read-only link while the actuator is mock; with the serial actuator it uses the actuator's link.
- **Pi battery runtime (2026-10-04, built, not yet deployed):** the PiSugar S can't report its level, so we measure how long the Pi lasts on one charge with an **intentional test** (nothing runs at startup otherwise). `python -m pi_pipeline.power runtime test start` (from a full charge, charger unplugged) starts a heartbeat; after the power dies, the next voice-service start (or `runtime test collect`) records the run. A clean shutdown or reboot during the test discards it, so a reboot is never mistaken for an empty battery. `runtime` lists runs and their mean; `runtime add <seconds>`, `runtime forget <n>`, `runtime test status|cancel`. A warning at 80% of the mean runtime (about 20% left; siren, then "My Pi battery is at about twenty percent.", again at 95%) is built but **off** until `G2_PI_BATTERY_WATCH=1` (it counts uptime since boot, so a reboot resets it); `G2_PI_FULL_RUNTIME_S` overrides the mean. First test: started when the Pi came back online after it ran flat.
- **CliffGuard is wired** into the app (built whenever `vision_safety` is on; a `SensorHub` `edge_source` supplies readings) but stays inert: no floor-vs-edge classifier exists yet, so nothing feeds it.
- **Not yet run on the robot:** the full app (`python -m pi_pipeline.app --serial`), long-run reliability of spoken replies, the
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
4. Voice: finish the "rest" interrupt test (steps in [`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md), paused 2026-10-03), then rsync the playback-error fix to the Pi, then re-run the voice → Claude → walk test with spoken replies and the full app (first full-app run on the robot). Next week: re-evaluate the head once it arrives.
5. **Acknowledgement tone (2026-10-04):** a continuous whistle named `star_trek_whistle` through the speaker (`voice/star_trek_whistle.py`, played at a peak of 0.0225, chosen by ear) now acknowledges every Claude-bound command; the buzzer blip is replaced. **Open:** the BiBoard's built-in voice commands (sit, etc.) still answer with the module's own spoken "ok". "Be quiet" makes the module ignore basic commands entirely (confirmed 2026-10-03), so there is no known way to remove only the "ok"; options are listed in the voice plan. The Pi does not speak after those commands. All speech the Pi itself produces uses `metal`.

Open work by item ID: [`backlog.md`](backlog.md). Roadmap and decisions: [`project-plan.md`](project-plan.md).
