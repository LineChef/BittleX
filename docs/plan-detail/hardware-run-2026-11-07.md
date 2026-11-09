# Hardware run 2026-11-07: falls at transitions and the memory check

Run under a code freeze (owner, 2026-11-07): all tests back to back, no code changes during the run, updates made afterwards from this data. Raw data (per-round output, status lines, notes) is on the Pi in `~/g2_runs/hw_20261107/`. Hardwood, the drill is `behavior/transition_drill.py` (10 cycles a round: attention pose, claw look, stand-up from the attention pose, turn, turn back). The pack was read before every round and is not a gate: falls happened at 100% (8.39 V) and 95% as well as at 74-86%.

## Rounds
| Variant | Round | Result | Where it fell |
|---|---|---|---|
| baseline | 1 | fell, 0 clean cycles | stand-up from attention (front right leg folded up) |
| baseline | 2 | 10/10 clean, worst swing 6.2 deg | - |
| baseline | 3 | fell, 0 clean cycles | attention-pose entry / claw look (tilt pitch -177..+150) |
| cycle | 1 | fell after at least 1 clean cycle | stand-up from attention (back right leg out backwards); the drill did not detect it, stopped by hand about a minute later; output lost to buffering |
| cycle | 2 | 10/10 clean, swing 6.5 | - |
| cycle | 3 | fell in cycle 4 (3 clean), swing 20.6 | stand-up from attention |
| pre* | 1 | fell in cycle 3 (2 clean) | during a turn right (pitch -115) |
| pre* | 2 | 10/10 clean, 1 near fall (20.9) | - |
| pre* | 3 | fell in cycle 2 (1 clean), 1 near fall (21.1) | stand-up from attention |
| eased* | 1 | fell, 0 clean | stand-up from attention (back left leg went backwards); fell again after a krest from the stop script |
| eased* | 2 | fell in cycle 4 (3 clean) | right after a level stand-up |
| eased* | 3 | fell in cycle 6 (5 clean), 3 near falls | stand-up from attention swung 37 deg, then the turn went to pitch -68 |

\* Low confidence: the voice service was running beside the drill from 10:25:53 PM (the owner ran `g2english`, which restarts it), sharing the serial port. Baseline and cycle rounds ran with it stopped. `cycle_pre` and the guards (`calm`, `gate`, `both`) were not run. One `pre` round was void (the board had gone silent after a fall; the owner power-cycled it).

## What the data shows
1. **The falls are at the attention pose and the stand-up from it, not at turns or stops.** Of 9 falls, 7 were at the stand-up from the attention pose, 1 at the attention-pose entry and 1 during a turn. The levers under test (whole-cycle stop, pre-position, eased stop) act on turns and stops, so most rounds ended before a lever could matter.
2. **No lever showed a benefit, and none is shown to hurt.** Per cycle attempted: baseline 2 falls in 12, cycle 2 in 18, pre 2 in 15, eased 3 in 11. Turn swings were the same: mean 4.9 / 5.7 / 5.8 / 6.0 deg (baseline / cycle / pre / eased), worst 6 / 21 / 21 / 27. With rounds of 0-10 clean cycles that cannot separate the variants.
3. **Whole-cycle stop was inert here.** The drill's turns last 1.0 s and the measured gait periods are 1.00 s (left) and 1.04 s (right), so a 1.0 s turn is already one cycle (added 0.0-0.04 s; on a 1.001 s run the rule said "boundary too far").
4. **Pre-position ran on every turn** (a 54 deg move, 1.01 s ramp, from the known pose). It adds a second to each turn and did not change the swings.
5. **The eased stop works as a mechanism.** An `i` command does cancel a running firmware gait cleanly on this board: it froze at the estimated pose and eased to balance over 0.8 s on every turn, with small swings. Whether it prevents falls is not shown.
6. **A random leg goes wrong at the stand-up from the attention pose, and tonight it is not rare.** Front right folded up (baseline 1), back right out backwards (cycle 1), back left backwards (eased 1): three different legs in three of the stand-ups that fell. The leg check never logged these because the fall comes first. This is the owner's earlier "odd leg" observation, now at the exact point where most falls happen. In the ball goal the owner also saw odd angles on all four legs; the leg check reported no bad joints (the board believes the commanded angles) while the tilt after a stand-up read roll -33 deg.
7. **Gait periods (`--measure`, 4 s each, the IMU streams at 5 frames/s):** `kwkL` 1.00 s, `kwkR` 1.04 s, `kwkF` 1.02 s, `kbkF` 0.62 s (resolution about 0.1 s).
8. **The pack does not predict the falls.**

