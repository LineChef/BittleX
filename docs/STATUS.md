---
audience: visitor
kind: overview
---

# Current status

G2 is a Petoi Bittle X quadruped that walks with a learned gait, listens and talks through Claude, remembers what it is told, and explores on its own. This page says what works today, what has only been tested in part, and what is still being fixed. It is the single page for the current state, updated after each round of hardware testing, and carries its last-changed date in the site header. Dated write-ups stay in the repository's working notes.

The longer story of how each part works is in [How it works](how-it-works.md); the full list of abilities is in [Capabilities](capabilities.md).

## At a glance

- Walking: Works on hardwood floors. Tile and carpet are not solved.
- Voice conversation: Works. Wake word, spoken commands, Claude replies, speech out.
- Memory: Works. Facts and past conversations persist between sessions.
- Exploration: Works in a small room. Camera and speech timing need more testing.
- Ball goal (punting a ball): Works some of the time. Falls during turns are the main problem.
- Falls: The biggest open problem. G2 sometimes tips over at pose and turn changes.

## What G2 is made of

- Body: A Bittle X V2 with a BiBoard control board, running Petoi's OpenCat firmware.
- Brain: A Raspberry Pi Zero 2 W in a printed pod on G2's back. It runs the voice, memory, vision and walking software, and talks to the BiBoard over a serial cable. Details in [As built](hardware/as-built.md).
- Eyes: A Grove Vision AI V2 camera that runs object detection on the camera itself.
- Ears and voice: A small microphone and speaker on the Pi.
- Neck attachment: A claw arm is fitted, with its camera on the claw. It replaced the Petoi AI Head that was fitted earlier. Wider shoulders are fitted. G2 now weighs a little over 530 g with all of it. How attachments change the settings: [Attachments](guides/attachments.md).
- Power: G2 runs on its own battery pack. The Pi runs on a small PiSugar pack that lasts about three hours.

## What works

### Walking

The deployed walking policy is a small neural network that makes constant corrections on top of Petoi's scripted walk. It was trained in simulation, then calibrated on a hardwood floor. On hardwood it walks about 4 ft in 12 seconds and drifts a few inches to one side, which a fixed foot adjustment trims. The arm fitted today has its own walking policy, which has been deployed but not yet walked on the real robot. See [Walking policy](rl/walking-policy.md) and [Gait deployment](guides/gait-deployment.md).

Every stand-up is a slow, eased movement played by the board. G2 never uses the firmware's own quick stand-up. A pose check runs before each stand-up, but it has not been tried on the robot yet.

Some Petoi tricks are switched off because they tip G2 over with the current weight: wave, scratch, shake paw, high five and hop. See [Disabled moves](hardware/disabled-moves.md).

### Voice and memory

- The wake word is "Gee Two". Short commands such as stop, sleep and "walk for ten seconds" are handled on the Pi without a network call. Everything else goes to Claude. See [Voice commands](guides/voice-commands.md).
- Memory is live. G2 keeps a log of conversations and a short list of lasting facts, and looks up relevant ones before each reply.
- G2 goes to sleep after five minutes at rest.
- The battery of both G2 and the Pi is monitored, with spoken warnings.

### Exploration

G2 can wander a room, turn away from walls, react to bumps, stop to take pictures and say what it notices. It has run for several minutes at a time in a small room. See [Exploration mode](guides/exploration-mode.md).

### The ball goal

G2 can be given a goal: find a ball, walk up to it and punt it. A session is up to ten attempts, and G2 adjusts its approach between attempts based on what worked. More on this in [Goals](guides/goals.md). Results are mixed. Early sessions scored well, and later ones dropped. Part of the cause was a default turn speed far lower than the real turn speed, which made turns overshoot. The corrected default is deployed and has not been tested on G2.

## What is deployed

Everything below is on the Pi.

- Walking policy: V7, a policy trained from scratch for 20 million steps on the pod and AI-head payload. It sends a joint command every third control tick and does not use heading. It fell less than the previous policy in simulation and climbed the lowest step far more often. Earlier policies stay on the Pi as fallbacks. Rolling back means pointing `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py` at the earlier file and deploying.
- Steering: The heading hold is off by default. Everyday walks use a fixed front-left foot trim per policy, measured on hardwood only.
- Walk start: After a firmware gait or skill, a walk first settles into a still stand and never starts while G2 is tilted past 30 degrees.
- Stand-ups: Every stand-up is the eased stand-up played by the board, from rest, a sit, the attention pose or any pose the board reports. G2 reads its pose first (three tries). An unreadable or unusual pose gets a rest first. Each stand-up is logged. A stop out of a stride stays immediate.
- Moves into skills: The serial link eases the legs from the known pose into each skill, so no joint exceeds 80 degrees per second.
- Disabled moves: Wave, scratch, shake paw, high five and hop are refused, because they tip G2 over on this payload.
- Voice: Wake word, local commands, conversation mode ("let's talk") and spoken sounds. Every wake trigger is logged with what followed it.
- Sleep: After five minutes at rest.
- Memory: Live: facts, exchange log, pinned core facts and sleep-time tidying. Reflection is switched off; the recaps are still written.
- Exploration: Two tiers: stationary and attentive, and a roam armed by voice. Roams have timed turns, a wall avoider, a hit sequence from the motion sensor, narration and scheduled survey pictures.
- Robustness: A dead camera reader restarts, a failed behaviour tick is skipped, and every walk log records why the walk ended.
- Battery alarms: Voice warnings for both G2's pack and the Pi's runtime.
- Sounds: One at a time, through an audio gate, at one global volume.

