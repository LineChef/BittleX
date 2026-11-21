---
audience: contributor
kind: reference
---

# Arm skills

This page records what Petoi's Bittle X+Arm firmware does when it is sent the arm's throw and launch skills (`klaunch`, `ktossF`, `ktossL`, `ktossR`, and the related `khunt`, `kshowOff` and `kclap`), what the repo has to do to use them safely, and the order in which they are tested on G2. It is for anyone changing the arm's skill table or running the first hardware test of these skills.

Source of the findings
----------------------

The skill data and the lookup code were read from Petoi's official BiBoard firmware repository, which Petoi's own OpenCat page links to.

- Repository: `https://github.com/PetoiCamp/OpenCatEsp32-Quadruped-Robot` (MIT licence).
- Pinned commit: `f5aba6b9cb7e4f2062f77365fbcd0c388acf32ef`.
- Files read, with SHA-256: `src/InstinctBittleESP_arm.h` (cd0a1c7c...00f6, 111431 bytes), `src/skill.h` (a68890f9...03de, 21281 bytes), `src/voice.h` (1b71141a...881b, 13912 bytes), `src/robotArm.h` (72b04bd0...b804e, 819 bytes), `src/OpenCat.h` (5fe49684...b191, 27417 bytes).
- The skill-abort finding comes from `src/reaction.h` (SHA-256 `6ff5ec5b…ddd0`, 67942 bytes) and `src/io.h` (SHA-256 `0e06a1d8…d264`, 1398 bytes) at the same commit, fetched from `raw.githubusercontent.com` over HTTPS and read as text only; `skill.h` and `OpenCat.h` matched the hashes recorded above. The fetched copies are in `~/g2_data/firmware_src_f5aba6b9` outside the repository.
- The files are C header text, read as data and never compiled or run. The arm skill arrays are byte-identical to the stock `InstinctBittleESP.h` already kept for the sim reference.

How the firmware finds a skill
------------------------------

`SkillList::lookUp(key)` in `skill.h` takes the token without its `k` and walks the skill table in order. An entry matches when its name equals the key, or when its name does not end in `F`, is not `bk`, starts with the key minus its last letter, and the key's last letter is `L`, `R` or `X`. The first match wins.

- `ktossL`, `ktossR` and `ktossX` are not separate skills. The table has `toss`, `tossD` and `tossF` only, so all three resolve to the generic `toss`. They play the same motion.
- The same holds for `kpickL` and `kpickR` (both play `pick`) and `kputL` and `kputR` (both play `put`). Only the `F` and `D` variants of pick, put and toss exist as separate arrays.
- `klaunch` matches the `launch` array exactly. `launch` and `tossD` hold identical data, which agrees with Petoi's note that launch is "toss down".
- The arm firmware's ten voice-module commands are `kpickF`, `kputD`, `khuntL`, `kshowOff`, `kputL`, `ktossL`, `klaunchL`, `kclapL`, `ktossF` and a calibration. The "Shoot" command (throw forward) is the tenth voice slot, which is `klaunchL`, so shoot plays `launch`.

A behavior skill is aborted by any serial byte
----------------------------------------------

Behavior skills (`pickF`, `pickD`, `put`, `launch`, `toss`, `hunt`, `showOff`, `clap` and the tricks) are played one frame at a time, and `perform()` in `skill.h` checks the serial port before each frame. If any byte is waiting there (from the wired serial port, the voice module or Bluetooth) the skill prints "Behavior interrupted", stops, and `reaction.h` loads `up` in its place, which is the `up` the board echoes. Gaits and postures are not checked this way.

- The problem: until this was found, every arm skill sent from the Pi was cut off at or before its first frame. The link wrote `gb` straight behind each skill while the arm profile had the gyro balance off, and test tools polled `j` or sent `gP` while a skill played. A bare `kpickF` typed by hand with nothing behind it played in full, and the claw opens and closes on direct `i2` commands, so the skill and the claw were never the fault. The earlier empty-claw runs of `launch`, `toss`, `tossF`, `hunt` and `showOff` were cut short the same way, so they say nothing about what those skills do.
- The fix: after a behavior skill the link stays silent (`G2_SKILL_QUIET_S`, 10 seconds at most) until the board echoes the completion token `k`; held toggles go out afterwards and reads are dropped. The gyro balance is also back on by default (the firmware default), so the link no longer writes a `gb` behind skills at all. Details are in the link specification.
- Tools: `g2armskill --joints N` reads the joint angles while a skill plays, which is itself a read and so is dropped during the quiet window; it cannot observe a skill that way.
- Not yet run on G2: the fix is in the repository and not deployed. It is confirmed on the robot by sending `pickF` with nothing written behind it, once after the eased stand-up and once with a `gb` written 100 milliseconds after (which should cut it), and then through `g2armskill`.