## Memory check (the voice service, with the 2026-11-07 changes)
- **Ball goal in the service, 9.7 min, 6 attempts:** lowest free memory 115 MB, peak swap 26 MB, about 6 MB swapped out (worst 0.6 MB/s). Piper was released at the start. Clean.
- **Exploration roam in the service (discover goal, 3 attempts, 11.1 min; enabled with a temporary systemd drop-in, since removed):** lowest free memory 40 MB, peak swap 136 MB, about 94 MB swapped out (worst 3.6 MB/s), no OOM kill. The low points came when Piper loaded again mid-roam while the embedder was in memory (free 41 MB at 11:20:28 PM and 40 MB at the next attempt start); attempt 3, with Piper released throughout, stayed above 117 MB. A short stretch of 690 major faults/s followed the embedder's release. The in-process roam path worked (no fall back to the hand-over).
- Roam result: 5 pictures an attempt, all usable, nothing new (0 of 3).

## Other findings
- **The goal's battery gate stopped the ball goal on a sag reading** (8% / 7.33 V at an attempt's start, against 64% / 7.81 V minutes earlier).
- **The claw look pictures are slow in the ball chase** (7.6 s of camera and 8.7 s standing still before each search move) but not in exploration (owner's observation); memory is ruled out.
- **Drill and harness faults (all repo or run-script problems):** `transition_drill --measure` crashes without `--variant`; the 45 deg fall check missed a leg-out fall (it kept driving a fallen G2); the "board started a move" void flag fires on a late `balance` echo every round; a stop script that sent `krest` to a fallen G2 dropped him again; the runner buffered the round output; a stop signal is ignored by background processes.
- **The BiBoard went silent once** (no pack, `?` or IMU reply) right after a fall, and answered again after the owner power-cycled it.

## Next steps, in order
1. **Fix the stand-up from the attention pose** (the owner's request: one smooth motion, the front legs starting right behind the back legs; now `gait/standup.py` `ATT_*`). Find why a leg goes wrong there (a garbled or dropped command, or a servo that lags); consider a standing claw look that skips the attention pose.
2. **Fix the drill:** the `--measure` crash, a fall check that sees a leg-out stand-up (and stops sending), the false void flag, a longer turn so the cycle stop means something, and add a turns-only variant (stand once, then many turns and stops) so the levers are tested where they act.
3. **Re-test `pre`, `eased` and the cycle stop** with the voice service verified stopped, on the turns-only drill, then the guards.
4. **Memory:** keep Piper released for the whole roam (no reload for narration), consider a free-memory floor before loading the embedder and releasing it sooner, the lazy `anthropic` import, then repeat the roam.
5. **Ball goal:** a battery gate that tolerates sag (the resting reading, or several readings); the slow claw look pictures in the chase.

## What was done about it (2026-11-08)
1. **Stand-up from the attention pose:** one smooth motion (the front legs start 0.35 s after the back legs, not 0.9 s; both finish near 1.75 s) and the whole leg pose is re-sent every 4 steps so a dropped or garbled joint is corrected within about 0.3 s (`G2_ATT_STAND=legacy` keeps the old timing). Unproven on hardware. The default gait is now Petoi's scripted gait (`G2_DEFAULT_GAIT`) and the arm runs with the gyro balance on (`G2_GYRO_BALANCE=0|1` per run for the A/B; the stand-up ramp turns it off and on again around itself).
2. **Drill:** a 30 deg stand-up swing counts as a fall, the fall limit is 30 deg, turns are 1.5 s, `--turns-only` tests the levers where they act, the false `balance` void is gone, `--measure` needs no variant, nothing is sent to a G2 that fell, it refuses while `g2-voice` runs, and `pi_pipeline/behavior/drill_block.sh` runs a block back to back.
3. **Memory:** `util/mem_budget.py` releases the idle one of Piper / the embedder before the other loads when the load would leave under 70 MB free. The lazy `anthropic` import was not done (it conflicts with the start-up connection warm-up).
4. **Ball goal battery gate:** a low pack reading is re-read twice, 4 s apart, and the best one decides (`battery.settled_gate`), in the goal runner approaches and the chase.
5. **Claw look in the chase:** the light is metered in the background while the claw moves, and the trace and the log carry the seconds spent in each phase (sit, raise, pan, settle, camera, find, lower, stand) so the next ball-goal run shows exactly where the time goes.

## Speaker heat and the service crash loop (2026-11-08)
The owner found the speaker (not the amplifier board) really hot, with the sound normal earlier. The Pi's logs for that boot: no usable audio device the whole time (`PortAudioError: Error querying device -1`; the kernel logged no amplifier enable/disable at all, every normal boot has hundreds of pairs), and the voice service crashed and was restarted by systemd 27 times in 20 minutes (about every 50 s), each restart saying "G2 online." (failed), re-sending the voice-module commands to the BiBoard and reloading the speech model (32 s of CPU a cycle). Nothing was playing, so the heat was not playback; the leading hypothesis is the amplifier left in its power-up state with no audio clock (unconfirmed). The next boot, after a power cycle, had working audio and the speaker was cool. Cause of the sound card not starting: not found (no kernel message, no throttling).
Fixed the crash loop: the wake word waits and retries with a backoff (2 s growing to 30 s) when the microphone cannot be opened, logs it once a minute, and still takes a command handed in from outside; the voice-module English setting is not re-sent within 10 minutes of the last time. If the speaker gets hot again: power off, and read `journalctl -b -1 -k | grep voicehat` and the service log for the audio errors first.

## Where we left off (2026-11-08, about 10:25 AM): pick up here
**State**
- **G2 is at rest. The Pi is OFF: its own battery ran out** (nothing answers on ssh; it had been slow to answer first). Charge it before anything else. Then read `power_log.jsonl` around the earlier audio failure and the silent board (a failing Pi battery can brown out) and see why no Pi-battery alarm warned (that fix was an open decision).
- **Code:** everything is committed and pushed through `d1be1380`. **The Pi has code up to `d59f5a2b`** (deployed 10:05 AM); `d1be1380` (the unequal-speed stand-up, `STAND_SPEED_MID`) is NOT deployed: run `bash tools/g2_deploy_when_online.sh --once` once the Pi is on.
- **On the Pi:** `~/.local/share/g2/motion_feel.json` = `{"STAND_SPEED": 14, "STAND_WAIT_S": 3.8}` (it wins over `pi_pipeline/motion_feel.py`, where the numbers live: stand-up speed 20 / wait 2.6, claw 60 deg/s at 40/s). The voice service starts at boot: use `pi_pipeline/behavior/service_off.sh` (rests G2, then stops it) before any test. Raw data: `~/g2_runs/hw_20261107/` and `~/g2_runs/hw_20261108/` (one folder per test, plus `notes.txt`).
- **Standing rules from this stretch:** G2 is always laid in the rest position after a fall and before the voice service goes offline; read each result before starting the next test (a 10-run was started once on top of an unread fall); `g2english` restarts the voice service, so stop it again before a test; the privacy hook rejects one four-letter word, including in identifiers.

**What the 2026-11-08 tests showed**
1. **Gyro balance ON everywhere is wrong for the arm:** during a claw look the board started its own `rc` / `up` self-right and flipped him (pitch 178). It is off again (`G2_GYRO_BALANCE=1` for one run). `G2_GYRO_GAITS=1` (gyro on just before a scripted gait only) is built and unit-tested, never run properly on G2.
2. **Turns-only drill, gyro off, 1.0 s timed turns:** 3 of 3 rounds clean (30 of 30 cycles, worst swing 9.0 deg). The first rounds that fell (1.5 s turns, and gyro-on-gaits round 1) fell at the stand-up from rest, before the turn.
3. **Line-up (align) turns in the ball goal:** one logged `asked 6.0 deg, got 22.4 deg in 0.02 s` (a yaw spike ends the turn at once); a yaw-spike filter and `G2_ALIGN_YAW_STOP=0` (timed turns) are built, not yet tried. The ball-goal fall that run was the board's `rc`/`up` (gyro on).
4. **The stand-up from rest keeps tipping toward the same side (negative roll), about 1 in 4, whatever the method:** firmware `kbalance` gyro off: leans of -16, -15, -1, then fell (-78); `K` skill, speeds 24 and 20, gyro off: 6 of 6 stood (one lean to -14); speed 14, gyro off: 1 of 1 fell (-42); speed 14, gyro on: 3 clean (roll within +-2) then fell (-46). The left and right legs get identical commands, so a one-sided failure points at that side's hardware (front right folded in twice); the owner says the leg is fine and a sweep of just that leg was not run.
5. **The `K` stand-up works on the board** (format read from the OpenCat source, verified: the board stood 3 of 3 and read the pose "stand"): one message, `K` + payload + `~`, a behavior skill of 8 stages, played by the board with left and right together; speed 24 "looked good, a bit snappy", 20 "better, still needs to be slower", 14 leans more (slower = longer in the half-up pose). Pack dips about 0.3 V during the rise.
6. **Voice service crash loop fixed** (it died on a missing audio device 27 times and re-sent the voice-module setting each time); the hot speaker is unexplained (the audio device was missing that boot, nothing was playing).
7. **Built this stretch (all committed):** default gait is Petoi's scripted gait (`G2_DEFAULT_GAIT=policy` to go back); smooth attention stand-up (`G2_ATT_STAND=legacy`); drill fixes, `--turns-only`, `--stand-only` (with pack voltage and the board's pose after each), `drill_block.sh`, `service_off.sh`; memory release/trim and `mem_budget`; sag-tolerant battery gate; claw-look phase timing; `claw_smooth_test` (never run); `motion_feel.py` plus the override file.

**Next, in order**
1. Charge the Pi; `service_off.sh`; deploy `d1be1380`.
2. **The unequal-speed stand-up, 10 in a row, gyro on** (the next test the owner asked for): set the override to `{"STAND_SPEED": 12, "STAND_SPEED_MID": 28, "STAND_SLOW_STAGES": 2, "STAND_WAIT_S": 3.4}`, run `G2_STAND_VIA=kskill G2_GYRO_BALANCE=1 drill_block.sh baseline 1 1 -- --stand-only --cycles 10`.
3. **Front-right leg check:** drive only that leg's two joints slowly through the stand range, IMU on, and compare with the front-left.
4. If a stand-up method is clean over 10: route EVERY Pi-started stand-up through it (the link has one choke point), gyro on for the rise and off after, then decide on the data-only firmware edit (`up` / `balance` in `InstinctBittleESP.h`, a re-flash) for the board's own stand-ups.
5. Claw raise jerk: run `claw_smooth_test` (four speed / step-rate settings) and pick by eye; the same may help the attention-pose stand-up.
6. Then the earlier list: `pre`, `eased` and the cycle stop on the turns-only drill with the service stopped, gyro-on-gaits (`G2_GYRO_GAITS=1`) against gyro off, the memory roam repeat, the ball goal with the gyro off (check the aligns), and the Pi battery alarm.

## Queued for the END of the 2026-11-08 session (owner's notes from the full drill with the K attention stand-up; do these after the ball chase and memory work, no code change before then)
1. **Slow the stand-up a tiny bit.** The stand-ups out of the ATTENTION pose were getting close to falling. The rest stand-up (10 of 10 clean) may stay as it is: give the attention-pose stand-up its own speeds (a separate `STAND_ATT_SPEED` / `STAND_ATT_SPEED_MID` / `STAND_ATT_WAIT_S` in `pi_pipeline/motion_feel.py`) and lower them a little (start at about 10 / 22 / wait 4.0), then re-run the drill.
2. **Ease into the attention position.** The robot sits hard into it: `kcalib` moves every leg joint at once at full speed. Ease it the same way as the stand-up (a board-played `K` skill, or a Pi ramp, from the standing pose to the attention pose) to put less pressure on the servo horns; keep the claw centered during it (see the claw test). It is probably harmless, but it is also where one 11-07 round flipped him.
