# Petoi robot arm (Bittle X+Arm)

Research 2026-10-17. Source: Petoi docs, <https://docs.petoi.com/extensible-modules/robot-arm> (the page is thin: it gives
no specs; everything below is what it states, and the gaps are listed at the end). **The module arrived 2026-10-24; it is not
installed and the arm firmware has not been flashed.** How the arm firmware changes G2's movement:
[below](#how-the-arm-firmware-changes-movement-2026-10-24).

## What it is

An add-on gripper ("claw") for Bittle, sold as the **Bittle X+Arm** model. It lets the robot grab an object, carry it, show it off
or throw it. It has its own firmware build, so the Desktop App model is **Bittle X+Arm**, not plain Bittle X.

**Safety (from the page):** keep hands out of the claws while the arm moves (pinch hazard).

## Install

- Needs the **neck part with a J-hook**.
- Ships fully assembled. Mount the servo-with-neck-structure into the servo slot with **two M2x5 self-tapping screws**.
- The page gives no wiring, port or pin information.

## Firmware and calibration

1. Desktop App: pick model **Bittle X+Arm**, then **Firmware Uploader**.
2. Connect the BiBoard by USB data cable or Bluetooth, power from the battery (long-press its button).
3. Open the **Joint Calibrator** (enters calibration mode automatically; or **Calibrate** in the calibrator).
4. The claw is **joint index 2**. Auto-calibrate with the **Auto** button, or send `c-2` on the serial monitor. The gear on the
   servo output shaft can also be adjusted by hand.
5. Calibration is what stops the claw from jamming and overheating.

The page shows calibration screenshots for **BiBoard_V0 and BiBoard_V1** (G2 has a BiBoard); it does not mention Nybble or NyBoard.

## Serial skill tokens

Send with a lowercase `k` prefix (e.g. `kpickF`), like any OpenCat skill.

| Token | Action |
|---|---|
| `pickD` `pickF` `pickL` `pickR` | pick up an object below / in front / left / right |
| `putD` `putF` `putL` `putR` | put the grasped object below / in front / left / right |
| `launch` | launch the grasped object forward (same as "toss down") |
| `tossF` `tossL` `tossR` | throw the grasped object forward / left / right |
| `hunt` | quickly grasp the object in front |
| `showOff` | show the grasped object |
| `clap` | clap with the gripper |

A token without a direction suffix (`kpick`, `kput`, `ktoss`) picks one of the directions at random. `hunt`, `showOff` and `clap`
have no directional variants.

`hunt` and `showOff` are also names in the stock Bittle skill table ([`petoi-skills-survey.md`](../hardware/petoi-skills-survey.md)); the
arm build presumably redefines them. This is an inference, not stated on the page. Check before relying on either name.

## Voice commands (BiBoard voice module)

Start in voice mode, say "Start learning", then record ten custom commands in this order (say "Stop learning" to exit):

1. Learn skill (releases the servos so the body can be moved for motion capture)
2. Play skill (plays the captured motion back)
3. Follow (releases the servos; moving one leg makes the others copy it)
4. Pick up
5. Put it down
6. Hunt (grab quickly)
7. Show off the object
8. Put away (store it)
9. Throw away (toss it aside)
10. Shoot (throw forward)

Recording steps: [voice command module](https://docs.petoi.com/extensible-modules/voice-command-module#record-customized-voice-commands).
Never send `Xa`/`XAd` to the voice module (see the project rule in the repo CLAUDE.md).

## Other control surfaces

- **Mobile app:** download the arm's command config file attached to the Petoi page and batch-import the buttons
  ([import steps](https://docs.petoi.com/mobile-app/controller.md#import-commands-in-batches)).
- **Mind+ / Petoi Coding Blocks:** the **Perform robot arm skill** block runs the predefined skills.
- **Skill Composer** (Desktop App): author new arm skills and export them to the mobile app, a Mind+ program or source code
  ([Skill Composer](https://docs.petoi.com/desktop-app/skill-composer),
  [source-code skill creation](https://docs.petoi.com/applications/skill-creation)).
- **Sensors:** the page says the arm can be combined with other sensors, with the Grove Vision AI V2 as the example
  ([page](https://docs.petoi.com/extensible-modules/advanced-development-and-application-of-ai-vision-modules)). Adding sensors
  needs source-code changes; the page says a sample demo is "in progress" and gives none.

## What the firmware source shows (2026-10-18)

Petoi's `OpenCatEsp32` source (`src/OpenCat.h`): the arm is a **compile-time** option, `ROBOT_ARM`, inside the Bittle branch. It names the model
"Bittle X+Arm" (the first line of the `?` banner), uses its own skill table (`InstinctBittleESP_arm.h`), assigns the claw to the **tail joint**
("the robot arm's clip is assigned to the tail joint"), widens joint 1's limit to -10..180 deg (±85 otherwise) and sets the leg servo model to P1S.
The servo count (16) and the pin table do not change. So the plain build and the arm build differ, and a swap needs either a reflash or one build
that serves both (untested: [`../guides/attachments.md`](../guides/attachments.md) "Open").

## How the arm firmware changes movement (2026-10-24)

Read from `PetoiCamp/OpenCatEsp32` `main` (newest commit `f5aba6b`, 2026-10-24): `src/skill.h`, `src/OpenCat.h`, `src/reaction.h`,
`src/espServo.h`, `src/InstinctBittleESP_arm.h`, compared with the stock skill table vendored at
[`rl_training/opencat-gym/reference_gait/InstinctBittleESP.h`](../../rl_training/opencat-gym/reference_gait/InstinctBittleESP.h). Petoi's arm page says nothing
about weight or walking; everything here comes from the source. The Desktop App flashes its own packaged build (v1.2.9, 2026-05-28 at
the last check), which can be older than `main`: read the `?` banner after flashing.

The arm build compensates for the claw's weight in three ways, all inside the firmware, all compile-time (`ROBOT_ARM`):

### 1. Arm-tuned gaits replace the stock ones by name

`loadBySkillName()` (`skill.h`): for a skill name ending in `F`, `L` or `R`, the arm build first looks for the same name with `Arm` inserted
before the letter (`wkF` → `wkArmF`, `trL` → `trArmL`). If it exists, that skill plays instead and is marked `optimizedForArm`. If not, the
original plays, with the shift in 2. Arm variants exist for walk, trot, crawl, back and vault: `wkArmF/L`, `trArmF/L`, `crArmF/L`,
`bkArmF/L`, `vtArmF` (`R` is the mirrored `L`). They are byte-identical in both skill tables (the stock build carries them unused), so
they can be decoded from the vendored file. `carpetF`, `jpF` and the others have no arm variant.

What the arm gaits change, against the stock gait (decoded from the vendored table; foot positions from the sim URDF at the keyframe
angles, approximate: lower-leg centre, not the foot tip):

| Gait | Frames per cycle (stock → arm) | Mean front shoulder | Front feet, average position | Rear |
|---|---|---|---|---|
| walk `wkF` → `wkArmF` | 116 → 43 | 47° → 29° | +0.65 in further forward; front stride 2.1 → 1.8 in | unchanged position; rear shoulder sweep 53° → 38° |
| trot `trF` → `trArmF` | 48 → 56 | 30° → 25° | +0.17 in forward; stride 2.0 → 2.4 in | about unchanged |
| crawl `crF` → `crArmF` | 103 → 67 | 64° → 56° | +0.1 in forward; stride 1.6 → 1.2 in | unchanged |
| vault `vtF` → `vtArmF` | 37 → 24 | 43° → 36° | +0.17 in forward | rear shoulders 57° → 50° |

The leg timing (which legs move together) is the same in each pair; `wkArmF` keeps `wkF`'s phase offsets within 0.02 of a cycle. The
pattern: a smaller front shoulder angle places the front feet further forward, under the claw's weight, and the walk cycle is shorter
(43 frames, so faster steps at the firmware's frame rate) with a shorter stride.

### 2. Everything else gets a fixed forward-weight shift

For every posture except `calib` (so `balance`, `up`, `sit`, `rest`, ...) and every gait without an arm variant, the arm build calls
`shiftCenterOfMass(-10)`: both front shoulders −10°, both front knees +6° (the knee factor is 0.6 for a negative shift). The rear legs are
untouched. In the sim geometry this moves the front feet about 0.3 in forward and lowers them slightly (front of the body up). The value is
a constant; no serial command changes it.

The arm build's own posture table also differs. Its `balance` / `up` row is shoulders 25, 25, 20, 20 and knees 50 (stock: all 30). With the
shift that becomes front shoulders 15, rear 20, front knees 56, rear 50: a stance about 0.25 in taller than stock, with the front feet about
0.25 in further forward. Its legs-only `rest` matches stock (75 / −55) before the shift, and its head joint 1 rests at 60. Its own `wkF`
(111 frames) differs from stock, but under the arm build `wkF` is never played: `wkArmF` replaces it.

### 3. Other arm-build differences

- **Servo model:** all 16 joints are set to `P1S` (angle range 290°) instead of the stock Bittle X build's `P1L` (270°) (`OpenCat.h`,
  `espServo.h`). Pulse range (500–2500 µs) is the same, so one degree is 6.9 µs instead of 7.4 µs. If G2's leg servos are the same
  physical servos the stock build drives as P1L, every commanded angle (firmware skills and the Pi's `i` stream from the policy alike)
  would move about 7% less, and calibration offsets scale the same way. Which is true is not stated anywhere found; measure it on the
  bench after the flash (command a known angle and compare).
- **Joint 1** (the arm's lift) is limited to −10..180° instead of ±85°. During gaits it is held at 0, or 50 for any `bk` gait; the stock
  build's small head sway during gaits is off.
- **The claw** is joint 2 ("assigned to the tail joint"). It is left out of the ±3° random posture shift and is not mirrored in mirrored
  behaviours. Calibration `c-2` finds its closed point by vibration, using the IMU.
- **Lifted recovery:** the automatic `dropRec` when G2 is picked up is disabled (the skill itself is still in the table).
- **Skill table:** 85 skills instead of 93. Not checked: which eight were dropped, and what the `R` serial token (`T_ROBOT_ARM`) does.

### What this means for G2's own code (nothing changed yet)

- **The learned walk is not affected by 1 or 2.** The Pi computes the walk from `wkf_ref.npy` (stock `wkF`) and streams joint angles,
  so the firmware's gait swap and the shift never apply to it. Only the servo-model scaling would.
- **Firmware skills G2 plays are affected:** `kcarpetF` (carpet mode) gets the −10 shift; `kwkL` (turn) becomes `wkArmL`, and `kwkR` its mirror if `R`
  resolves as it does for stock skills (not checked).
- **The eased stand-up and transitions would land wrong.** `pi_pipeline/gait/standup.py` and `link/transitions.py` assume the stock
  poses (`REST_URDF_DEG` 75 / −55, `BALANCE_URDF_DEG` 30 / 30, `SIT_URDF_DEG`). Under the arm build, `kbalance` is front shoulders
  15 / knees 56, rear 20 / 50, and rest is shifted too, so the ramp's end and the firmware's pose would disagree and G2 would jump at the
  hand-over. These tables need arm-build values, chosen from the fitted attachment.
- **The `head` attachment's firmware check accepts `Bittle X+Arm`** ([`../guides/attachments.md`](../guides/attachments.md)). Given all
  of the above, the arm build is not a neutral superset; leaving it on for the head or no attachment changes every posture.
- **For a new policy:** the arm build's own answer to the claw's weight is front feet forward plus a faster, shorter walk. In sim terms that
  points to a payload profile with the claw's measured mass and position, and either the stock `wkF` reference with the policy left to
  learn the shift, or `wkArmF` decoded as the imitation reference (`build_skill_reference.py wkArmF`). Both are open choices, not decisions.

## What the page does not say

Degrees of freedom, servo model and count, payload, reach, weight, power draw, price, minimum firmware or app versions, and the
BiBoard connector/pin the claw servo uses. Resolve these from Petoi's shop page or support before any purchase decision.

## Relevance to G2 (open, not a decision)

- The arm uses the same serial skill path G2 already drives (`pi_pipeline/link/opencat.py`, `voice/skills.py`'s `SKILLS`). Five of the tokens above
  (`pickF`, `putF`, `tossF`, `showOff`, `clap`) are added to the skill table when the arm is the fitted attachment and the BiBoard answers "Bittle X+Arm"
  ([`../guides/attachments.md`](../guides/attachments.md)); none has been run on G2 yet.
- It changes the mass and front/rear balance, which the gait policy is trained against (payload study:
  [`specs.md`](../hardware/specs.md) and the proposed-build weights). The arm's weight is not published, so that needs a measurement.
- The arm build is a separate firmware, and a firmware change interacts with the BiBoard flashing and calibration state; see
  [`calibration-and-bringup-research.md`](../hardware/calibration-and-bringup-research.md).
