# Arm policy plan (ARM1): Petoi's arm walk on the claw payload, stock legs

Written 2026-10-24. Goal (user): a walking policy ready to deploy once the Petoi arm is installed, trained tonight while the arm goes on. It is an
intermediate step towards the final build: this policy keeps the **stock shoulders and stock feet**. The wide shoulders and CLpaw get their own
policy later (ARM2), after those parts are installed. Background on the arm firmware: [`../planned/robot-arm.md`](../planned/robot-arm.md).

## Decisions (user, 2026-10-24)

| | |
|---|---|
| Base walk | Petoi's arm walk `wkArmF` (`reference_gait/wkArm_ref.npy`) in place of `wkF`, as the residual base and the imitation reference |
| Rewards and recipe | The V7 recipe unchanged ("today's rewards"); reward changes for the claw's weight come after the first hardware data |
| Turn blending | Off (already off in the V7 recipe) |
| Gait switching | Off on G2 with the arm |
| Easing | Off on G2 with the arm (stand ramp, skill transitions, stop blend) |
| Gyro balance | Off throughout arm testing: policy walks, poses and Petoi's own walk |
| Servo range | Petoi's arm build (P1S, 290 deg) assumed right; checked at calibration |
| Step speed | Today's 1.25 s cycle; Petoi's real cycle is measured on hardware and a matched-speed screen follows if it differs |
| Legs | Stock shoulders, stock feet (CLpaw and wide shoulders: ARM2, later) |
| AI head | Removed; the arm takes the neck |

## Simulator: the `arm` payload profile

The pod as in `pod` (185 g, weighed) with the AI head body replaced by the claw. Nothing about the claw is published except what follows, so the
uncertain values are varied per episode.

| | Value | Source |
|---|---|---|
| Claw mass | 63 g, varied ±15 g | Petoi's spec pages: the arm version tops out at 353 g against 290 g for the plain Bittle X |
| Position | centre 3.1 in (80 mm) ahead of the body centre, at the torso's mid height (z 0), varied ±0.4 in in x and z | estimate: the arm hangs from the neck servo and reaches forward; the AI head's centre is at 68 mm |
| Collision box | 2.4 x 1.2 x 1.0 in (60 x 30 x 25 mm) | estimate, so the sim sees the claw hit the floor in a stumble |
| Whole robot | about 502 g (AI head build 481 g) | |

When the claw is weighed and measured, the profile takes the real numbers (fixed, no variation, as for the pod). If the weight is more than 15 g
off the estimate, a retrain on the real numbers is offered.

The camera moves too (user, 2026-10-24): with the arm it is mounted on the claw, not on top of the pod. The camera (Grove Vision AI V2, about 15 g, not
weighed) comes out of the pod's weighed 185 g and goes onto the claw, so the pod is about 170 g and the claw carries arm + camera, far forward. The claw is
rebuilt from the real parts (photos or print files, weights from a scale) before the chain starts; the runner holds after the screen until then
(`trained/arm_hold`).

Note: the user judged G2 at his limit at 481 g (2026-10-21); the arm build is about 21 g heavier, with the weight further forward.

## Training (unattended runner `phase_arm.py`, a copy of `phase_pod.py`)

1. **Build and preflight** (about 1 h of work, then `preflight.py` must pass): the `arm` profile in `opencat_gym_env.py`, the runner, a sim
   playback check that the claw box sits where intended.
2. **Two 3M screens** on the `arm` payload, one after the other (about 26 min each):
   - `armwk`: the arm walk base, the V7 recipe. The candidate recipe.
   - `armctl`: today's `wkF` base, the V7 recipe. The control: shows whether the arm walk base helps with the claw.

   Gate for `armwk` (standing screening rule): it learns, and it does not fall more on flat ground than the control. If it fails, the chain
   runs on whichever screen passed, and the report says so.