What each skill does to the body
--------------------------------

Measured from the frames with the same scores as [Disabled moves](disabled-moves.md): the largest front-to-rear difference of the shoulder and knee angles, and the largest left-right difference within a leg pair. The arm columns are pan, lift and claw.

- `launch` (and `tossD`): five frames. Shoulder difference 39, knee difference 69, left-right 0. The arm lifts from 23 to 90 and the claw opens to 25 for the release. The mildest of the group, close to the `pickF` lunge the ball chase already uses.
- `toss` (what `tossL` and `tossR` play): five frames. Shoulder difference 68, knee difference 68, left-right 12. The pan swings from -74 through 12 to 60 with the lift at 110, the rear legs sit back (shoulders about 100, knees about -55) and the claw opens to 120 at the end. The throw goes to one side, the positive pan side.
- `tossF`: five frames. Shoulder difference 73, knee difference 115 (front knees to 78, rear knees to -37), left-right 0. The lift swings 0 to 125 while the claw goes from -100 to 0. The strongest forward lean of the group, beyond the stretch kept as borderline. With about 46% of the pod payload over the front feet this is the skill with the most nose-over risk.
- `hunt`: seven frames. Shoulder difference 24, knee difference 20, left-right 0. A quick grab with the claw to -120 and back.
- `showOff`: five frames. Shoulder difference 72, knee difference 108, left-right 0. The arm lifts to 95 to 105 and pans a little either side with the rear legs sat back.
- `clap`: twelve frames. Shoulder difference 129, knee difference 134, left-right 97. The wave that flipped G2 scored 129 left-right, so `clap` needs its own audit before it is used.

What is in the code today
-------------------------

- The arm's skill table in `pi_pipeline/attachments/__init__.py` offers the tokens to the conversation when the arm is fitted and the board answers "Bittle X+Arm". The empty-claw test has been run on G2 (see Hardware results below); no held-object run is recorded.
- None of the toss or launch tokens is in `DISABLED_SKILLS`, so a spoken request can run them. They stay enabled for voice; the test below is how they earn that.
- The left and right names (`toss_left`, `toss_right`, `pick_up_left` and the others) are offered as if they had a direction. They play the generic skill, so their descriptions say so.
- `python -m pi_pipeline.behavior.arm_skill_test --skill NAME` (`g2armskill NAME`) plays one skill with the body watched and writes a JSON file to `~/g2_runs/arm_skills/` with the verdict, the whole IMU trace (time since the skill was sent, pitch and roll), when the body first moved and when it tilted most, the wall-clock send time (to line up a phone video), the pack percent before and after, the claw joint's angle before and after, the object, and the landing record typed in after the run. Options: `--object NAME`, `--object-oz`, `--object-in`, `--floor LABEL`, `--pictures N` (claw-camera pictures after the swing, off by default because whether the camera stream disturbs the IMU stream is not yet known) `--joints N` (read the joint angles N times, about every 0.6 seconds, while the skill plays and log them as `joints_during`: the board reports commanded angles, so this shows whether the skill commands the claw joint at all; reading them stops the IMU print, so the trace has gaps) and `--no-prompt`. A skill that should move the body but moves it under 3 degrees is reported as `no_motion`, not `ok` (`hunt` is exempt). The pick skills `pickF` and `pickD` are accepted too: run with the object on the floor in front of the claw, the claw joint's angle is read after the run (part-open means an object is held, fully closed means nothing).

Test plan for the next hardware session
---------------------------------------

Run after the attentive-bout check, one skill per run, with a person's go before each.

