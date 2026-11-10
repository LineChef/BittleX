---
audience: visitor
kind: overview
---

# Current status

G2 is a Petoi Bittle X quadruped that walks with a learned gait, listens and talks through Claude, remembers what it is told, and explores on its own. This page says what works today, what has only been tested in part, and what is still being fixed. It is updated after each round of hardware testing and was last revised on 2026-11-09.

The longer story of how each part works is in [How it works](how-it-works.md); the full list of abilities is in [Capabilities](capabilities.md).

## At a glance

| Area | Where it stands |
|---|---|
| Walking | Works on hardwood floors. Tile and carpet are not solved. |
| Voice conversation | Works. Wake word, spoken commands, Claude replies, speech out. |
| Memory | Works. Facts and past conversations persist between sessions. |
| Exploration | Works in a small room. Camera and speech timing need more testing. |
| Ball goal (punting a ball) | Works some of the time. Falls during turns are the main problem. |
| Falls | The biggest open problem. G2 sometimes tips over at pose and turn changes. |

## What G2 is made of

- **Body.** A Bittle X V2 with a BiBoard control board, running Petoi's OpenCat firmware.
- **Brain.** A Raspberry Pi Zero 2 W in a printed pod on G2's back. It runs the voice, memory, vision and walking software, and talks to the BiBoard over a serial cable. Details in [As built](hardware/as-built.md).
- **Eyes.** A Grove Vision AI V2 camera that runs object detection on the camera itself.
- **Ears and voice.** A small microphone and speaker on the Pi.
- **Neck attachment.** A claw arm is fitted, with its camera on the claw. It replaced the Petoi AI Head that was fitted earlier. Wider shoulders were added on 2026-11-03. G2 now weighs a little over 530 g with all of it. How attachments change the settings: [Attachments](guides/attachments.md).
- **Power.** G2 runs on its own battery pack. The Pi runs on a small PiSugar pack that lasts about three hours.

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

G2 can be given a goal: find a ball, walk up to it and punt it. A session is up to ten attempts, and G2 adjusts its approach between attempts based on what worked. More on this in [Goals](guides/goals.md). Results are mixed. Early sessions scored well, and later ones dropped. Part of the cause was found on 2026-11-09: the default turn speed was far lower than the real turn speed, so turns overshot. The fix is deployed and has not been tested on G2.

## What is still being fixed

1. **Falls at transitions.** Most falls happen in turns and when changing pose. Safeguards are built (a pose check, a steady check before pose changes, gentler stops), but none has yet been proven in a clean test.
2. **The BiBoard going silent.** Now and then the board stops answering the Pi, usually until it is power-cycled. The first thing to check is the plug between the Pi and the board, which comes loose in falls.
3. **Legs going limp.** After standing still for about ten seconds, the leg servos sometimes lose strength and G2 sags. The leading explanation is the servos' own overload protection. A check from the motion sensor now catches a sag and re-stands G2, but it is untested on the robot.
4. **Carpet.** Every gait tried so far fails on carpet. Petoi's own carpet gait is used when carpet mode is requested.
5. **The camera.** It sometimes stops answering during exploration, and its wall-distance estimate needs recalibrating for the claw camera.
6. **Wake-word false triggers.** Nearby conversations sometimes wake G2. A confidence threshold is now set and is being tuned from logs.
7. **Stepping over ledges.** No trained policy can cross steps higher than about 0.3 in in simulation.

## What happens next

Testing follows a simple rule: collect data from normal runs first, then run a targeted test only where the logs cannot answer the question.

1. Run the ball goal inside the voice service (the first full test of that setup), then read the logs of the stand-ups and turns.
2. Explore a bigger room to check the camera fix, picture speed and speech timing.
3. Test the survey poses on their own to find which one tips G2 over.
4. Recalibrate the wall estimator for the claw camera.

Longer-term plans are in the [Roadmap](project-plan.md).