3. **The V6/V7 chain** on the passing recipe, fresh from S0: S0 2M, S1 3M, S2 3M, S3 1M, a flat-ground check, then the 20M (about 4 h in all).
   The 20M is part of tonight's training per the user ("train the new walking policy tonight").
4. **Pick, export, score:** average of the last 5 checkpoints, exported to ONNX with the sidecar (`base_ref: wkArm`, `payload_profile: arm`,
   residual scale, command cadence). Scored against **V7 in the same claw world** (V7 is the policy G2 would run with the arm today), 100
   paired episodes per cell, plus the load ladder.

Estimated timeline (`tools/eta.py`, medians of finished runs of the same size; from a 5:15 PM start):

| Step | Time | Done about |
|---|---|---|
| Build the profile and runner, sim check | about 60 min | 6:15 PM |
| Preflight | about 15 min | 6:30 PM |
| Screens `armwk` + `armctl` (3M each, scored) | about 26 min each, 52 min | 7:25 PM |
| Chain S0 to S3 (9M) + flat check | about 75 min | 8:40 PM |
| 20M | about 141 min (130 to 168) | 11:00 PM (10:50 PM to 11:30 PM) |
| Pick, export, score against V7 in the claw world, report | about 35 min | 11:35 PM (11:20 PM to 12:15 AM) |

Clocks are re-estimated with `tools/eta.py` at each launch. Early estimates have run short by up to about 40%.

## Promotion rule (set before the result; needs the user's approval)

ARM1 is ready to deploy if, against V7 in the claw world:

- no falls on flat ground (T1.1, N1);
- mean falls over the shared benchmark cells no more than V7's + 0.03;
- calm-walk heading no more than V7's + 5 deg, and under 20 deg;
- calm-walk speed at least 70% of V7's (the arm walk's stride is shorter: 72% of `wkF`'s open loop at the same cycle).

Step-up success is reported, not gated: the arm walk cannot step up open loop, and climbing with the claw is not a goal for this policy.

If it passes, it is saved as **the arm attachment's gait only** (`Release_CandidateARM1_ppo.onnx`); `DEFAULT_POLICY` (V7, used by the head and
no-attachment setups) does not change. If it fails, the full report says why, and V7 stays the arm's fallback.

## Pi work before the first walk (built and tested on the Mac while training runs)

1. `promote_release.py --attachment-only`: save a release to one attachment's slot without moving `DEFAULT_POLICY`.
2. `gait_profiles.json` arm entry: `payload_profile: arm`; `pi_pipeline/gait/wkArm_ref.npy` (the Pi reads the base walk named by the
   sidecar).
3. With the arm fitted: easing off (stand ramp, skill transitions, `blend_to_balance`), gyro balance off for poses and firmware skills
   (no `gB`), gait commands answered "not with the arm" and the gait held at normal.
4. The arm's skills (`pickF`, `putF`, `tossF`, `showOff`, `clap`) kept out of the conversation until they pass the bench test.
5. The head attachment stops accepting the `Bittle X+Arm` firmware (the arm build changes every posture).
6. A new hardware epoch for the real-data pipeline (`arm`), so arm-build walks never mix with the AI head epoch. Added with the install time
   when the user says the arm is on (epochs are dated by their start).

Items 1 to 5 are built and tested on the Mac (2026-10-24): the profile switches `easing`, `gyro_balance`, `gait_switching` and `skills` are
off for the arm ([`../guides/attachments.md`](../guides/attachments.md) "Behaviour switches"); `run_gait.py --openloop --base wkArm` plays
the arm walk (H5). None of it changes the head or no-attachment behaviour (tests pin that). **Not deployed: the Pi gets it only after the
user says the arm is installed** (user, 2026-10-24), when the Pi is idle and everything is committed.

## Hardware test plan (after the arm is installed)

Each step runs on the user's go, G2 on his feet on the floor with hands near, the floor label set (`g2floor`), one step at a time with a
report in between. Battery as percent at the start of each step.

