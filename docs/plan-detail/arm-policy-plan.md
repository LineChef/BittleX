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
- ARM1 against Petoi's scripted arm walk (wkArm, no learned correction), same claw world, 100 episodes, same seed (scored 2026-10-25, `trained/arm_report/scripted_wkarm.json`): the scripted walk is steadier and straighter, ARM1 is faster and gets through more clutter.
  - Scripted wins: falls (step down 0.6 in 15% against 70%, 0.9 in 33% against 97%; side-hill 6 deg 0% against 45-57%; shoves 25% against 44%; ledges 0% against 43-49%), heading drift (2.4 deg against 17.6 on the 12.5 s walk), roll (1.4 against 3.5 deg).
  - ARM1 wins: calm-walk speed (0.082 against 0.064 m/s on the 12.5 s walk, +28%; 0.081 against 0.058 on flat, +40%), rubble (62-78% crossed against 0-7%), box obstacles (100% against 45% at half size), thin cords, rough floor at 2x, overheated servos.
  - Both stall at step ups above the smallest size; both fall on the brutal gauntlet (89% / 78%).
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

### Hardware, 2026-10-25 (H4 to H6, hardwood, battery 100% then 88%)

- **H4, Petoi's walk** (`kwkF`, 10 s): 4 ft 4 in and 4 ft 5 in (0.13 m/s), 5 to 7 in off line; roll swing 3.3 to 3.7 deg; cycle about 0.5 s (from the IMU roll period).
- **H5, the arm walk from the Pi at the training pace** (1.25 s cycle): 1 ft 7 in in 7.5 s (0.064 m/s, the sim's figure), 1 in off line.
- **H6, ARM1** (cmd 0.10): one fall at the stand-up, then no falls; roll swing 9 to 11 deg (sim 3.5), 20 to 26 deg left; the front right leg limped (not during Petoi's
  walk). The user saw the cause: ARM1 put its front feet much further out (front shoulders 62 to 63 deg against Petoi's 55). Why: the sim played the base at
  cmd / 0.10, and Petoi's walk moves only 0.064 m/s at that rate, so the policy closed a 56% speed gap with a longer reach.
- **ARM1R** (the fix: `G2E_PHASE_RATE_NOM_CMD` 0.064, so a 0.10 command plays the base 1.56x faster; promoted for the arm and deployed 8:02 AM): front shoulders
  56 deg, back 75, yaw +12 deg, no fall. The user: more stable than ARM1, still a lot of roll. The reward had almost nothing against roll and a soft imitation term.
- **Weights** (user): 532 g with the arm (sim 502 g); front feet 288 g, back 259 g (52.6% front; the sim matched). **Claw height** standing: 1.25 in (sim 22 to 26 mm).

### Hardware, 2026-10-25 later (turns, claw, stand-up)

- **H7, Petoi's turns** (`kwkL` / `kwkR`, 5 s): no falls, roll within +-3 deg; left turn 6 deg/s (the user saw it turn left), right turn about 5 deg/s.
- **Claw bench** (standing): `kpickD` and `kputD` ran clean (`kpickD` tilts the body under 5 deg; `kputD` raises the nose about 9 deg). Decoded from the skill table: `pickD` is a pick for something right under the jaws (the legs crouch, the jaws drop to the floor); `pickF` is the forward lunge (arm to 75, front legs fold). With the 3 in treat ball under the jaws, `kpickD` tried to grab it but the jaws were too low (the crouch) and did not open wide enough. The claw opens at least to 125 with no strain; the user thinks the widest setting might just straddle the ball. Claw height standing: 1.25 in (user); ball about 3 in against an opening of about 2.75 in.
- **Arm stood at the wrong angle (found today):** the Pi never sets the arm's lift servo. After `rest` it sits at 59 to 61 (claw on the floor), and a Pi walk that began from rest walked with the claw reaching forward. The arm build's own `kbalance` sets it to 0. With the arm at 0 the ARM1R walk (cmd 0.10, 12.5 s) went 4 ft 5 in, 5 in off line, roll spread 6.2 deg against 7.2 before; the user: the rocking was better.
- **Stand-ups fell front right** (about four times this morning, the front right leg giving way; the user checked it for heat, play and weakness and a bench sweep of all four legs looked fine, so it is how the stand-up moves). The firmware `kbalance` lifts all eight leg joints at once with the claw out ahead. The arm build now stands up in order (`standup.stand_sequenced`, profile `poses.stand_via` = `sequenced`): the rear legs first, the front legs starting when the rear is half way (a fast start), the lift servo easing 60 to 0 inside the same `i` commands, `kbalance` last; 2.7 s, level (pitch +1.2 deg) in the first run, and the user: it looked good. Used by the walk loops (`ramp_to_stand`) and the link's stand-up.
- **The Pi-to-BiBoard plug comes undone during falls** (user): the board then answers some commands and not others, or none. If the board does not answer, check the plug first.
- **Fall recovery is off for the arm** (`fall_recovery: false`): the scripted self-right, roll-over and drop-recover moves are refused.
- **Open:** the servo angle scale of the arm firmware (P1S, 290 deg range, against the P1L the stock build drives): the arm looked right at lift 90, the legs were not measured; a knee move tipped the body under 1 deg, too little to test a 7% difference. A phone level on a straight leg, or two photos of a knee, would settle it.

### Fetch the green ball: what was built and measured (2026-10-25)

- **The ball** (the cat's treat ball): about 3 in across; the claw opens to about 2.75 in (up to angle 125, no strain), so it cannot be grabbed (tested standing at 95 and at 125). `kpickF` (the forward lunge) hits it and throws it **about 18 in straight ahead**; that is the cat game. `kpickD` crouches the legs and drops the jaws too low for a ball. Roll in the lunge up to +15 to +18 deg (the earlier test +-1.6).
- **Punt calibration:** a ball 2.6 in from the camera is a good punt (the claw hits it first); 4.5 in is too far. Punt range in the code: 2 to 3.5 in from the camera.
- **Finding the ball** (`vision/ball_finder.py`, plain numpy, no model, no scipy on the Pi): the green channel stands out from red and blue (55 to 85 on the ball, 19 or less elsewhere); blobs, the biggest round one. Distance from its size (330 / diameter in px inches), direction from its position. On correctly exposed pictures: 19 of 23 found (the 4 misses are the ball in a patch of direct sun, which goes pale), 3 false alarms in 19 pictures without the ball (the flat green card and the ring). Ball size at 6 / 12 / 24 / 36 in: 50 / 27 / 16 / 8 px across.
- **Pictures:** 88 with the ball and 19 without, in `training_data/greenball/` (session_1 was taken with the camera's exposure balancing off by mistake: later frames overexposed, 31 of 54 usable; session_2 with it on, rule: never take a picture with it off) and in the review page (`g2pics`: Named: greenball, greenball-noball). 25 of the 73 first-set files are cut off by 16 bytes (the camera's usual truncation). 50 ball pictures were promoted to the training data automatically; the no-ball ones are kept out. The trained "ball" class needs 300+ varied pictures: the chase saves each picture with the ball found, with its box, once every 2 s (approved by the user).
- **The chase** (`behavior/ball_chase.py`): stop, look, step: turn toward the ball (Petoi's turn, 6 deg/s), walk up to it (`kwkF`, 3 s at most), punt (`kpickF`), look where it went, search toward the side it was last seen, back up after three punts that do not move it; never gives up on its own (stop file `~/.local/share/g2/ball_chase_stop`, Ctrl-C, a fall, or a battery under 30% or unreadable). Dry run on the Pi: sensible decisions. Live 5 steps: the walks did not close the distance (20 in before and after) and the back left leg was out in the pictures; suspected cause, the link's `gb` right after each skill cutting the firmware walk short (to test: the same walk with and without it). Not yet fixed.
- **Battery:** the pack died during the chase and nothing warned: the voice service's battery watch only runs while the service does, and it is stopped for every hardware test. `power.battery.motion_gate` (fail safe: under 30% or an unreadable voltage is not ok) is used by the chase; tests for it are in; not yet deployed to the Pi after the last change. Always read the battery percent before a hardware test.

## ARM1X: the claw world as measured, a training system that keeps learning (user, 2026-10-25, plan approved)

Why ARM1R's 20M stopped at about 11M: the plateau stop fired on noise (the best of three evals against one lucky early best, 8 + 6 episodes per check), the eval tested
every hazard at its hardest size (step-ups of 30 mm, which the claw build cannot pass: the jaws jam on the face from about 20 mm and the back paws stop at 15 mm,
`stepup_contacts` check), the step-up frontier sat at 5 to 7.5 mm the whole run, PPO updates ran at a 0.25 to 0.29 clip fraction, and the action noise shrank with no
entropy bonus. Changes (runner `phase_armx.py`, log `trained/phase_armx.log`):

- **The world:** 532 g (`build_limits.json`), the claw 9 mm higher (`opencat_gym_env.ARM_LOWER_DZ`; standing 31 to 35 mm), the `armsmall` recipe (imitation
  sharpness 8, roll and roll-rate terms, residual 15 deg; its 3M screen: roll 2.2 deg, side-hill 8 deg falls 7 / 12%, but less crossing of clutter).
- **Per-build tops** (`build_limits.json`): step-ups 15 mm on the arm. The top caps the training ramp, is where a hazard counts as trained, and is the top of the
  scorers' ladder; the old top is scored as a separate "beyond this build" row, outside the means.
- **Trained and stuck hazards** (`G2E_FR_TRAINED_SHARE` 0.05): a hazard passing at its top for 6 updates in a row drops to 5% of its share (practice over its whole
  range) and goes back to full share if its recent success falls 0.15 under the bar. A hazard below its top that has not moved for 3M steps is logged STUCK.
- **The eval** (`G2E_EVAL_FR`): 16 clean episodes, then each hazard at half and all of its own top; the plateau rule uses the hazards not yet trained.
- **The plateau rule** (`G2E_PLATEAU_SMOOTH`): three-eval means against the best earlier three-eval mean, the curriculum over the same windows, a hazard turning
  trained counts as progress. Off in this 20M (log only: "WOULD STOP"), so the run goes the full 20M.
- **Screens** (3M each, rule set before the results in `phase_armx.adopt`): control, PPO batch 512 x 5, entropy bonus 0.005, back paws at 20 mm in mid-swing.
  Then S0 to S3 and the full 20M with what was adopted, pick final or avg5, export `ARM1Xcand`, compare with ARM1R and Petoi's walk in the same world.
- The claw stays at its walking pose (lift 0): at 1.25 in standing and about 1 in at the lowest point of a walk it clears a 15 mm step; a 20 mm step would want
  about 10 deg of lift, only once the legs can do 20 mm.

### ARM1X result (sim, 2026-10-25, 2:53 PM) and promotion

The full run (screens: control, batch 512 x 5 and the entropy bonus adopted, back-foot clearance not; S0 to S3; a 20M with no plateau stop) finished at 2:32 PM and scored 2:53 PM; avg5 weights picked (final tied). All three in the corrected world (532 g, claw 1.25 in, step-ups capped at 15 mm), 100 episodes per test, sim only:

| | ARM1X | ARM1R | Petoi's scripted walk |
|---|---|---|---|
| Flat falls | 0 | 0 | 0 |
| Calm walk | 0.111 m/s | 0.113 | 0.096 |
| Roll / heading | 2.2 / 7 deg | 3.4 / 7 | 1.4 / 4 |
| Front / back shoulders, peak | 53 / 73 deg | 52 / 74 | 52 / 71 |
| Ladder falls / success | 2.0% / 69% | 6.1% / 72% | 3.0% / 57% |
| Step-up success (to 15 mm) | 26% | 39% | 12% |

Faster and better on hazards than the scripted walk, steadier than ARM1R (a third of the roll, a third of the falls), not as steady as the scripted walk; the sim has understated hardware roll about 1.8x for ARM1R. The 20M's training system: the plateau rule logged no "would stop"; clip fraction 0.08 (0.25 to 0.29 before); `ledge_down` was marked trained at 18M; the four slope frontiers reached F6 (ARM1R's reached F3); the frontier flagged hazards short of evidence (a slope bin needs 30 episodes) or failing (snag, from its second bin). Rubble stayed weak (success 0.12 to 0.36).

Promoted as the arm attachment's gait (`--attachment-only`, commit 226e22d) and deployed to the Pi 4:22 PM, with ARM1R and ARM1 kept as history; the Pi loads it with residual scale 15 deg and the 0.064 pace from its sidecar. **First hardware walk (2026-10-25 4:3x PM, hardwood, pack 100%):** cmd 0.10, 12.5 s, no fall, yaw -1 deg over the run, the user: walked straight down the line, ended 1 in off line (ARM1R 5 in, Petoi's walk 5 to 7 in); roll spread 4.3 deg (-11 to +7; ARM1R 6.2, Petoi 3.3 to 3.7); front shoulders 55 to 56 deg and back 75 (the sim says 53 / 73); no late ticks. Distance not measured; one run only (the user stopped the testing there).

### Blending back on for the arm (user, 2026-10-25 evening)

The user separated two things the code had under one `easing` switch: easing (smoothing a skill's own motion: stays off for every skill until we see what blending does) and blending (pose to pose, to stop the falls at stand-up to walk and similar changes: back on). New profile switch `blending` (on for the arm); `link/transitions.py` now knows the arm firmware: its rest and balance poses (`poses`), the Arm variant of a gait (`kwkF` blends into `wkArmF`, `kbkF` into `bkArmF`), and the front shift (shoulders -10, knees +6) for every other skill; the end-of-walk blend uses the arm's balance pose. In a simulation a stand-up followed by `kwkF` blends from the balance pose to the walk's first frame in 37 steps over 0.94 s, then plays the walk. Not yet run on G2 (the Pi was off); the walk_seq experiment (five identical walks after a stand-up, the ball as a ruler) is the test.

### Desk test, attempt 1 (2026-10-25 10:3x PM): a punch through the chase

Surface set to desk; the new code (commit 002fd40: the punch with the claw shut, no blind search walk, a 75 s limit, punt within 5 in); a 12 in start. Stood from rest, said "target acquired", saw the ball 13 in ahead (-2 deg), walked 2.2 s: still 13 in; walked 2.3 s: the ball dropped out of view for one look and then read 2.7 in, +7 deg; he said "punting", punched once and the attempt ended ("punted at 2.7 in, 6.7 deg after 4 looks"; walk steps (13.0 in, 2.2 s), (13.0 in, 2.3 s)). So the first walk after the stand-up again covered nothing (blending was not on the Pi yet when this ran), the ball is seen from about 13 in down to 2.7 in, and the punch fires. The user's outcome of the punch itself (did it hit the ball and how far) is not recorded. An earlier desk run searched for 12 looks with the ball in front of him and his own search walk at look 13 on a short desk: blind walking is now off by default (`--search-walk` turns it on). The user then switched the arm's stand-up back to the plain firmware `kbalance` ("easing is off"): profile `poses.stand_via` = `kbalance`; the sequenced stand-up stays in the code (`stand_via` sequenced).

## Queued until the ball testing is done (user, 2026-10-25: no work on walking or standing before then)

- **Stand-up "needs more work"** (user, 2026-10-25 4:3x PM): fixed so far, the second stand-up (the firmware `kbalance` after the sequence replayed it) and the jerky arm pull-back (1.6 s lift, 3 deg a step); more feedback to be added here as it comes.
- The arm servo angle scale on the legs (P1S 290 deg against P1L 270 deg), unmeasured.
- Walking: ARM1X repeat runs (one run so far, 1 in off line), the sim-hardware roll gap, a foot trim if needed.
- Raising the slope evidence (30 to 15 episodes) and the snag hazard for the next training run; the trained ball class; the wall estimator for the claw camera; the dim-room picture set.

### Ball chase testing, 2026-10-25 evening: where it stands (needs more work, user: pick it back up later)

Five live attempts (one punt per attempt, rest after each, stand at the start; he says "searching", "target acquired" and, since the last deploy, "punting"). One real punt through the chase (attempt 3, ball 5 in ahead at the start); the others did not reach one. Findings:
- **The first walk steps after a stand-up often do not move him** (ball distance unchanged over 3 to 4 steps of 2 to 2.7 s: 13 in four times; 15 in three times), then one step moves him 7 in or more. Pictures were different frames, so the scene really did not change. Not yet explained: a `gb` next to the gait token stopped walks (fixed: no `gb` around gaits); the sequenced stand-up followed by a gait may leave the firmware believing it is in the rest posture (it did the same with the ball chase's `kbalance` after each walk); a clean test is five identical walks in a row with the ball as a ruler (script written: `walk_seq.py` in the session scratch; not run: the Pi dropped off the network).
- **He often pushes the ball away while closing in** (walks are 6 in a second and the claw touches the ball at about 3 in); whether the ball "vanishes" because he bumped it or because the camera loses it (too close, under the claw) is untested (user, 2026-10-25).
- **Punt range:** the lunge reaches about 3 to 4 in from the camera (2.6 in threw the ball 18 in; 4.5 to 5 in just out of reach, 6 to 7 in too far). The planner nudges closer from 4 to 7 in and punts at 4 in or less, and punts when the ball vanishes right after being close; the user saw him right in front of the ball many times without punting: not fixed.
- **The Pi drops off the network while G2 moves** (ssh timeouts for minutes at a time); the Pi was powered off at the end of the evening.
- **Queued:** "g2, fetch" as the voice command that starts the chase (user, 2026-10-25); the chase as a mode of the voice service, not a script with the voice service stopped; the ball and the wall estimator for the claw camera.

## Next hardware rounds (user, 2026-10-25)

**Wall estimator, camera on the claw.** `vision/wall_distance.py` is geometry, not a model: the row where the floor ends maps to a distance through a calibration.
The camera moved twice (pod top, then the claw, lower and further forward), so the old calibration is wrong.
1. One picture at the walking pose (lift 0) to check the view is upright and where the floor strip sits.
2. `python -m pi_pipeline.vision.wall_distance calibrate`: boxes at tape-measured distances (6, 12, 18, 24, 36 in).
3. The wall checks in [`../vision/wall-check-plan.md`](../vision/wall-check-plan.md) again, then a short dry-run roam.
The calibration holds only at lift 0; any behaviour that lifts the arm must not use it meanwhile.

**Fetch the green ball (superseded 2026-10-25 night: the claw cannot hold the 3 in ball, so the game is chase and PUNCH it; see the ball chase sections above).** Find the ball, walk to it, pick it up, check the grasp, and on a miss (the claw closed on nothing, or the ball rolled away) back up,
find it again, turn to it and try again (three tries, then say so); then bring it to the person and put it down. Built from what exists, no new firmware:
1. **See the ball.** The camera's detector gives boxes at about 15 fps but knows face / dog / cat. Two paths: (a) first, colour on the Pi from the camera's
   240 x 240 pictures (green pixels: bearing, size, where in the frame), a stop-look-step approach at the picture rate, no model change; (b) then a "ball" class
   in the camera's detector (the custom-model recipe, pictures captured from the claw camera), for tracking while walking.
2. **The pick.** Petoi's arm skills `kpickF` (in front) and `kpickD` (below), then `kput` to put it down; decode each one's keyframes first (no three-foot moves).
   The ball must fit the open claw (measure the ball and the claw's opening).
3. **Did it work.** The claw servo's position after closing (on the ball it stops part-open, on nothing it closes fully; servo feedback runs at about 9 Hz) and
   one picture (the jaws are at the bottom of the frame, so a held ball fills that spot).
4. **The loop.** A small state machine in `behavior/` (search, approach, align, pick, check, retry, return, put down), each step an `Effect`, tested with mocks;
   the approach uses the arm walk policy at a slow command plus small turns (the arm turns are H7, not yet run). Returning uses the face class to find the person.
5. **Learning, later.** Once the scripted version works, the misses are data: a learned correction on the approach or the grasp (the usual scripted base plus a
   bounded residual), not before.
