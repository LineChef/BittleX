# Falls at pose and gait transitions: what outside sources say (searched 2026-11-06)

Question: does Petoi (or anyone) have advice for a Bittle that falls when it goes from a walk to a pose, from a pose into a walk, or between poses, and for servos that lag and leave the body in a state the commands do not show? Our own evidence and plan: [`../plan-detail/falls-at-transitions-2026-11-06.md`](../plan-detail/falls-at-transitions-2026-11-06.md). Nothing was downloaded; page text was read as data only.

## Short answer

**Petoi publishes no guidance for this specific problem.** The official FAQ and calibration pages cover joint calibration, the gyro and the board's level calibration, and nothing on transitions or on servo lag. The community forum is gone (the old forum pages now show "This application has been discontinued"), so the threads that match (Bittle losing balance in `pee` and push-up; "why can't my Bittle walk well") cannot be read. Searches of Petoi's GitHub turned up no issue about falls at gait or posture transitions. Nobody has published a fix we could adopt as it stands. The general robotics literature does support the direction of the guards we built.

## What Petoi says that is relevant

- **Calibrate the joints** with the L-shaped tuner when a robot does not walk or stand stably, and remove the rubber toe covers ([FAQ](https://guide.petoi.com/faq-frequently-asked-questions)). The offset step is coarse: the servo gears divide the circle into 25 sectors of 14.4 deg (an offset range of about ±7.2 deg). A larger error needs the horn taken off and put back one tooth over ([joint calibration](https://guide.petoi.com/quick-reference/joint-calibration), [calibrator](https://docs.petoi.com/desktop-app/joint-calibrator)). **For us (corrected the same day):** this does NOT explain the odd leg on stand-up. A horn slipped a tooth would put the same leg at the same wrong angle every time; what is seen is a leg that is right about 98% of the time and a different leg when it is wrong. Calibration is hygiene only. The intermittent single-leg causes to separate are a lost or garbled joint command on the serial link, a servo that did not track during the stand-up surge (a voltage dip), and the firmware overwriting a joint mid-move; see the plan page.
- **Gyro:** on for self-righting, off makes slow gaits steadier; "calibrate gyroscope" (board level and untouched) resets the IMU ([FAQ](https://guide.petoi.com/faq-frequently-asked-questions)). We already run with firmware gyro balance off at idle; the IMU calibration is not something we have re-checked recently.
- **Battery:** calibration needs a fully charged pack; a pack that dies mid-process ruined one user's calibration. Nothing about weak servos from a low pack, so no support either way for the pack gate we rejected.
- **Rest button** puts the robot down and shuts the servos off and is always safe ([play with Bittle](https://bittle.petoi.com/ri-yu/7-play-with-bittle)). Old firmware had a "play dead" loop bug fixed by updating; ours (B10_260527) is recent.
- A review adds that a Raspberry Pi on the back changes the balance, and surface friction matters ([review](https://www.sciencefocus.com/reviews/bittle-robot-dog-review)). Both are true of G2 (pod, arm and claw).

## What the wider literature says (not Petoi; patents and papers, general direction only)

- **Check the state before a transition.** A patent family on legged-robot gaits describes validity checks before a transition: how many feet are in contact and whether body pitch and roll are within bounds. It notes a running robot may not be able to go straight to standing without falling, and uses transition gaits (slow-walk-to-stand) in between ([patent 10144465](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10144465)). **Matches** our pose gate (tilt and drift checked before a move) and the idea of not snapping out of a stride.
- **Do not cut the swing phase.** A biped controller ends a swing when contact is detected and blends the joint command into the next controller's command over the handoff to avoid a jerk ([arXiv 1901.08100](https://arxiv.org/pdf/1901.08100)). **Matches** the calm stop (wait for a good moment) and the eased-pose idea we parked because our rules keep a stop out of a stride immediate.
- **Servo lag is a known problem with a known remedy.** Older patents add feedback compensation proportional to the gap between the commanded and the measured joint angle, with a different gain for a leg in the air than on the ground ([US9789611B1](https://patents.google.com/patent/US9789611), [US5252901A](https://patents.google.com/patent/US5252901)). **Does not apply directly:** it needs measured joint angles, which the Pi does not get (servo feedback is echo-only over the UART). Our IMU tilt gate is the substitute.
- Learned transitions ("viability" as the objective) exist in the research ([Nature Communications 2024 via DOAJ](https://doaj.org/article/681d691c189d4fbfa72337c06b0d43da), [DeepTransition](https://arxiv.org/pdf/2306.07419)); they need sim training and do not fit a hand-tuned servo robot like this.
- Falling safely is its own literature ([Guardians as You Fall](https://arxiv.org/pdf/2310.04828)); not pursued.

## How Petoi's own firmware changes from one skill to the next (read from the public source, 2026-11-06)

Read from the public OpenCat repository (`src/skill.h`, `src/motion.h`; page text read as data, the board runs firmware B10_260527 so details may differ). This is the part that bears on falls at transitions:

- **There is no intermediate posture.** Every switch loads the new skill's FIRST frame and moves there at once. `loadFrame()` sets `frame = 0` and the old gait's phase is thrown away.
- **The move is a cosine-eased interpolation from `currentAng[]`**, the last angle the firmware wrote to each servo (not the last target), at a fixed speed ratio (`transformSpeed = 2` for everything except landing): about `maxDiff / 2` steps, so a joint that has to travel 40 deg takes 20 steps whatever the skill. Joint limits clamp, nothing else slows it.
- **So a stop out of a stride, and the start of a turn from a pose, are each one fast whole-body move from an arbitrary joint set to a different one.** Stopped mid-stride, the legs are wherever the gait left them (some feet in the air) and all eight joints race to the balance pose together; started from the stand, the turn skill's first frame is not the balance pose (left and right turns apply a +25 / -25 shoulder offset, `offsetLR`).
- **Balance is a gyro correction added to each frame** (`adjust()`), with a dead band; it is not a transition mechanism, and no gating during a transition is visible in the files read.
- The `up` posture is loaded when serial input interrupts a behavior.
- Open: the gait generator and `transform()` callers outside these two files were not read; the units of the speed ratio are described inconsistently in the comments; the Petoi forum threads on balance problems are unreadable.

**What this means:** our gate, steady check and calm stop only choose WHEN to command the next skill. None of them reduces how big the jump is, and the firmware decides that. Two levers that do, both on the Pi side (no firmware fork):

1. **Stop at a whole number of gait cycles.** The gait starts at frame 0 and repeats, so after N whole cycles the legs are back at (about) frame 0, close to where the move started, instead of mid-stride. The firmware's jump to the balance pose is then small. Needs the cycle time of each gait (kwkL, kwkR, kwkF, kbkF), measurable from the roll oscillation in our walk logs.
2. **Pre-position before a skill that starts from a pose.** Drive the legs (the Pi's own eased `i` commands) to the new skill's first frame before sending the skill, so the firmware's interpolation has almost nothing to travel. Needs the first frames (public: `InstinctBittle*.h`).

A third, bigger option (the Pi ramps from its estimate of the mid-stride pose to the balance pose itself) conflicts with the owner's immediate-stop rule and needs the gait timing as well.

## What we could not find

- Any Petoi statement on gait-to-pose stop timing, transition tuning or servo lag.
- Hobby-servo latency figures or stop timing for small quadrupeds (a further search for Arduino and ESP32 quadruped projects was not done).
- The text of the Petoi forum threads, and the OpenCat firmware source for how it moves between postures (not read; worth reading `OpenCat.ino` and the skill transition code before designing an eased stop).

## What this changes in our plan

1. **The calibration check is hygiene only** (a slipped horn gives a constant error, not a random leg 2% of the time). Do the Petoi joint and gyro calibration once, but do not expect it to explain the odd leg.
2. Keep the pose gate and the steady-before-pose-change check: the literature calls for the same pre-transition validity check.
3. The eased stop remains a candidate; read the firmware's own transition code first.