| Step | What | Pass | Time |
|---|---|---|---|
| H0 | Before the swap: photograph the Joint Calibrator offsets; weigh the arm module, the camera, and the arm with the camera on; photograph and measure where it sits (forward of the neck, how low the claw hangs with the arm at its walking angle) | numbers recorded here | 15 min |
| H1 | Swap and flash: AI head off, arm on (J-hook neck part); Desktop App, product **Bittle X+Arm**, board BiBoard_V1_0, the `cu.usbmodem` port; `?` reads `Bittle X+Arm`; recalibrate every joint and the claw (`c-2` / Auto); voice module English | banner right, the calibration pose looks right (this also checks the servo range) | 45 to 60 min |
| H2 | `g2attach arm`; `python -m pi_pipeline.doctor --serial` | firmware check passes, the arm's gait and settings shown | 5 min |
| H3 | Bench poses: a small joint 1 move (which way is up), claw open / close, `kbalance`, `ksit`, `krest` from standing (does the claw clear the floor?), back to stand; one camera picture from the claw-mounted camera (where it points at the arm's walking angle, whether the cable reaches through the lift and claw moves) | no contact, no jump, view noted | 15 min |
| H4 | Petoi's walk: `fw_skill_log.py kwkF --seconds 10` (plays `wkArmF`), balance off, with a phone video; twice | distance and drift recorded; the cycle time counted from the video | 10 min |
| H5 | The same walk from the Pi at the training pace: `run_gait.py --openloop --base wkArm --cycles 6` | compared with H4 | 10 min |
| H6 | ARM1: `run_gait.py --cmd 0.10 --seconds 12.5`, three walks; then V7 once for comparison | no falls; distance and drift; a foot trim if needed (`g2attach save arm ... --trim`) | 25 min |
| H7 | Turns: `kwkL` / `kwkR` (play the arm turn) | turns without tipping | 10 min |
| H8 | Rest and stand: `d`, then stand (no easing) | no fall, heading jump noted | 5 min |

About 2.5 to 3 hours in all, at the pace of one go per step. H0 to H3 do not need ARM1 and can run tonight while it trains; H4 and H5 need the
Pi work above deployed (after the user says the arm is installed); H6 needs ARM1 (about 11:35 PM, or the next morning).

Not in this round: self-right with the arm, exploration, the arm's pick and toss skills on the floor, voice-driven walks. With the camera on the claw,
every camera-using behaviour (exploration pictures, gaze, the cliff guard) sees from wherever the arm points; checking those is a later round.

## Looks and physics (user, 2026-10-24)

Only what changes how G2 moves goes into the simulator: the pod's CAD place and size, the body's real height (`models/bittle_esp32_cad.urdf`) and the arm's parts
(`opencat_gym_env.ARM_PARTS`: shapes, weights, walking pose) are in ARM1's training. Looks stay in the live viewer only (`build_body_mesh.py`: the real part meshes and
colours, loaded from gitignored `models/local/`); they are not copied into the other viewers or the training. A later change to the claw from the user's photos goes into
the training only for its shape, weight and position.

