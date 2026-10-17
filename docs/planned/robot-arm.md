# Petoi robot arm (Bittle X+Arm)

Research 2026-10-17. Source: Petoi docs, <https://docs.petoi.com/extensible-modules/robot-arm> (the page is thin: it gives
no specs; everything below is what it states, and the gaps are listed at the end). **G2 does not have this module**; this is
reference only.

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

## What the page does not say

Degrees of freedom, servo model and count, payload, reach, weight, power draw, price, minimum firmware or app versions, and the
BiBoard connector/pin the claw servo uses. Resolve these from Petoi's shop page or support before any purchase decision.

## Relevance to G2 (open, not a decision)

- The arm uses the same serial skill path G2 already drives (`pi_pipeline/link/opencat.py`, `voice/skills.py`'s `SKILLS`), so the
  tokens above could be added there if the module is ever fitted.
- It changes the mass and front/rear balance, which the gait policy is trained against (payload study:
  [`specs.md`](../hardware/specs.md) and the proposed-build weights). The arm's weight is not published, so that needs a measurement.
- The arm build is a separate firmware, and a firmware change interacts with the BiBoard flashing and calibration state; see
  [`calibration-and-bringup-research.md`](../hardware/calibration-and-bringup-research.md).
