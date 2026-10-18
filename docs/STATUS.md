# Current status

**The one place for "what is true right now."** Everything volatile (what is deployed, what has been exercised on the robot, open problems, next steps) lives here; other pages link to this file instead of restating it. Update rules: [`README.md`](README.md#where-to-update-what).

Each row carries the date it was last confirmed. The long dated write-ups that used to fill this page (test results, build notes, every fix) are kept in [`archive/status-2026-10-detail.md`](archive/status-2026-10-detail.md); run-by-run data is in [`rl/real-walk-log.md`](rl/real-walk-log.md). Last rewritten 2026-10-17; the hardware state below is as last recorded and was not re-checked that day (the Pi was offline).

## The robot

| Part | State (as last confirmed) |
|---|---|
| Body and board | Bittle X V2 with a BiBoard V1, alloy feedback servos; assembled, calibrated, running official OpenCat firmware (B10_260527) with the Serial-2 and onboard-voice module flags set and the IMU calibrated (2026-10-08). The front-left shoulder servo was replaced 2026-10-06. [`hardware/as-built.md`](hardware/as-built.md) |
| Pi | Zero 2 W on the PiSugar S, UART to the BiBoard at 115200; IMU stream is the stock 5.0 Hz. Mounted in the Bittle X Pi add-on pod on the platform cover (since 2026-10-17, [`../blueprints/mounting.md`](../blueprints/mounting.md)); payload 185 g (was 168 g), the camera's new view is not measured yet. Runs the voice service (`g2-voice`) from boot. Deployed by `rsync` ([`guides/pi-bring-up.md`](guides/pi-bring-up.md)) |
| Camera | Grove Vision AI V2 on the Pi's USB (`/dev/ttyACM0`), custom detector on the camera; the module is mounted rotated 90°; since 2026-10-17 it is on top of the pod at the front, lens forward (orientation unchanged). Vision-based navigation is gated off |
| Microphone and speaker | I²S mic and amp installed and working (2026-10-04). The mic is very quiet, so a software gain is applied. [`blueprints/build-logs/i2s-audio-build-log.md`](hardware/build-logs/i2s-audio-build-log.md) |
| Mass | About 422 g; about 46% of the weight over the front feet (2026-10-07) |
| Pi battery | PiSugar S 1200 mAh, no readout. Measured full-charge runtime 3.28 h (mean of three runs, 2026-10-10); warning at 70% of it (about 2.29 h), critical at 80% (about 2.62 h). Recharge from flat takes about 40 minutes |
| Petoi AI Head | Mounted on G2 (owner, 2026-10-18), on stock Petoi firmware, 42 g, counted in the payload. Used as an extra LLM by pressing its button; Claude stays the main brain. Wired to G1 with data, so its model can move G2 and change firmware settings (it sent `g`, the gyro toggle, in a test): use it only while G2 is idle or resting (details and the sim's numbers: [`hardware/specs.md`](hardware/specs.md)). A tool server on the Pi was reached from the head (2026-10-11). The head's tool server has an opt-in memory recall tool (`G2_HEAD_RECALL=1`, not enabled on the Pi); role prompts (Petoi's default and the G2 replacement) are kept in [`planned/ai-head/head-role-prompts.md`](planned/ai-head/head-role-prompts.md). Plans: [`planned/ai-head/`](planned/ai-head/README.md) |
| Robot arm | A Petoi Bittle X+Arm module arrives the week of 2026-10-19, not installed: [`planned/robot-arm.md`](planned/robot-arm.md) |
| Attachments | One setting (`G2_ATTACHMENT`, `g2attach none\|head\|arm`) says what is on the neck and switches the gait policy saved for it, the firmware check and the arm's skills. Built 2026-10-18; G2 is on `none` until it is set. Every profile also sets the BiBoard voice module to English at each service start-up (deployed with the commit that added it). No gait is saved yet for any attachment (`none` with nothing saved = the legacy behaviour); the arm's firmware and skills are untested: [`guides/attachments.md`](guides/attachments.md) |

## What is deployed

- **Walking policy:** V7 (the name is `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py`; deployed to the Pi 2026-10-18, not yet walked on G2), heading-blind (the Pi feeds it yaw 0), a joint command every third control tick. It is the V6 recipe retrained from scratch for 20M steps on the pod + AI head payload (sim profile `pod`, 481 g in all); the user promoted it without the benchmark rule. Against V6 scored on the same payload in the sim it fell less (mean cell falls 0.159 against 0.174) and climbed the lowest step-up far more often (93% against 0%); calm-walk heading is about equal (10.8 against 10.4 deg); both are at 0% on the taller step-ups. It is also saved as the head attachment's gait (`G2_ATTACHMENT` is still `none`). No foot trim is measured for V7 yet (V6's `fl=-0.3` does not carry over). V6, V4, V3 and V2.1 stay on the Pi as fallbacks. Plan and training record: [`plan-detail/v6-staged-training-plan.md`](plan-detail/v6-staged-training-plan.md). Rollback: set `DEFAULT_POLICY` to the earlier file and run `tools/g2_deploy_when_online.sh --once`. Lineage: [`rl/hw1-log.md`](rl/hw1-log.md).
- **Steering:** the heading hold is OFF by default (`G2_FOOT_HOLD=fl` turns it on); the everyday walk uses a fixed front-left foot trim per policy (`DEFAULT_TRIMS` in `gait/heading_hold.py`: V6 `fl=-0.3`, measured on hardwood only). On hardwood V6 walks within about 2 in of centre over short runs; long-lane tuning and tile are open.
- **Stand-up:** every stand-up uses the eased 0.8 s ramp (`gait/standup.py`); a stop out of a stride is immediate.
- **Voice:** wake word, local commands (stop, sleep, shut down, floor, "walk for N seconds", gait switching), conversation mode ("let's talk"), spoken exchange sounds. Commands: [`guides/voice-commands.md`](guides/voice-commands.md). Switches: [`guides/settings-switches.md`](guides/settings-switches.md).
- **Sleep:** on by default after 5 minutes at rest (`G2_SLEEP_AFTER_S`).
- **Memory:** live on the Pi (facts, exchange log, pinned core, sleep-time consolidation). Reflection levels 1 to 3 are built; on the Pi reflection is parked (`G2_REFLECT=off` since 2026-10-18) until there are more sessions, and the recaps keep being written. A dry run of the idle pass had never fired before that (the service restarts too often for its 20-minute idle window).
- **Exploration:** two tiers (stationary attentive, voice-armed roam) with timed turns, picture stops, a wall avoider (turns away from a near wall) and a hit sequence started by an IMU contact signal. Guide: [`guides/exploration-mode.md`](guides/exploration-mode.md).
- **Battery alarms:** G2's pack and the Pi's runtime both warn by voice; thresholds are settings.
- **Sounds:** one at a time through an audio gate; levels in `sound_levels.py`.
- **Not deployed as of 2026-10-10:** place-memory logging (P1, built and tested). Check what the Pi has with a dry-run `rsync` before assuming.

## Exercised on the real robot

- **Walking:** V2.1 on hardwood (six steady runs, drifts right, rolls about ±6°); V4 on hardwood and over a 1/4 in ramped threshold with no falls (2026-10-09); V6 calibrated on hardwood with a fixed trim (2026-10-10). Data: [`rl/real-walk-log.md`](rl/real-walk-log.md).
- **Voice to Claude to walk,** spoken replies, and the first full listen-talk-walk run (2026-10-04); exploration by voice hand-over (2026-10-05).
- **Wall avoider and hit sequence** (2026-10-10 evening): the user judged avoidance "working fairly well" and saw G2 back up after bumping a wall. The fall horn plays; sleep and wake and the follow-up window work.
- **IMU captures** at rest and standing (5.0 Hz, no sensor bias) and wall-stall runs that separate from free walks on heading jitter.
- **Not yet run on G2:** vision-based reflexes while walking; the full `app --serial` over a long period; the teach tool (`gait/teach.py`); the recognition labelling photos; the per-leg wall look; conversation mode ("let's talk") as a hardware test.

## Open problems

1. **Heading drift on other floors.** Hardwood is handled by the trim; tile is unresolved (2 falls in 4 held 25 s walks on 2026-10-07 with the hold) and carpet is open.
2. **Carpet.** Every gait tried fails on about 1/4 in pile; falls are sideways to the right.
3. **Standing wobble.** The firmware balance loop goes unstable on a 5 Hz IMU; the idle-balance-off setting and a guard are deployed but a rest-then-stand has not been confirmed on G2. [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md)
4. **BiBoard ticking** during runner-started walks: unexplained, parked by the user, no reflash. First suspect if it returns: any quiet command sent per second (`G2_NOISE_LOG_ALL=1`, then `python -m pi_pipeline.link.noise_log 60`).
5. **Back-left shoulder servo** is stiffer and louder (noted 2026-10-09, parked); flag anything unusual.
6. **Control ticks run late during exploration** (9 to 23 percent), speech arrives 7 to 17 s after it is decided, and the turn-away and hit turns sometimes fight; the camera contact frame can be 8 s late when the camera is busy.
7. **Wall estimate gaps:** beyond 24 in it only says far or near; left-angle walls, the right 45° wall and corners read far. [`vision/wall-check-plan.md`](vision/wall-check-plan.md)
8. **Stepping up and over small ledges.** No policy crosses step-ups above 7.5 mm in the sim; the high-step creep attempt (2026-10-12/13) did not clear steps better than V6. A high-step gait is still wanted: [`planned/README.md`](planned/README.md).
9. **Open firmware question:** "be quiet" makes the BiBoard's voice module ignore basic commands; there is no known way to remove only its spoken "ok" ([`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md)). Never send `Xa` or `XAd`.

## Decisions pending

- **Petoi AI Head:** scope changed 2026-10-18: the head's LLM is an extra used by its button, Claude stays the main brain, nothing is integrated for now (see the plan doc's section 0). [`planned/ai-head/ai-head-implementation.md`](planned/ai-head/ai-head-implementation.md). Do not remove the Pi before the scorecard is filled.
- **A new 20M** starts only on the user's go and never on top of a consolidated 20M.
- **Gait comparisons on G2** are not run (sim only, user rule 2026-10-09), so the original scripted-vs-learned hardware comparison (H1) is not being pursued.

## Next steps

1. **Hardware session** (the user's go, each run on their reply): the remaining blocks of [`plan-detail/hardware-session-plan-2026-10-09.md`](plan-detail/hardware-session-plan-2026-10-09.md): recognition photo labelling, a longer roam in a second room, the right-45° and corner wall pictures, the teach tool.
2. **System-identification capture** (rest of it; Capture A is done): [`rl/sysid-capture-plan.md`](rl/sysid-capture-plan.md), then `real2sim.py --fit` with the Mac idle.
3. **Fixes from 2026-10-10:** arbitrate the turn-away against the hit turn; the camera busy delay for the contact frame; profile the Pi during an exploration for the late ticks.
4. **Place memory:** deploy P1 when no exploration is running, then roam in two or three other rooms, then P2. [`planned/place-memory-plan.md`](planned/place-memory-plan.md)
5. **V6 trim:** a longer 20 s / 9 ft lane and the tile threshold strip.

Open work by item ID: [`backlog.md`](backlog.md). Roadmap and decisions: [`project-plan.md`](project-plan.md).
