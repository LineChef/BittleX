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
- The speed findings come from two more files at the same commit, fetched from `raw.githubusercontent.com` over HTTPS and read as text only.
  - `src/espServo.h`: SHA-256 `23545a21…7584`, 14000 bytes, the servo driver setup, with no speed control in it.
  - `src/motion.h`: SHA-256 `5cac3e28…5375`, 32863 bytes, holds `transform()`.
  - Each is kept in its own folder under `~/g2_data/` outside the repository.
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

Arm speed series
----------------

How fast the lift joint and the claw jaw can be driven decides what a throw can do, and nothing recorded gives it. `transform()` in `motion.h` moves every joint of a frame together and finishes them together: it takes the largest joint change in degrees divided by the frame's speed (the speed byte over 8) in steps, each step an eased interpolation followed by a fixed 8 millisecond wait, so the speed byte sets the duration and the servo write time comes on top. A direct `i` command uses a global speed (default 2), and the byte in a skill frame is an int8, so 127 is the most a frame can ask. The commanded rate is about 125 degrees a second per unit of speed ratio at most; the servo's own limit is what the series looks for. This is read from the source and not yet measured on the board.

- The claw look moves the arm at 60 degrees a second by sending one position at a time from the Pi, which cannot go much faster (a run dropped a byte above about 1 KB a second). The series therefore plays a data skill (`K`) that the board steps itself, with nothing written to the port while it plays.
- `g2armspeed --series lift --speed N` (`python -m pi_pipeline.behavior.arm_speed_test`) runs one step: the legs stay at the angles the board reports, the lift goes to its start, up to 120 degrees at speed N, holds half a second and comes back down slowly. The jaw series (`--series jaw --jaw-open A --jaw-closed B`) raises the arm slowly first, opens the jaw, closes it at speed N, opens it at speed N, returns it and lowers the arm. The two jaw angles have no defaults because their sign and range differ between the arm skills.
- Steps are 4, 6, 8, 12, 16, 24, 32, 48, 64, 96 and 127, the first about the claw look's pace. The tool refuses a step more than one above the last logged run of the series, a step above a run that stalled, hit something or was unsafe, and a step above a run with no recorded observation. `--dry-run` prints the plan and touches nothing; `--allow-jump` skips the check and is for a deliberate jump only.
- Logged in `~/g2_runs/arm_speed/`: the send time, the body's IMU trace, the pack percent, the plan with each step's nominal time and upper rate, and the typed observation (followed, lagged, stalled, hit or unsafe, with the sound and a note). The real arm position is not available, so the observation is the main data.
- Before the first run the arm is moved by hand through its whole range to check its clearance over the pod and Pi stack.
- `g2armspeed --report` prints the runs so far (speed byte, result, body tilt, pack) and the next step, and sends nothing. `g2armspeed --session --series lift` runs several steps in one process: G2 is laid in rest between steps, the next speed is offered before each, and the reply is the go for that run (Enter runs it, a number runs that speed if the one-step check allows it, `s` stops).
- `g2jawrange --to ANGLE` finds the two jaw angles by eye. It stands G2, raises the arm the way the claw look does, steps the jaw from where it is toward ANGLE in steps of at most 15 degrees (within 60 degrees of the start, at most 12 steps) printing each commanded angle, brings it back, lowers the arm and rests him. The angles typed in afterwards (open, closed, where it stopped) become the `g2armspeed` jaw command line. The board reports commanded angles, so the eye is the measurement. Start with a small ANGLE.

