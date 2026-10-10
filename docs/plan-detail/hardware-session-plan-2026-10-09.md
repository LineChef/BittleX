# Hardware session plan (written 2026-10-09 night, for the next session)

The user runs the hardware (places G2, holds him, measures tape and facing); Claude runs every command and records. Floor: hardwood unless the user says otherwise (then `g2floor <name>` first). Times are Eastern.
Read first: [`handoff-2026-10-09-night.md`](handoff-2026-10-09-night.md) (state), [`../STATUS.md`](../STATUS.md) (what is deployed).

## Rules for this and every hardware session (user, 2026-10-09)
- **Everything starts on his feet** (the user has no stand): hands near, never on his back, no "in the air first" step. Anything new still gets a short first walk (6 s).
- **No gait comparisons on the real robot.** Comparing gaits (policy against policy, scripted against hi step) is sim only. On G2 we measure one thing's own behavior: drift, trim, ramp, stability, sounds.
- Stop anything that controls G2 with `tools/g2_safe_stop.sh` (rest first, never a plain `systemctl stop`). Tell Claude about any fall, odd noise or heat.
- **Why `g2-voice` is stopped before a walk:** the service runs the real serial actuator and holds the BiBoard's serial port (and the mic stream), and only one process can use the port at a time (see the `stand_log.py` note in `hardware/petoi-firmware-reference.md`). A walk script started beside it would collide on the port, and the voice loop's own commands (wake word, behavior, battery watcher) could move G2 mid-test. Stop it with `tools/g2_safe_stop.sh voice` (not a plain `systemctl stop`) and start it again at the end (`sudo systemctl start g2-voice`).
- Ask for the floor, the pack voltage (resting) and the lane before the first walk. Give timing estimates with clock times (12-hour AM/PM Eastern); `python tools/eta.py` is for training, hardware time is quoted from this plan.

## Confirmed by the user (2026-10-09 night)
Hardwood, the 9 ft lane, the same spacing between rounds as the V4 session (35 s), fresh batteries. G2 rests on the user's desk until the session starts.

