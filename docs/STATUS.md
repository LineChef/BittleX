---
audience: visitor
kind: overview
---

# Current status

G2 is a Petoi Bittle X quadruped that walks with a learned gait, listens and talks through Claude, remembers what it is told, and explores on its own. This page says what works today, what has only been tested in part, and what is still being fixed. It is the single page for the current state, updated after each round of hardware testing, and carries its last-changed date in the site header. Dated write-ups stay in the repository's working notes.

The longer story of how each part works is in [How it works](how-it-works.md); the full list of abilities is in [Capabilities](capabilities.md).

At a glance
-----------

- Walking: Works on hardwood floors. Tile and carpet are not solved.
- Voice conversation: Works. Wake word, spoken commands, Claude replies, speech out.
- Memory: Works. Facts and past conversations persist between sessions.
- Exploration: Works in a small room. A 5-minute roam on hardwood ended with no falls and level stand-ups after the claw-look and motion-sensor fixes. Earlier roams fell on the back-left leg, which sagged. The yes to G2's question starts a roam. A roam can still bump a wall three times in a short roam; the attention pose after a long hold is not yet confirmed level.
- Ball goal (punting a ball): Works some of the time. Falls during turns are the main problem.
- Falls: The biggest open problem. G2 sometimes tips over at pose and turn changes.

What G2 is made of
------------------

- Body: A Bittle X V2 with a BiBoard control board, running Petoi's OpenCat firmware.
- Brain: A Raspberry Pi Zero 2 W in a printed pod on G2's back. It runs the voice, memory, vision and walking software, and talks to the BiBoard over a serial cable. Details in [As built](hardware/as-built.md).
- Eyes: A Grove Vision AI V2 camera that runs object detection on the camera itself.
- Ears and voice: A small microphone and speaker on the Pi.
- Neck attachment: A claw arm is fitted, with its camera on the claw. It replaced the Petoi AI Head that was fitted earlier. Wider shoulders are fitted. G2 now weighs a little over 530 g with all of it. How attachments change the settings: [Attachments](guides/attachments.md).
- Power: G2 runs on its own battery pack. The Pi runs on a small PiSugar pack that lasts about three hours.

What works
----------

### Walking

The deployed walking policy is a small neural network that makes constant corrections on top of Petoi's scripted walk. It was trained in simulation, then calibrated on a hardwood floor. On hardwood it walks about 4 ft in 12 seconds and drifts a few inches to one side, which a fixed foot adjustment trims. The arm fitted today has its own walking policy, which has been deployed but not yet walked on the real robot. See [Walking policy](rl/walking-policy.md) and [Gait deployment](guides/gait-deployment.md).

Every stand-up is a slow, eased movement played by the board. G2 never uses the firmware's own quick stand-up. The pose is read before each stand-up, which has run on G2 in every session since it was added. A pose that is readable but is not one of the four stand-up poses (the survey bow, the check lean) is eased from the angles the board reports, and an unreadable pose gets a rest first.

Some Petoi tricks are switched off because they tip G2 over with the current weight: wave, scratch, shake paw, high five and hop. See [Disabled moves](hardware/disabled-moves.md).

### Voice and memory

- The wake word is "Gee Two". Short commands such as stop, sleep and "walk for ten seconds" are handled on the Pi without a network call. Everything else goes to Claude. See [Voice commands](guides/voice-commands.md).
- Memory is live. G2 keeps a log of conversations and a short list of lasting facts, and looks up relevant ones before each reply.
- G2 goes to sleep after five minutes at rest.
- The battery of both G2 and the Pi is monitored, with spoken warnings.

### Exploration

G2 can wander a room, turn away from walls, react to bumps, stop to take pictures and say what it notices. It has run for several minutes at a time in a small room. A roam starts only on a spoken request. After three minutes of idling G2 asks "Can I go exploring?" and walks only on "Gee Two, yes". See [Exploration mode](guides/exploration-mode.md).

### The ball goal

G2 can be given a goal: find a ball, walk up to it and punt it. A session is up to ten attempts, and G2 adjusts its approach between attempts based on what worked. The session runs inside the voice service. More on this in [Goals](guides/goals.md). Results are mixed. Early sessions scored well, and later ones dropped. Part of the cause was a default turn speed far lower than the real turn speed, which made turns overshoot. The corrected default is deployed and has not been tested on G2.