## Tested on the real robot

- Walking: Six steady hardwood runs with the first policy. The next policies were tested on hardwood and over a quarter-inch ramped threshold with no falls. V7, with the pod and head, did three 12-second walks with no falls.
- Poses and transitions: Stand, sit, rest and stand-from-sit are smooth with firmware balance off. The wave flipped G2 twice.
- With the arm, on hardwood: Petoi's walk covered 4 ft 4 in in 10 s. The first arm policy covered 4 ft 5 in in 12.5 s, about 5 in off line. The claw's pick, put and lunge moves ran. The lunge throws a 3 in ball about 18 in, but the claw cannot grab it.
- Exploration: Short roams in tight rooms produced wall turns, hit sequences, survey pictures and narration. One roam ended in a tip-over at a survey stop.
- Voice to Claude to walk: Spoken replies and a full listen, talk and walk run.
- Wall avoider: Judged "working fairly well" with the camera in its old position.
- Ball goal: The first sessions scored a few punts, and the finder, turns and wall reading were then improved several times. Daily success rates fell from about one in four early on to about one in ten by mid-November. Part of the cause is a turn-speed mismatch that is now fixed in code. A first-stand-up fall is more common than later ones.

### Not yet run on G2

The walls goal, "G2, practise", the spoken goal suggestions and operator overrides, the policy walk toward a ball with self-measured pace, vision reflexes while walking, the full application over a long period, the teach tool, the recognition labelling pictures, the per-leg wall look, conversation mode as a hardware test, and the pose read before stand-up.

## Known limitations

1. Falls at transitions: Most falls happen in turns and pose changes. Of 154 logged ball-goal attempts, 18 recorded a fall, 13 of them in turns, and most falls are never logged. Safeguards exist (a pose gate, a steady check, calm stops, the claw look as the only look) but none has had a valid test round. Voided rounds were caused by a drill bug, a voice-module move and a silent board.
2. Legs going limp: After about ten seconds standing still, the leg servos can lose strength. The leading explanation is the servos' overload protection, worst on the back legs, which carry the raised arm. A sag check from the motion sensor now re-stands G2. It is untested on the robot.
3. The BiBoard going silent: The board sometimes streams motion data but ignores every command until power-cycled. Reseating the Pi-to-BiBoard plug cured it once. The ball goal now runs inside the voice service so the serial port is never closed. This has not been tried on G2.
4. Garbled serial reads: right after the voice service stops. The pack reading comes back empty, so the battery gate warns and continues. A restarting service can hold the port, so check before reading the board.
5. The board's own voice module: hears the television and starts moves by itself. The command log marks such moves "not from the Pi". "Be quiet" makes the module ignore basic commands, and there is no known way to silence only its spoken "ok".
6. The camera: answers each request with the previous picture, so each picture is taken twice and the first dropped. It sometimes stops answering during exploration.
7. The wall estimator: needs recalibrating for the claw camera. It reads "8 in" almost every time, so the chase distrusts that reading.
8. Late walk ticks: reached 30 percent in exploration. The serial send does not wait for the bytes to drain. This is untested.
9. Speech arrives 7 to 17 seconds late: during exploration. Lines are now cached and pre-made at idle.
10. Wake-word false triggers: About four in seven triggers were nearby talk. A confidence threshold is set and is being tuned from the log.
11. The bump reflex misses thin obstacles: such as chair legs.
12. Heading drift on other floors: Hardwood is handled by the trim. Tile is unresolved, and carpet is open.
13. Carpet: Every gait tried fails on about a quarter inch of pile. Falls go sideways to the right.
14. Ledges: No policy crosses step-ups above 0.3 in in simulation.
15. Minor: An unexplained ticking from the board during some walks, and a stiffer, louder back-left shoulder servo.

## Open decisions

- The Petoi AI Head: is an extra voice model started by its button. Claude stays the main brain and nothing is integrated for now.
- Claude descriptions of survey pictures: (one billed call per picture) are on hold.
- A new 20-million-step training run: starts only on explicit approval and never on top of a finished long run.
- Gait comparisons on G2: are not run. Policies are compared in simulation only.

## What happens next

Testing follows a simple rule: collect data from normal runs first, then run a targeted test only where the logs cannot answer the question.

1. Run the ball goal inside the voice service, then read the stand-up and turn logs.
2. Explore a bigger room to check the camera fix, picture speed, late ticks and the four milestone pictures.
3. Test the survey poses on their own to find which one tipped G2 over.
4. Recalibrate the wall estimator for the claw camera, then improve the bump reflex for thin obstacles.
5. Check the wake-word log after a few days of use.
6. Capture more real walks for system identification, now with V7.

Longer-term plans are in the [Roadmap](project-plan.md).
