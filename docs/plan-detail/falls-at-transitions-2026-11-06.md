# Falls at pose and gait transitions (HIGH PRIORITY, opened 2026-11-06)

**State at the end of the first hardware session: nothing is proven.** The guards below are built, tested in code and deployed, but no A/B round has valid evidence yet. Do not write the approach into the project-wide guidelines until one variant clearly beats the baseline (owner's rule); this page is where it gets written up from.

## What we know

- **Logged falls** (goal journal, 154 attempts): 18 fell; 13 of the 18 were during a turn (`search_turn` 9, `turn` 3, `wall_turn` 1), 7 of the 9 `search_turn` falls started right after a look or claw look, 1 plain walk. Median pack at a fall 66% vs 75% otherwise (weak), so a pack gate was rejected (servo sag is common; it would stop most runs).
- **The logged count is a floor.** Most falls end an attempt without being recorded (owner, 2026-11-06). Compare variants on IMU tilt swings and near falls, not only on logged falls.
- **Two stops out of a turn** (`kwkL` for about 1 s, then an immediate `kbalance`, over within a second) on 2026-11-06 fit "walking to a pose".
- **The drill's own falls** (do not count them against any variant): the first drill sent a turn from the attention pose without standing him up (fixed); a BiBoard voice-module move (`pee`) started on its own mid-round; one round ran with the BiBoard silent (no IMU frames, firmware "did not answer"), so the guards did nothing and "10 clean" was void.
- **Valid baseline so far** (no guards): about 3 falls in about 10 cycles, all in the attention pose, the stand-up from it, or the claw look, not in the turns.
- **`both`** (pose gate and calm stop): one valid round, fell going into the attention pose in cycle 2 (before the "steady before a pose change" check existed). The next `both` round was void (silent board).
- **Leg check** (`SerialRobot.leg_check`, log `~/.local/share/g2/leg_check.jsonl`): every logged stand-up read all eight leg joints at their stand angles, so a lost joint command is not the cause of the odd leg angles seen on stand-up. The Pi gets no servo position feedback (`f` is echo-only over the UART and leans him), so a servo that was commanded right but lags can only be seen through the IMU tilt.
- **The BiBoard's own voice module starts moves** (`not_from_pi` in the command log: 127 rows in 3 days, including `pee`, `hi`, `ck`, `bx`, `fiv`, `wkArmF`). Some falls may be those. Sending `Xa`/`XAd` to silence it breaks its voice commands (rule), so use a quiet room for tests.
- **Claw partly open at rest** (new on 2026-11-06): nothing in the code commands the gripper joint (the claw look drives joints 0 and 1). Read the commanded angle of the claw joint at rest with `j`: closed on the board but open in the hand = mechanical (horn slipped, jolted by falls); open on the board = send a close.

## Built for the odd leg (lower priority than the transition falls; it is rare)

- `leg_check` now corrects: a leg joint the board holds more than 4 deg off its stand angle after a stand-up is driven back (just those joints, twice at most, read back), and the pack voltage at the stand-up is logged with it (`leg_check.jsonl`: `bad`, `fixed`, `volts`). `G2_LEG_CORRECT=0` makes it report only. `g2oddleg [note]` flags an odd leg the moment it is seen (`odd_leg.jsonl` on the Pi, with the last leg checks attached).

## What is built (all `unproven`; `G2_POSE_GATE=0` and `G2_STOP_CALM=0` switch them off)

- `SerialRobot._gate`: before a walk or turn that follows a pose change, lower the claw, read the real tilt twice (0.25 s each), compare with the last good stand (`_stand_tilt`) and check the drift; re-seat the legs (attention pose and up, `recover_sag`) up to twice; then go anyway, logged.
- `SerialRobot._settle_before_pose`: before a pose change within 6 s of a move, wait up to 1 s for a steady body.
- `SerialRobot._calm_before_stop`: a firmware move waits up to 0.4 s for a calm moment before its stop (not for gyro-stopped turns, waiting would turn them further).
- The claw look is the look everywhere with the arm fitted (`behavior/claw_survey.py`).
- `behavior/transition_drill.py`: `python -m pi_pipeline.behavior.transition_drill --variant baseline|calm|gate|both --cycles 10` on the Pi with the voice service stopped (on the owner's go, hardwood, hands near). A cycle is attention pose, a claw look, the back-legs-first stand-up, a turn, a turn back, no rest. It stops at the first fall, prints the IMU tilt through every phase, counts near falls (swing of 20 deg or more) and flags a round as void when the board started a move on its own.

## Outside sources (searched 2026-11-06)

Petoi has no published advice for this; the old forum is gone. The findings, and one useful pointer (its calibration pointer, a slipped horn, was ruled out as the cause of the odd leg: that leg is right about 98% of the time and it is a different leg each time), are in [`../research/falls-at-transitions-outside-sources-2026-11-06.md`](../research/falls-at-transitions-outside-sources-2026-11-06.md).

## What the firmware does at a transition (the main lever)

Read from the public OpenCat source (details in the research page): a skill switch loads the new skill's first frame and jumps there by a cosine-eased interpolation from the last written joint angles at a fixed speed; the old gait's phase is discarded; no intermediate posture. So the size of the jump at a stop or a turn start is set by where the legs are, which our guards (they only choose when to send) do not change. **Priority next lever: stop after a whole number of gait cycles (legs back near the start pose) and pre-position the legs to the new skill's first frame before starting it.** **Built 2026-11-06, default OFF, unproven:** `G2_CYCLE_STOP=1` (a timed turn or back-up runs on to the next whole gait cycle, at most 0.8 s longer, never the gyro-stopped line-up turns; code `behavior/gait_cycle.py`, `SerialRobot._finish_cycle`) and `G2_PREPOSITION=1` (before a firmware turn or walk the Pi eases the legs to the skill's first frame itself, `SerialLink.ease_into`, even where the link does not know the pose; the link already did this from a known pose, so the drill now prints a `link transition` line saying whether the ramp ran or why not). The first frames were already in `link/skill_frames.json`. The gait period is not in the skill data (116 frames for wkL, 43 for the arm's gait), so it is measured: `python -m pi_pipeline.behavior.transition_drill --measure` runs each gait for 4 s, finds the period by autocorrelation of the roll/pitch and writes `~/.local/share/g2/gait_cycles.json` (override: `G2_GAIT_CYCLE_S`; with neither, the cycle stop estimates from the move's own IMU frames). Drill variants: `cycle`, `pre`, `cycle_pre` beside `baseline`/`calm`/`gate`/`both`.

## Next steps, in order

**Hardware session order (user's go for each round):** (a) `--measure` once (about 40 s, G2 standing on hardwood, hands near) and read the periods and the IMU frame rate; (b) `baseline` x3 valid rounds; (c) `cycle`, `pre`, then `cycle_pre` x3 each; (d) `calm`/`gate`/`both` after, if time. Read the `link transition` and `last cycle stop` lines in every round. Stop at the first fall.

0. **The odd leg on stand-up (right about 98% of the time, a different leg each time).** Candidates: a lost or garbled joint command on the serial link, a servo that did not track in the stand-up surge (voltage dip), the firmware overwriting a joint mid-move. To separate them: resend the final stand pose a second time after the ramp (a mitigation and a test), log the pack voltage at the end of the ramp beside the leg check, and a way for the owner to flag an odd leg when seen. The leg check (`leg_check.jsonl`) has seen about six stand-ups, all clean: no evidence either way yet. Petoi's joint and gyro calibration is hygiene only.
1. **(Built 2026-11-06) The drill refuses to start, and voids a round, when no IMU frames arrive** (a silent board must never look like a pass). Add the BiBoard plug/answer check first.
2. Rerun `baseline` and `both` for at least 3 valid rounds each (a quiet room, the plug checked, the pack read), then `calm` and `gate` alone; compare cycles to the first fall, tilt swings and near falls.
3. If the attention-pose entry still falls: test a lower claw lift than 120 deg, a slower sweep, a standing look, and holding the attention pose for 10 s before the arm moves.
4. Try an eased stop out of a stride as another variant (the owner's 2026-10-10 rule keeps a stop out of a stride immediate; it is a rule they can change).
5. Look at the BiBoard voice module's part in the falls (count `not_from_pi` moves against fall times).
6. When one variant clearly wins: write the approach into `docs/guides` and the hard rules for all operations, and make every new move go through the same gate.