Measured on G2 by eye, with the legs held and the body trace as a check on timing (the lift and jaw speeds and ranges are under "The claw servos" below):
- Speed 0: a frame's speed byte divided by 8 is the ratio passed to `transform()`, and a ratio of 0 means no interpolation steps, so every joint is sent its target at once (`motion.h`, read from the source). `g2armspeed` accepts 0 only with `--allow-jump`. Petoi's own `tossF` uses speed 0 for its release frame.
- `--from-attention` plays a run from the attention pose (the claw look's own entry, legs straight, which prevents most of the servo sag) with rest sent straight from it. The `both` series plays the lift up and the jaw open, closed and open again at one speed in one short run.
- Body trace: the roll and pitch stayed within a few degrees in every run from the attention pose. Runs from a stand with the arm raised pitched the body nose-up by about 22 degrees, and one jaw sweep with the arm raised for about 8 seconds fell as the legs sagged.

The claw servos
---------------

What was learned about the lift joint and the jaw on G2, by eye and from the firmware source. The board reports the angles it was last told to hold, never where a joint is, so every number below is a commanded value checked by eye.
- Jaw direction: 0 degrees is closed and positive angles open it. 0 to 60 degrees works, and the jaw was still opening wider at 60, so the end of its range is not found. Petoi's own `pickF` opens it to 65, and its `tossF` holds a ball at -78 to -100 (a closed jaw squeezing an object it cannot close on) and releases by going to 0.
- Jaw holding an object: `pickF` ends with the lift at 0 and the jaw at 0, the object held with the jaw commanded closed.
- Jaw speed: every speed byte from 4 to 127 followed. 127 looked faster than the rest but slower than the snap in the Petoi calibration tool, and speed 0 (no interpolation, the target sent at once) was faster still. The calibration tool's snap and the speed 0 snap are the claw's top speed.
- Lift speed: every step from 4 to 127 followed smoothly, with no lag, no bang at the top and nothing unsafe, so 127 is the working maximum. Speed 0 was not faster for the lift.
- Lift range: the lift reached 135 degrees by direct command, in steps of 5 past 125. A data skill carries 125 at most (an angle in a skill frame is one byte clipped at 125), so a skill move that includes the arm lowers the lift to 125 and it is set again by `i1 135` after it. Beyond 135 was not tried.
- Skill frames cannot carry the claw's full reach: any scripted movement that needs the lift above 125 sets it by a direct command after the skill.
- Hand posing: moving the limbs by hand with the servos released (`d`) is not seen by the board. A read with the claw raised and the legs folded away from rest still reported the rest angles, within about 2 degrees of noise, so a pose cannot be recorded that way. Poses are found by commanding them (the pose editor below).
- Gyro balance: with the firmware's gyro balance on, the board moved the legs to level the body, so the angles it reported were not the angles sent (the front shoulders read 20 after 15 was sent). The pose editor turns it off for its session.
- Weight on the claw: a full bow (Petoi's `buttUp`, front shoulders 90 and knees -60) lifted the front feet off the floor and left the body on the claw and the rear feet. The claw takes the front's load in a deep bow, so a bow that keeps the front feet down needs the front legs less folded.
- Standing time: the legs can sag after about ten seconds standing, so each pose is reached in one move, not in slow steps.

The backward catapult
---------------------

`g2catapult` (`python -m pi_pipeline.behavior.catapult`) plays one run of the move as a data skill the board plays itself, built from the legs the board reports.
- The frames: a bow (Petoi's `buttUp` pose: rump up, front legs bent), then one swing frame in which the legs go to the pose of Petoi's `launch` (front legs tall, rear legs folded, body pitched up), the lift joint swings to the peak given, and the jaw opens a few degrees, then the jaw opens fully at speed 0, then the legs, arm and jaw return slowly.
- The release time: a frame's joints finish together and ease to a stop at its end, so the jaw is opened inside the swing frame. The object leaves when the jaw has opened past its width: early in the frame for a large `--jaw-delta` and late for a small one. That angle is the knob to tune.
- Scale: `--amount` (0.1 to 1) is how far the legs go from where they stand toward the bow and the launch pose, and `--lift-top` and `--speed` set the arm. The defaults are small (0.3, 60 degrees, speed 16).
- Stages: `bow`, then `swing` (the jaw held shut), then `throw` (the release). A stage is refused until the one before it has a logged run with the body ok. `--pick` plays `pickF` first and the move from where it ended.
- Logs: `~/g2_runs/catapult/` has the plan, the body trace and the typed landing note. `--dry-run` prints the frames and touches nothing.
- Setup: a soft surface and clear floor behind G2 and a hand near. The arm passes over the pod and Pi stack, and tipping over backward onto the pod is the main risk.
- Progress (the launch sequence is built one pose at a time with the pose editor, each pose played from the stand at the stand-up's pace):
  - Pose 1, the bow: the front legs squatted (shoulders -9, knees -3), the back legs extended (shoulders -19, knees 84), the claw closed (jaw 0) and the lift at 135. It is saved as `bow` in `pi_pipeline/behavior/scripts/poses/bow.json` and played by `g2script bow` after the eased stand-up. It worked on the floor: pitch 22 degrees nose-down, close to the look in the reference photo.
  - The first tries that did not work: Petoi's `buttUp` bow played at 30 and 50 percent barely moved, at 100 percent it lifted the front feet off the floor, and the same bow played all at once from a stand fell G2 over backward onto the pod.
  - Pose 2, the launch: the front legs straight and tall (shoulders 20, knees 100), the rear legs crouched (shoulders 70, knees -35), the claw at 125 with the jaw closed, saved as `launch` in `scripts/poses/launch.json`. The transition from the bow, `g2script catapult_launch`, drops the claw as the legs begin to rise (it is already on the floor in the bow, so it cannot drop earlier) and swings it back up to 125 at speed 127 as they finish; it ran from rest through the stand-up and looked right to the person watching.
  - The release: `catapult_throw` is the same sequence with the jaw opening a few degrees inside the lunge frame (`--set lunge.jaw=30` changes it per run), then fully open at speed 0. A frame's joints ease to a stop at its end, so the release has to happen inside the swing; the object leaves when the jaw has opened past its width, so a larger angle releases earlier in the swing. The first estimate is 26 degrees, from about 22 degrees for the 1 inch cylinder; `--pick` plays `pickF` first.
  - Checkpoint 1: the throw that works, a forward lob that the slow-motion video showed leaving the claw at about 60% of the lunge, 35 degrees above horizontal, is `catapult_throw_checkpoint1` (the jaw opening 8 degrees inside the lunge, the best of 26, 16, 12, 10 and 8), also tagged `catapult-checkpoint-1`. It does not throw backward: the arm reaches about 40 degrees above horizontal forward and never swings back over the body.
  - Tuning variants for a farther throw: `catapult_throw_b` sends the legs 70% of the way to the launch pose before the whip.
  - `catapult_throw_c` jumps the legs and arm at speed 0 and opens the jaw one pause later (`--set lunge.delay_s=0.1` moves the release).
  - `catapult_throw_d` uses a deeper rear crouch, the pose `launch_deep`.
  - Checkpoint 2: the legs 10% of the way before the whip (`catapult_throw_checkpoint2`, 15 and 18 inches against checkpoint 1's 12; 30% threw 17 once and 70% threw 4, so less leg motion before the whip throws farther).
  - Speed-0 lunge: sending the legs and arm to the launch pose at speed 0 and opening the jaw one pause later threw 22, 21 and 18 inches (test C), and with the deeper rear crouch 24, 23, 17 and 23 inches (test D).
  - Checkpoint 3 keeps both: the lob, `lob` (test C), throws higher on a more arched path, and the line drive, `line_drive` (test D, the pitch 37 to 38 degrees nose-up) throws farther on a flatter path, so the lob suits putting the cylinder onto a target and the line drive distance. They were named for the two kinds of throw, since the motion is a forward throw and not a catapult. Git tag (from before the rename): `catapult-checkpoint-3`.
  - Old look: the survey's inspect bow is the same `buttUp` pose, and the firmware `sit` (front shoulders 45, knees 45, rear shoulders 105, knees -45, also the last frame of `gdb`) is the nose-up pose that follows it; the launch pose is still to be found the same way.
  - Still to do: the launch pose (front legs extended, rear legs folded, the arm swung to its peak), the release inside that swing, then playing the bow and the launch from a hand-placed object, joining them to the pick-up, and adjusting until the throw is reliable.

Height and distance of the throw
--------------------------------

What the throw tests showed about what makes the cylinder go higher or farther, kept for later skills that need to aim a throw (a basketball shot, for example). The throws are the forward lob of the catapult launch sequence, played from the stand with the cylinder in the closed claw. Distances are measured from a fixed point to the first landing, by eye with a ruler, so each carries a few inches of scatter between throws of the same script.
- Two things set where the cylinder goes: the speed of the claw at the moment the jaw lets go, and the direction the claw is moving then. The speed comes from the arm's swing and from the body's motion, which adds to it. The direction depends on how far round the swing the claw is at the release and on how far the body has pitched nose-up by then.
- Release time: the jaw opens inside the lunge frame (an angle that opens later for a small value) or in the frame after it at speed 0 (a pause that moves the release later). The earlier the release in the swing, the lower and flatter the launch; the later, the steeper. The slow-motion video of the first throws showed the cylinder leaving at about 60% of the lunge, about 35 degrees above horizontal, with the arm never swinging back over the body, so the throw is forward.
- Leg motion before the whip: the less the legs have moved when the arm whips, the farther the throw. With the legs 70%, 50%, 30% and 10% of the way to the launch pose before the lunge, the throws went 4, 12, 17 and 15 to 18 inches. The likely reason is that the body's rotation is then still to come when the arm swings, so the body's speed adds to the claw's.
- Lunge speed: sending the legs and arm to the launch pose at speed 0 (every servo at its top speed for the whole move, with no ease in or out) threw farther than the eased lunge (18 to 22 inches against 15 to 18).
- Rear crouch depth: a deeper rear crouch in the launch pose (rear shoulders 80 and knees -45, instead of 70 and -35) pitches the body about 6 degrees further nose-up (37 to 38 degrees against 30 to 32) and threw farther and flatter (17 to 24 inches, average about 22). The normal crouch threw higher and more arched (18 to 22 inches, average about 20). Both kept as checkpoint 3: an arc for a lob onto a target and the flatter throw for distance.
- What the body traces show of the difference between the two (seven throws, the IMU read about five times a second): the bow pitch is the same (about 24 degrees nose-down), the lunge begins at the same time after the send, and the final pitch is 30 to 33 degrees nose-up for the normal crouch against 37 to 38 for the deeper one. The roll stays within about 1 to 4 degrees for the deeper crouch and reaches 4 to 7 for the normal one, so the deeper crouch is also the more symmetric pose. The pack percent (77 to 82) did not differ. The IMU cannot show the launch angle: the release happens in about 0.1 s, between two samples.
- Why body pitch alone does not explain it: with the release at the same point of the arm's swing, a body pitched 6 degrees further nose-up turns the arm and the claw's velocity 6 degrees steeper, which would give the deeper crouch a higher arc, the opposite of what was seen. Both throws release 50 ms after the lunge command, at which time the arm has moved the same distance, because every servo runs at its top speed from the same instant.
- Explanations not yet tested: the deeper crouch folds the rear legs further (the rear knee travels 117 degrees against 107) and so pushes the body forward over the front legs, adding forward speed to the claw at the release, which gives a flatter and longer throw; the cylinder is released by slipping out of the jaw under the lunge's acceleration before the open frame, in which case the grip and the acceleration set the release; or the scatter of a few inches between throws hides a smaller difference than it looked. Slow-motion video of both throws, with the claw's path and the launch angle measured frame by frame, and throws with only the rear crouch changed would separate them.
- Controls to try for aiming: the release time (the jaw angle or pause) for the launch angle, the rear crouch depth for body pitch, and the share of leg motion before the whip for speed. Varying one at a time, with the launch angle and the distance recorded for each, would give a table to aim from.

Authoring a scripted movement
-----------------------------

A new movement is written as keyframes and played by the board as one data skill. Two tools do it: the pose editor finds each pose by eye, and the player strings the poses into a script.
- The pose editor (`g2poseedit`): `g2poseedit start [--attention | --from-rest]` stops the voice service and stands G2 up (or lays him in rest and starts there, with no standing time), `g2poseedit set fkn=-15 rsh+=10` eases him into the changed pose, `g2poseedit show` prints the 16 angles and the tilt, `g2poseedit save NAME` keeps the pose and `g2poseedit end` lays him in rest and starts the voice service again. Nothing is released and every angle is one the editor commanded; a limb moved by hand cannot be recorded, because the board reports the angles it was last told to hold.
- More commands: `g2poseedit step fsh -15` keeps stepping one joint 15 degrees a tick in one run (up to `--count`, until the joint's range) so the person can call stop, `load NAME` goes to a saved pose, `diff A B` lists the joints that differ between two poses, and every reply shows the session age. `--speed 0 --allow-instant` jumps to the target with no transition. A lift above 125 is set by a direct command after each move, because a skill frame carries 125 at most. `save` falls back to the last commanded pose when the board cannot be read.
- Helpers: `g2poses` copies the poses saved on the Pi into `pi_pipeline/behavior/scripts/poses/`, and `g2script --list` lists the scripts and poses.
- Joint names: `pan`, `lift`, `jaw` for the arm, `fls frs brs bls` for the shoulders and `flk frk brk blk` for the knees (front left, front right, back right, back left). Groups: `fsh rsh fkn rkn sh kn legs arm`. A change is `name=angle`, `name+=n` or `name-=n`. Every angle is clipped to its joint's range and one command moves a joint 70 degrees at most.
- The player (`g2script NAME`): a script is `pi_pipeline/behavior/scripts/NAME.json`, a list of frames, each with a pose (saved, or `start`, or inline `angles`), the joints it takes from it, a speed byte and a pause. `--amount` scales every pose from the starting angles, `--attention` plays from the attention pose, and `--dry-run` prints the frames. The run is logged in `~/g2_runs/scripts/` with the body trace.
- Poses are kept on the Pi in `~/g2_runs/pose_edit/poses/`. A finished movement's poses are copied into `pi_pipeline/behavior/scripts/poses/` and its script committed, so it deploys.
- The workflow is the `author-movement` skill: pose by pose with the person watching, short stands (the legs can sag after about ten seconds), then the script played small first and raised in steps.

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

Pick-up bisect
--------------

If `g2armskill pickF` still does not play in full after the link's silence fix, `g2pickbisect --variant plain|gb|gP|j|link` (`python -m pi_pipeline.behavior.pick_bisect`) separates the skill from what the Pi writes around it. Each run stands G2 up the eased way, writes `kpickF` straight to the port (like a hand-typed `printf`, bypassing the link), writes at most one extra command 100 milliseconds later and nothing else for 10 seconds, while the IMU is only read. The person typed in what the claw did.

- `plain`: nothing extra. The reference, expected to play in full. Run it first.
- `gb`, `gP`, `j`: one extra byte pair written behind the token, expected to cut the skill short (the old link wrote `gb`, the older test tools `gP` and `j`).
- `link`: the token goes through the link's own `send`, the fixed path `g2armskill` uses, expected to play in full.
- If `plain` plays and the others cut it, the cause is confirmed. If `plain` does not play, the stand-up path or the board is the next place to look.
- Logged in `~/g2_runs/pick_bisect/` with the body trace and the typed result.

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
  - Status: the lift and jaw speeds are measured and the first pose (the bow) works; the launch pose and the release are still to be authored. The release angle and the claw's opening delay are the two numbers to find.
- Whether the skills throw only when the claw holds an object. Nothing read says so: the frames are fixed angles, and nothing read shows the claw sensing a load, so the same motion is inferred to play empty or loaded. Not verified; the held-object runs in step 5 of the test plan would settle it.
- Whether the claw angle at the release means open or closed in the toss frames (negative values in `tossF` and `hunt`, positive in `pickF`).
- Whether `toss` throws to the left or the right on G2's claw, since both names play the one motion.
- Whether the throw clears the pod and the Pi stack, which sit behind the claw.