## State going in
- **V6 is the deployed default** (`DEFAULT_POLICY`; promoted and deployed on the user's word although it did not beat V4 in the sim: mean falls 0.215 against 0.189, better on 7.5-15 mm step-ups, about equal elsewhere; short report https://claude.ai/artifact/P2CTwR8Z1KgCw8ccVtrRiK, V6 section of [`v6-staged-training-plan.md`](v6-staged-training-plan.md)). It is heading-blind (the Pi feeds yaw 0), commands every 3rd tick, has NO trim yet. V4 (trim -0.2 front-left, keyed to its file name), V3 and V2.1 are on the Pi as fallbacks: `--policy rl_training/opencat-gym/trained/Release_CandidateV4_ppo.onnx`.
- Everything committed this evening was deployed 11:23 PM (exchange sounds, exploration changes, gait switching and scripted hi step, wall dry run, V6).
- Lane: 9 ft start line on hardwood, tape numbers = forward then sideways (+ = right) in inches, facing as a clock face (12 = straight). Data goes to `docs/rl/real-walk-data/<date>/README.md` plus CSVs (`g2data` syncs; labels with `g2floor`).
- Open hardware item: the **back-left shoulder** servo feels stiffer and louder (power off, no wire snag); parked, flag anything unusual (test options: microphone sweep comparison, slow-motion video, USB `servo_static_test.py` with the Pi removed).

## Block 1 -- V6 calibration (about 45-60 min; must-have)
1. **First walk, 6 s on the floor**, hands ready: `python pi_pipeline/gait/run_gait.py --cmd 0.10 --seconds 6 --log-extra`. Check: upright, no faults, nothing odd in the log.
2. **Natural turn, hold and trim off, 3 runs of 12.5 s** (`G2_FOOT_TRIM=off python pi_pipeline/gait/run_gait.py --cmd 0.10 --seconds 12.5 --log-extra`; the hold is off by default; 25-35 s between rounds): tape (forward, sideways), facing by eye, logged yaw. Expect a turn; V4 turned right about 60 deg by eye.
3. **Trim sweep:** from the measured turn choose 2-3 values of front-left foot trim (`--foot-trim fl=-0.2` etc.; V4's -0.2 is the starting guess if V6 also turns right), 3 runs each, pick the one that keeps him straightest. Same method as V4 (`trim20_*` logs).
4. **Confirm at the chosen trim:** 3 more lane runs, then 3 crossings of the 1/4 in (6.4 mm) threshold strip (11 s, tile side), then, if the user has it, the taller strip.
5. **Record:** set the V6 default trim in `gait/heading_hold.py` `DEFAULT_TRIMS` keyed to `Release_CandidateV6_ppo.onnx`; README for the day; update STATUS. A trim for tile if the user switches floors.

## Block 2 -- sounds (about 15 min)
Speaker works at all? (The Pi logged a sound-device error earlier.) Then: wake-word beep, "boop" when the words are captured, the two falling notes when the follow-up window closes, the double beep on a gait switch, the exploration fanfare (the user liked it from the Mac, still to hear on G2). About 10 tries each of "hi step" and "walk mode" (and "walk normally") to see how well the recognizer hears them.

## Block 3 -- hi step, scripted hsF (about 25 min)
On the floor: 4 walks, note speed (expected about 0.04 m/s, slower than normal on purpose) and sway; a snag (cable or pencil) and a small rubble patch, where it should help most; then "walk normally" back. No comparison with the basic walk on G2 (sim only).

## Block 4 -- exploration session (about 15 min, at the end of the walking blocks)
Cleared area, no edges. Watch: the 40 s start announcement, fanfare, 7 s legs ending in the standing pose, no head moves, picture stops about once a minute, clean stop (`tools/g2_safe_stop.sh`). Afterwards read `~/.local/share/g2/wall_dryrun.jsonl` (the wall estimator only logs).

## Block 5 -- wall calibration (about 15 min)
A box or book wide enough, placed at 20, 30, 40, 60 and 100 cm in front of G2 (floor tape). Plan and the cadence of the periodic wall look: [`../vision/wall-check-plan.md`](../vision/wall-check-plan.md). The vision avoider stays unwired until the user says.

## Block 6 -- recognition training
Label the first 5 pictures per object (plan [`../vision/exploration-object-learning-plan.md`](../vision/exploration-object-learning-plan.md)); DINOv2-small thresholds need retuning, Pi int8 timing still to measure.

## If time or battery allows
Tile trims for V6, taller threshold strip, a low-pack repeat (about 7.9 V), a second capture for the sim fit (real2sim fit must reproduce on another day or battery), bench servo tests, the BiBoard low-battery alarm voltage (the user will say when it sounds).

## What to bring back
Tape/facing numbers per run, resting pack voltage at start and end, any falls, the floor, how the sounds and exploration felt. Claude: logs fetched, README written, STATUS and the trim default updated, commit with explicit paths.

## Session log (update as blocks complete)
- **2026-10-09 ~11:50 PM, block 1 step 1 DONE; session paused by the user, the next session continues from step 2.** Hardwood labelled (`telemetry surface hardwood`), fresh pack 8.43 V resting (8.36 V at the end of the walk). First V6 walk, 6 s, `G2_FOOT_TRIM=off`, hold off: no fault, guard ok, policy step 1.95 ms mean; roll sway 3.7 deg (range -6.1..+5.9), pitch sway 2.7 deg, **logged yaw +55 deg in 6 s (a right turn of about 9 deg/s, like V4's about 8 deg/s with no trim)**. Log on the Pi: `~/g2_runs/v6_first_20261009.csv`. **By eye (user): 6 in right of the line at the end, front end facing about 2:30 (about 75 deg right); forward distance not given.** The log's +55 deg is below the by-eye angle (for V4 the log read higher than by eye). `g2-voice` was stopped for the walk and started again afterwards (active); to run more single walks stop it first (`sudo systemctl stop g2-voice`), and start it again at the end.
- Next: step 2 (3 natural-turn runs of 12.5 s, trim off), then the trim sweep starting from `fl=-0.2` (V4's value; V6 turns right about as much), then steps 3-5. Expect V6 to need the same sign of trim.