The active look is part of the goal: after the last punt of an attempt, from the standing position with the arm left up, the claw follows the rolling ball on the camera's picture stream until it stops or leaves view. Then one last picture is taken (even when the stream lost the ball), the claw is centred, G2 lies down in rest and stands up from rest, and he says target acquired and goes on from there, or turns toward where the ball was last seen. "Got it." is said right after a good punt, before "I lost the ball". The weak point is seeing the ball in the stream: the finder saw it in only about one picture in ten on a pale ball, the picture brightness swung between 48 and 127 within seconds, and small false blobs at the frame edges steered the claw. Changes now deployed and not yet judged on the robot: the ball found by its own colour, a lead on a moving ball, a check against false jumps, a per-picture log in the journal, and a camera-only probe for the exposure lock and the picture size options.

Three falls in two days began with G2 standing rolled about 22 degrees for several seconds. The move gate (before every move and before the claw look) now stops that, and recovery lies down in rest and stands up from rest; it fired twice in the last run. Why a stand from rest sometimes leaves him rolled 16 to 23 degrees is not known: the logs show every leg joint at its stand angle. The battery gate ended the last run (the pack read 32 percent, then 25 percent).

What is deployed
----------------

Everything below is on the Pi.

- Walking policy: V7, a policy trained from scratch for 20 million steps on the pod and AI-head payload. It sends a joint command every third control tick and does not use heading. It fell less than the previous policy in simulation and climbed the lowest step far more often. Earlier policies stay on the Pi as fallbacks. Rolling back means pointing `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py` at the earlier file and deploying. With the arm fitted the walk is chosen by one rule for every mode (`gait_mode.walk_choice`): a floor labelled tile, or the spoken "high step", plays ARMW, the arm's own policy (trained for the arm with wide shoulders and stock feet); any other floor plays Petoi's scripted arm walk (`wkArmF`); turns and the small steps near a ball stay scripted. V7 stays the policy for the head and for no attachment. ARMW on tile is untested on G2; on a tile exploration the V7 version was seen to start its walks, and the wall check's false stops (one column group reading 8 in off a grout line) are fixed but not yet tested.
- Steering: The heading hold is off by default. Everyday walks use a fixed front-left foot trim per policy, measured on hardwood only.
- Walk start: After a firmware gait or skill, a walk first settles into a still stand and never starts while G2 is tilted past 30 degrees.
- Stand-ups: Every stand-up is the eased stand-up played by the board, from rest, a sit, the attention pose or any pose the board reports. G2 reads its pose first (three tries). An unreadable or unusual pose gets a rest first. Each stand-up is logged. A stop out of a stride stays immediate.
- Moves into skills: The serial link eases the legs from the known pose into each skill, so no joint exceeds 80 degrees per second.
- Disabled moves: Wave, scratch, shake paw, high five and hop are refused, because they tip G2 over on this payload.
- Voice: Wake word, local commands, conversation mode ("let's talk") and spoken sounds. Every wake trigger is logged with what followed it.
- Sleep: After five minutes at rest.
- Memory: Live: facts, exchange log, pinned core facts and sleep-time tidying. Reflection is switched off; the recaps are still written.
- Exploration: Two tiers: stationary and attentive, and a roam armed by voice or by a yes to G2's question. Roams have turns that end on the gyro, a wall avoider that does not trust a repeated "8 in" reading, a hit sequence from the motion sensor, narration and scheduled survey pictures. The driver reports one phase (look, move or pause) and logs each change.
- Looks and rests: The claw look is one standard move that every mode calls (`run_claw_look`, which runs the ball chase's sequence; the callers add no steps around it, so a change to it applies everywhere): G2 stands first, goes into the attention pose and settles for 2 s, the claw is raised, swings left (settle, picture), right (settle, picture) and back to the centre (settle, picture), the claw is lowered, and he stands up (out of the attention pose he lies down in rest first, then stands up from rest). The one-skill version and the eased lie-down tried on the first evening of the new look are removed. No step waits out a timeout for a pose read the board does not answer. Every session ends in the verified rest position.
- Sag recovery: While G2 stands idle, a tilt that grows after 5 s without a command re-stands G2. While a roam walks, a tilt that moves 12 degrees from the walk's own reference holds the walker and re-stands G2.
- Start-up: The voice service is ready in about 33 s. The firmware question is skipped for the arm, and the speech model loads in the background. The Piper voice (13 s on the Pi) is now the largest remaining step.
- Motion-sensor stream: The IMU print stays on through every pose read, stand-up tilt reading and claw look (they used to switch it off, which blinded the fall guard, the sag check and the turn measurement during roams). The stand guard sends the print command again after 8 s without frames.
- Falls and a deaf board (every mode): The guards are built one way for every mode (`gait/body_guards.py`): the voice service, the exploration and the chase use the same thresholds, the same sag recovery (standing and walking) and the same responses. A fall is a tilt past 60 degrees for 0.3 s: gyro balance off and rest at once, the losing horn and "I fell down. I have stopped.", and the mode ends. A board that sends no motion data for 20 s is deaf: whatever is moving is halted, G2 is laid down, he says his motion sensor stopped answering and asks for the board plug to be checked, and the mode ends (a goal counts the attempt as not counted). Each fall also saves a record of the motion-sensor trace around it, and each stand-up logs the joint angles the board reports just before the rise.
- Claw look: The stand-up after a look waits for the look to finish. A late look skips its side pictures, and so does a look after one missed picture. While the pose is held, the leg angles are sent again every 4 s.
- Attention pose entry: The move into the pose is an eased skill that is left to finish (up to 7 s), never snapped into place. A stand-up out of the attention pose first lies G2 down in the rest position and then plays the normal stand-up from rest (`STAND_ATT_VIA_REST`; 0 plays the K stand-up straight out of the attention pose). The straight stand-up tipped him over backwards after the claw look in the first evening roams and in three drill rounds, and the more the back legs led the front legs the further he tipped (pitch down to -71 degrees); the stand-up from rest was level every time. The via-rest version is being tested.
- Roam length: The default is 5 minutes.
- Wall loop handover: The same wall turned away from three times at the same distance within 20 s hands over to the back-up-and-turn-around sequence.
- Walk logs: A scripted firmware gait writes a `scripted_walk` log, kept apart from the learned walks and never read by a fit.
- Robustness: A dead camera reader restarts, a failed behaviour tick is skipped, and every walk log records why the walk ended.
- Battery alarms: Voice warnings for both G2's pack and the Pi's runtime.
- Sounds: One at a time, through an audio gate, at one global volume.

Tested on the real robot
------------------------

- Walking: Six steady hardwood runs with the first policy. The next policies were tested on hardwood and over a quarter-inch ramped threshold with no falls. V7, with the pod and head, did three 12-second walks with no falls.
- Poses and transitions: Stand, sit, rest and stand-from-sit are smooth with firmware balance off. The wave flipped G2 twice. Played one at a time from a stand, the survey poses (sit, bow and check lean) caused no fall, with a body swing of about 28, 14 and 19 degrees.
- With the arm, on hardwood: Petoi's walk covered 4 ft 4 in in 10 s. The first arm policy covered 4 ft 5 in in 12.5 s, about 5 in off line. The claw's pick, put and lunge moves ran. The lunge throws a 3 in ball about 18 in, but the claw cannot grab it.
- Exploration: Short roams in tight rooms produced wall turns, hit sequences, survey pictures and narration. One roam ended in a tip-over at a survey stop. A roam on the build before the latest fixes repeated one wall turn eight times and ended with both back legs sagging.
- Voice to Claude to walk: Spoken replies and a full listen, talk and walk run.
- Wall avoider: Judged "working fairly well" with the camera in its old position.
- Ball goal: The first sessions scored a few punts, and the finder, turns and wall reading were then improved several times. Success rates fell from about one in four early on to about one in ten later. Part of the cause is a turn-speed mismatch that is now fixed in code. A first-stand-up fall is more common than later ones. Inside the voice service, one session ran ten attempts with one punt, and the next runs ended in falls within the first minutes.

### Not yet run on G2

The colour matching, the lead and the jump check in the active look, the proportional small steps, the exposure-lock and picture-size experiments (`g2stream --lock-ae`, `--compare`), the finder's pale-ball rules in a clean run, the step calibration (it stopped at trial 1: the ball was not seen), the arm skills, the walls goal, "G2, practise", the spoken goal suggestions and operator overrides, the policy walk toward a ball with self-measured pace, vision reflexes while walking, the full application over a long period, the teach tool, the recognition labelling pictures, the per-leg wall look, conversation mode as a hardware test, G2 asking to explore, the sag check while walking, and the wall-loop handover.

Known limitations
-----------------

1. Falls at transitions: Most falls happen in turns and pose changes. Of 154 logged ball-goal attempts, 18 recorded a fall, 13 of them in turns, and most falls are never logged. Safeguards exist (a pose gate, a steady check, calm stops, the claw look as the only look) but none has had a valid test round. Voided rounds were caused by a drill bug, a voice-module move and a silent board.
2. Legs going limp: After about ten seconds standing still, the leg servos can lose strength. The leading explanation is the servos' overload protection, worst on the back legs, which carry the raised arm. A sag check from the motion sensor re-stands G2 while idle and, in a roam, while walking. In a roam the earlier check never fired, because it waits for 5 s without a command. The walking check is deployed and untested on the robot. The servos' own cutoff cannot be switched off from the Pi, so the claw look holds the attention pose for less time: the leg angles are sent again every 4 s, a stand-up waits for the look to finish, and a look that runs late skips its side pictures. The next roam shows whether the legs stay level in the attention pose.
3. The BiBoard going silent: The board sometimes streams motion data but ignores every command until power-cycled. Reseating the Pi-to-BiBoard plug cured it once. A long-running cause: the plug on the BiBoard's 5-pin header sat the wrong way round, so the Pi received no motion data. With it turned and a new wire, the stream arrived at the start of two of three voice service restarts, and the third started about 30 s late: the stand guard sends `gP` once and, with no frame yet, resends only after 30 s, later than the 20 s deaf-board verdict. No walk has run since. The ball goal now runs inside the voice service so the serial port is never closed.
4. Garbled serial reads: right after the voice service stops. The pack reading comes back empty, so the battery gate warns and continues. A restarting service can hold the port, so check before reading the board.
5. The board's own voice module: hears the television and starts moves by itself. The command log checkpoints such moves "not from the Pi". "Be quiet" makes the module ignore basic commands, and there is no known way to silence only its spoken "ok".
6. The camera: answers each request with the previous picture, so each picture is taken twice and the first dropped. It sometimes stops answering during exploration.
7. The wall estimator: needs recalibrating for the claw camera. It reads "8 in" almost every time, so a repeated reading is distrusted. A roam also read "12 in" at one wall many times in a row.
8. Late walk ticks: reached 30 percent in exploration. The serial send does not wait for the bytes to drain. This is untested.
9. Speech arrives 7 to 17 seconds late: during exploration. Lines are now cached and pre-made at idle.
10. Wake-word false triggers: About four in seven triggers were nearby talk. A confidence threshold is set and is being tuned from the log.
11. The bump reflex misses thin obstacles: such as chair legs.
12. Heading drift on other floors: Hardwood is handled by the trim. Tile is unresolved, and carpet is open.
13. Carpet: Every gait tried fails on about a quarter inch of pile. Falls go sideways to the right.
14. Ledges: No policy crosses step-ups above 0.3 in in simulation.
15. Board-started stand-ups: The BiBoard starts an `up` by itself before some attention stand-ups, which raises the hind legs first. The cause is not proven. Candidates are the firmware's own self-right and the stand guard.
16. Turns in a roam: Every roam turn logged no yaw change. Whether the IMU stream is missing during roams is not known yet.
17. Turn angle from the gyro: The board's yaw reading does not match the real rotation, and the error differs by side. In the 1.5 second pivot test on hardwood the camera pictures and direct observation agreed on about 30 to 40 degrees for each pivot, while the gyro counted about 6 to 16 degrees for right pivots and about 45 to 50 for left pivots. The spike filter ignored none of them (one spike in 14 turns), and a right command does turn him right. The ball goal's line-up turns are sized from this reading and corrected by the camera after each pulse, so the camera loop covers the error today.
18. The pivot gait (`kvtL`, `kvtR`) turns him in place but ends mid-cycle: its 72-frame cycle starts and ends near the balance stand, and a stop at any other phase leaves the diagonal leg pairs apart. Before the next move the body was tilted more than 12 degrees in 10 of 28 pivot turns. `G2_TURN_GAIT=pivot` selects it for every mode (off by default). Its measured cycle is 0.86 seconds. Its turn cap is 4 seconds. A timed pivot keeps going to a whole cycle before it stops (`G2_PIVOT_CYCLE_STOP`, on): in a 20-turn comparison the large nose-up sags (31 to 35 degrees) were 3 of 10 turns without it and 0 of 10 with it, a small sample. After every pivot the tilt and arm are logged, and a nose-up lean past 8 degrees (`G2_PIVOT_LEAN_DEG`) lays him down and stands him up again at once. Measured later: 10 pivots of 1.0 second each moved him about 0.7 inch forward on average (net of the alternating turns), against 2 to 7 inches for arc turns; the tilt after every pivot was within about 1.5 degrees; two of the 10 turns needed a sag recovery. The cycle time repeated at 0.86 seconds for the left pivot and 0.88 for the right. The eased stop also covers the pivot frames (`G2_EASED_STOP`, off). The ball goal's line-up turns use both gaits (`G2_LINEUP_GAIT=auto`): arcs while the ball is far or right up against it, the pivot while it is 8 to 40 inches away, as one or two whole pivot cycles with no gyro stop. The first version, a gyro-stopped pivot, flipped him in its first goal run (asked 20 degrees, turned 48 and coasted 32 more, rolled to 80 degrees, with the board starting moves of its own just before); the whole-cycle version turned the 3 to 6 degree align pulses far too much (one cycle is 20 degrees or more), so only turns of 18 degrees or more use the pivot (one cycle turns the camera bearing 26 to 28 degrees) and the small pulses stay on the arc; that corrected version has not been run in the goal yet. In the first baseline run on hardwood (arc turns) the claw sat on the ball, the camera still read it 20 to 30 degrees off at 2 to 4 inches (inside about 3 inches the camera bearing is documented as unusable and the tracker counts turns with the gyro), and after a pulse the ball left the picture and he punted at the empty spot as "vanished at close range". Changes since: the camera's blind range is 4 inches (it was 3, inside the punt range), a ball that vanishes after being last seen more than 12 degrees off straight is looked for instead of punted at, a sag recovery never sends a stand-up to a body that has fallen (the lie-down from a rolled stand flipped him to 178 degrees in the 10:45 fall), and every sag is logged with what he was doing lately (`G2_SAG_LOG`).
19. Falls in lie-downs and pivot turns: three falls in one day had different causes. A sag recovery's lie-down from a one-sided roll of 22 degrees flipped him to his back, and the recovery then sent a stand-up to the fallen body (it now reads the tilt first and lays him in rest). A line-up turn with the gyro-stopped pivot, asked for 20 degrees, turned 48 and coasted 32 more, rolled to 80 degrees and flipped him, with the board starting moves of its own just before (the line-up pivot is now whole cycles with no gyro stop, used only for turns of 18 degrees or more). A last lie-down at the end of a turn test left him on his back with nothing logging the tilt around it. Every sag is logged with what he was doing lately (`G2_SAG_LOG`). On 2026-11-19 the lie-down log caught the next one: a sag recovery from a 21 degree roll flipped him within a second of the firmware rest command, with the pack at 7.9 V. The lie-down from a stand, the attention pose or a sit is now an eased K skill like the stand-up (`REST_EASED` in `motion_feel.py`; a body found fallen still gets the plain rest). The eased lie-down did not stop it: on the next run the board started its own `up` two seconds into the move, the pose never read as rest in 7 seconds, and he went over with no tilt recorded for the move (the pose reads stop the IMU print). The eased lie-down now reads the tilt for its first 3 seconds and records it (`during` in `liedown_events.jsonl` and the motion events), and a sag with a roll of 15 degrees or more is first answered by re-seating the legs where he stands, with no lie-down (`G2_SAG_RESEAT`); the lie-down is the fallback. Untested on G2: read `liedown_events.jsonl` for both. Why the board starts `up` is not known (its voice module or its own tilt reaction).
17. Minor: An unexplained ticking from the board during some walks, and a stiffer, louder back-left shoulder servo.
18. Legs ending in odd positions: A move can end with a leg joint away from its target. The suspected cause is the firmware gyro balance: when a foot slips on a hard floor, the balance loop corrects the leg joints in the middle of the move. This is unproven. Every stand-up and attention-pose entry logs how far each leg joint is from its target and the gyro balance state (motion events log, a warning at 8 degrees or more, and the run report).

Open decisions
--------------

- The Petoi AI Head is an extra voice model started by its button. Claude stays the main brain and nothing is integrated for now.
- Claude descriptions of survey pictures (one billed call per picture) are on hold.
- A new 20-million-step training run: starts only on explicit approval and never on top of a finished long run.
- Gait comparisons on G2 are not run. Policies are compared in simulation only.
- G2 looking around on his own while idle is not enabled, because the legs sag when G2 stands still.

What happens next
-----------------

Testing follows a simple rule: collect data from normal runs first, then run a targeted test only where the logs cannot answer the question.

1. Power, board and posture, before anything moves. Charge the pack and the Pi. After the boot, read the voice service's journal for "receiving the IMU stream" and for no "not answering": the board is silent for the first minutes after a boot and after a deploy restart until it is powered and its plug is seated. Check the Pi-to-BiBoard plug, that G2 is on his feet by eye, and a quiet room (the board's voice module starts moves of its own).
2. Setup. Run the `sync-data` skill first (it pulls everything new off the Pi, then grooms), set the floor label (`g2floor hardwood`), confirm the Pi is on the newest commit (`bash tools/g2_preflight.sh`), and place the ball where the test needs it. The `wall` object class was removed on the Mac (13 pictures in the review page's Trash, 14 in the training class moved to `G2Memory/_pruned/wall_class_20261118`, restorable for 14 days): the sync sends the queued Pi-side trash first, then check the Pi's object gallery for a learned `wall` entry and discard it, because a name the gallery has already learned stays there. Do the camera-dependent tests in good light: the room was too dark for the ball goal and the far-ball check, and the picture matching for rotation failed in dim light.
3. Ball goal run with the corrected line-up: arcs while the ball is far, under 5 inches, closer than 8 inches (where he now backs up to about 9 inches first when a line-up is needed under 5 inches), or for pulses under 18 degrees, whole-cycle pivots for turns of 18 degrees or more with the ball 8 to 40 inches away (the line-up is now asked for the whole bearing, up to two cycles: the 6 degree pulse cap meant the pivot never ran in the 2026-11-19 run, which got within 3 to 5 inches but could not line up on the arcs), then small steps closer. Read the stand-up, gate and active-look logs after it. Count align successes, overshoots, falls and sags, and read `after_punt.frames` to judge the ball watch's lead (0.9 seconds) and coast (1.5 seconds). Stop on a fall and run the fall analysis. Earlier runs on hardwood: 1 success in 8 attempts with the arc turns (ended by a fall), 1 in 3 with the gyro-stopped pivot (ended by a fall), 0 in 4 with the mixed line-up before the small-pulse fix (ended by the pack gate).
4. Far-ball check. The first missed-ball pictures showed the ball as a small pale-green dot, 98 to 189 pixels, at the base of a wall; the finder's dim pass wants 300 pixels and row 80, so it missed them, while the ball's own colour finds them (it also fires on about 5 percent of pictures with no ball). The colour is remembered between sessions, every look falls back to the ball's own colour, and the watch takes up to three more pictures before it says the ball is lost. Read the missed-look pictures kept on the Pi (`~/g2_claw_pics/misses_*`) first, then judge whether "I lost the ball" with the ball 4 to 5 feet away still happens.
5. Lie-down tilt logging (deployed with the 2026-11-19 session start, no lines yet): the shared robot writes a line to `liedown_events.jsonl` for every lie-down it makes, with the tilt before and 1 and 3 seconds after the rest command (`G2_LIEDOWN_TIMES=1,3,10` adds 10 seconds), whether the body went over, and the pack voltage read before it; each sag line now carries the pack voltage read at that moment. Because the log reads the tilt for 3 seconds after the rest command, the lie-down inside a look or a sag recovery waits about 2 seconds longer than before (`G2_LIEDOWN_LOG=0` restores the old timing). After a fall, `g2fall` prints the fall record with these events and a first guess at its class. Read the first lines before relying on them.
6. Rotation per second from pictures, in good light: put the ball off to one side so it stays in the picture after a 1.0 second turn, and compare arc and pivot on each side. Picture matching on a plain, dim wall was inconclusive.
7. Small steps. Decide whether the shortest step should rise: a 0.4 second step moved the ball by less than the distance reading's noise (about 1 to 2 inches), a 0.6 second step about 3 inches, 0.9 seconds about 3.6 inches, 1.2 seconds about 4 inches.
8. False wall readings. In a 5-minute roam 13 of 34 wall looks read "near", every one at exactly 8 inches, the closest calibrated row (every lower row reads that value too). The old calibration predates the claw camera: in the claw's view a far wall's base sits at 46 to 58 percent of the picture height, which that calibration calls 8 inches. 52 of the 60 unlabelled near pictures in the wall cache (the Mac keeps every roam picture, the Pi only the newest 20) showed open floor with no wall within a foot, and they are labelled `nothing` in the Walls tab (the labels say who set them, so check them); 8 pictures too dark to use were moved to the wall trash. Scored on them with the Pi's settings (`python -m pi_pipeline.vision.wall_replay DIR --score`), the detector acted on 41 of 59 of them. A reading at the closest row now needs three column groups behind it, which brings that to 30 of 59 at the cost of one real wall between 13 and 24 inches; the claw's own jaw rows are no longer searched for an obstacle. The rest need a new calibration for the claw camera: with the arm in its walking pose, G2 facing a flat wall at 8, 12, 16, 24 and 40 inches (measured with a ruler), take the pictures with `g2calpic SET INCHES` into their own protected set (`~/g2_wall_calibration/SET`, kept apart from the roam pictures and the ordinary shots, hashed and read-only), run the wall calibration from that set, then score it on the roam pictures labelled `nothing`. The old calibration shots predate the arm and are not a usable yardstick for the claw camera.

Waiting for a decision on the Mac, no Pi needed:
- Local training output (the `*_report` folders, the HEAVY and CARPET candidate exports and the head probe) is ignored by git on purpose; the carpet policy and the carpet stall candidate are tracked and kept.
- The gallery grooming (`g2groom`) runs at the start of every hardware session and now applies (`g2groom on`): the auto-saved named classes are capped at 250 and near-twins collapse in the behaviour folders, never touching calibration pictures. Extras move to `G2Memory/_pruned/groom_<date>/` (deleted after 14 days) and the same removal goes to the Pi's restorable trash.
- The background curation loop is removed: `g2groom` at the start of a hardware session does its work (sync, curate, groom, cap), and the Pi empties its own picture trash after 14 days.
- A far-ball class, `greenball-far` (117 pictures where the ball is 20 pixels or smaller across, labelled from the existing green ball pictures), is in `training_data/exploration/promoted/`; it is not yet in the robot's gallery.
- Four empty picture files (2 in the named green ball class, 2 in the curated rejects) hold no data and can be deleted.
- The vision library (7,132 pictures, 87 percent flagged as near-duplicates) is person-capture frames that differ only slightly in pose, so it needs a looser rule before anything is moved or deleted.

Done this session: the camera-only probes (3.67 pictures a second is the module's limit and the smallest size is the fastest), the follow calibration with and without the exposure lock, the arm skills test (launch, toss, tossF, hunt and showOff ok; tossL and tossR play the same motion as toss), the small-step calibration, the picture class cap (250 a class, the green ball set pruned from 752 to 250 with the rest kept aside), and the turn calibrations (arc against pivot, the pivot's cycle and cycle stop), and a 5-minute hardwood roam with the claw looks (8 attention-pose entries, no sag, no fall, one look skipped for a missing camera picture).

Lower priority, when time allows:

- Walk on tile with ARMW, which is now the arm's tile and high-step policy and has not been run (a 5-minute exploration with the floor label set to tile; the journal should say it walks with the ARMW policy).
- Find out what the BiBoard's own `up` moves before some attention stand-ups are.
- Recalibrate the wall estimator for the claw camera, then improve the bump reflex for thin obstacles.
- Check the wake-word log after a few days of use.
- Capture more real walks for system identification, now with ARMW (V7 stays the head's policy).

Longer-term plans are in the [Roadmap](project-plan.md).