1. Preconditions: the arm fitted, the BiBoard powered on and answering "Bittle X+Arm" (the test refuses and sends nothing when no IMU frames arrive), the claw calibrated, the pack above the 30% gate, G2 on his feet on hardwood, hands near, nothing in the claw, a soft surface in front, a quiet room.
2. Order, mildest first: `launch`, `toss`, `tossF`, `hunt`, `showOff`, then `tossL` and `tossR` once each to confirm they play the same motion as `toss`.
3. Each run: `g2armskill launch` stands him up, reads the tilt, sends the skill, watches the IMU for 6 s, sends `gb`, reads the tilt again and lays him in rest. The result is `ok` (under 30 deg from where he stood), `lean` (30 to 45), `tipped` (45 or more) or `fell`.
4. Stop the block at the first `tipped` or `fell`. A `lean` is repeated once before going on.
5. Held-object runs, only after the empty runs pass: `kpickF` with the ball, then `launch`, then `toss`, with a hand under the claw.
6. Pass: three empty runs in a row of each skill with no fall and no tilt of 45 deg or more. A skill that tips him is added to `DISABLED_SKILLS` the same way as the wave.
7. Watch and record: whether the claw opens or closes at the release (the claw sign differs between `pickF` and `tossF` in the frames), where the throw goes, how far the ball travels, and any servo that stalls.
8. `clap` is not in the block. It is tested only with `--allow-clap`, on its own, after the others.

Hardware results
----------------

- Empty-claw body test: `launch`, `toss`, `tossF`, `hunt` and `showOff` each scored ok (G2 stayed upright). `tossL` and `tossR` play the same motion as `toss`, as the firmware lookup predicts. The state page records the run.
- Throw distance: none of `launch`, `toss` or `tossF` was seen to throw an object any distance; the motions look too slow and small for a throw.
- Loaded-claw pick-up tests: `pickF` and `pickD` were sent after the eased stand-up and did not play (the body stayed within 3 degrees, the commanded joints never changed and the claw never moved), and `launch` pitched the body 13 degrees but never opened or closed the claw. Direct `i2` commands do open and close the jaws, and a bare `kpickF` typed with nothing behind it played in full. The cause is in the firmware: a behavior skill checks the serial port before every frame and any waiting byte (the link's `gb`, a `gP`, a `j` read) aborts it and the board stands up instead. So every arm skill sent with a byte right behind it is cut off at or before its first frame.
- Not recorded: the per-run result lines are written on the Pi in `~/g2_runs/arm_skills/` and are not synced to the Mac, so the tilt numbers and timings are not in the repository. No run with an object in the claw is recorded, and no throw distance was measured.

Open questions
--------------

- How much speed a body lunge can add to the throw. An arm swing alone is estimated to reach about 1 to 2 feet; a lunge that drives the shoulder forward as the arm swings, timed with the release, is the planned way to add launch speed. It is studied in simulation first, then on the floor with the pitch trace watched, since a lunge is also the likeliest way to nose over.

- Whether a backward catapult motion works.
  - The motion: from a play bow with the object in the claw, the lift joint swings to about 120 degrees while the rear legs fold and the front legs extend, and the claw opens before the top of the arc so the object lands behind G2.
  - Why backward: the nose-up body pitch tilts the arc up and back, and the object leaves heading upward. A forward throw swings the claw down and forward, so the object would leave heading toward the floor.
  - Evidence so far: Petoi's demo clip pitches the body up about 40 degrees in under 0.2 seconds as the arm snaps up, and its second release sends the object up and toward the rear.
  - First check: the arc passes over the pod and Pi stack, so their clearance comes first.
  - Status: not built or simulated, and planned only after the claw's speed and release time are measured. The release angle and the claw's opening delay are the two numbers to find.
- Whether the skills throw only when the claw holds an object. Nothing read says so: the frames are fixed angles, and nothing read shows the claw sensing a load, so the same motion is inferred to play empty or loaded. Not verified; the held-object runs in step 5 of the test plan would settle it.
- Whether the claw angle at the release means open or closed in the toss frames (negative values in `tossF` and `hunt`, positive in `pickF`).
- Whether `toss` throws to the left or the right on G2's claw, since both names play the one motion.
- Whether the throw clears the pod and the Pi stack, which sit behind the claw.