For the next model update (not ARM1, whose 20M started 8:50 PM): the arm's lift servo sits where the stock head's neck servo sat, in the same mount (user, 2026-10-24),
so `lift_servo` moves to the CAD neck mount (about 12 mm further back than the estimate; the training already varies the whole arm +-10 mm). The user's scale weights
of the arm and the camera replace the estimates (63 g from Petoi's spec pages; the camera's 15 g is a guess: Seeed publishes no weight, and the case is 29 x 47 x 15 mm
from the platform project's model). No length specs for the arm are published.

## After the first hardware round

- If Petoi's cycle (H4) differs from 1.25 s by more than 20%: a 3M screen at the matched speed (`phase_rate_nom_cmd` in the sidecar).
- Reward changes for the claw's weight, chosen from what H4 to H6 show.
- Screen the levers from earlier work one at a time to see what is worth keeping.
- ARM2: the same plan with CLpaw and the 0.2 in wide shoulders, once installed.

## Results

### ARM1 sim result, 2026-10-24 (11:13 PM training end, 11:35 PM verdict)

20M steps on Petoi's arm walk (wkArm), claw payload, stock legs; 100 episodes per test, one seed. Weights picked: avg5 of the last five checkpoints (final scored the same on falls and speed, 13 deg heading instead of 18). Promoted as the arm attachment's walking policy (`--attachment-only`; `DEFAULT_POLICY` unchanged).

- Strong: no falls on flat ground, carpet, slick tile or the carpet-to-hard transition; calm walk 0.099 m/s, roll 3.5 deg, left-right asymmetry 2.7 deg; uphill and downhill to 10 deg; rubble, thin cords and overheated servos at or under 12% falls at every size.
- Needs work: step down (70% falls at 0.6 in, 97% at 0.9 in); side-hills (about half fall at 6 deg, over 80% at 8 deg, worse right side down); heading drift 18 deg on the 12.5 s walk; step up crosses only the smallest step (larger ones stall without falls); brutal shoves 44% falls.
- 20M progress checks: speed 0.094 to 0.099 m/s, asymmetry 4.1 to 1.3 deg, heading 9 to 20 deg throughout, step-down falls 0.79 at 2M, 0.36 at 4M, 0.62 at 20M.
- V7 in the same claw world (background only, scored on the stock walk it was trained on): mean falls 0.219 against 0.293, heading 7.6 against 17.6 deg, speed 0.105 against 0.099 m/s, right side-hill mean falls 0.08 against 0.33. The pre-set rule failed on falls and heading (footnote only; nothing was gated). V7 would not run as scored on G2, since the arm firmware plays the arm walk.
- Caveats: one run and one scoring seed; the claw weight is an estimate (63 g plus the 15 g camera).
- Report page: published as an Artifact (ARM1 Claw Gait Profile). Reports: `trained/arm_report/` (final, avg5, v7_claw).


### Hardware, 2026-10-24 evening (H0 to H3)

- **H0:** joint offsets backed up from the stock firmware (`blueprints/calibration.md`); the arm and camera were not weighed yet (the sim keeps 63 g and 15 g).
- **H1:** flashed Bittle X+Arm B10_260527. The Desktop App's port list could not show the BiBoard's `cu.usbmodem` port (its dropdown draws three rows and the
  port was fourth), so the flash ran from the terminal with the app's own esptool command and files (`FirmwareUploader.py`); all four hashes verified. The
  stored calibration survived (no first-boot questions, leg offsets unchanged); claw pan -14, lift 0, open 1 (Auto). The voice module came back in Chinese, as
  after every reflash; the Pi's start-up sets English.
- **H2:** deployed (commit 74c5967); with the BiBoard connected the service logs "firmware 'Bittle X+Arm' fits arm", voice module English, gyro balance off.
- **H3 (battery 50% at the start):**
  - arm lift: higher values swing the claw forward and out (0 hanging, 30 reaching forward); a 10 deg move reads as a twitch;
  - claw: positive opens it (30 about 30 deg), 0 closes it fully, clean;
  - stand (`kbalance`): stable, the arm in the reverse L, the claw about 1 in off the floor (sim estimate about 0.7 in);
  - sit: claw clear; rest: the claw rests against the floor (Petoi's design, so every rest, including the Pi's idle rest, sets it down);
  - stand from rest, no easing: good;
  - the claw camera works at 240 x 240 only (480 and 640 frames arrive cut off, as before); its view is about 1 to 2 in off the floor, with the jaws at the
    bottom of the frame; the on-device detector called the floor "cat 65%".
- **Stopped at H4:** two unexpected poses traced to the Pi-to-BiBoard plug working loose (how it was connected, not the arm), then the battery ran out.
  Before H4: a charged pack, the plug seated, and the Pi's voice service restarted with G2 on (its start-up checks need the board).
