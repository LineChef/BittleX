---
audience: visitor
kind: overview
---

# Roadmap

The G2 project is built in phases. This page lists each phase, where it stands and what comes next. For the current state of the hardware, see [Current status](STATUS.md). For the list of abilities, see [Capabilities](capabilities.md).

## The goal

Build a Petoi Bittle X quadruped, called G2, that:

1. learns to walk through reinforcement learning instead of hand-written keyframes,
2. sees its surroundings through an onboard camera,
3. holds spoken conversations through the Claude API, and
4. keeps a lasting memory of past conversations.

Walking, vision, voice and memory are separate systems that run side by side. They are not one controller. [How it works](how-it-works.md) explains each.

## Phases

- **Repo setup and orientation**: Done.
- **Walking policy training in simulation**: Done. Several policies were trained, and one is deployed. New gait training starts only on explicit approval.
- **Hardware assembly**: Done. The Pi sits in a printed pod, the camera is mounted, and a microphone and speaker are fitted. A claw arm is fitted on the neck. See [As built](hardware/as-built.md).
- **Basic control**: Done. A serial link to the control board drives walking, turning and the built-in skills.
- **Sim-to-real deployment**: Walking works on hardwood. Layers for steering, stand-ups, falls and heat protect it. Tile and carpet remain open.
- **Voice and Claude**: Working on the robot. Wake word, spoken commands and conversation run on the Pi.
- **Perception**: The camera detects objects on its own hardware. "What do you see", ball finding and exploration pictures work. Vision-based navigation is switched off for now.
- **Memory**: Working. Facts and past conversations persist on the Pi.
- **Integration**: In progress. Exploration and the ball goal run on G2. A long run of the full application is still to do.

## Decisions that shape the project

- **Every new training run is a fresh candidate.** A run is scored against the deployed policy and replaces it only if it is clearly better. Policies are never trained on top of a finished long run.
- **Difficulty never exceeds what a capable policy can pass.** Each simulated hazard has a measured upper limit, and impossible episodes are treated as bugs.
- **Vision stays out of the walking policy.** Putting vision inside the policy is out of scope. Vision instead chooses a scripted skill or a speed above the gait.
- **Cloud calls are used sparingly.** Anything that can run on the Pi, such as command tables, rules and geometry, runs there. See [Voice commands](guides/voice-commands.md) for which commands stay local.
- **Every stand-up is the slow, eased stand-up.** G2 never uses the firmware's own quick stand-up.
- **The firmware is not forked.** The software is an application on top of Petoi's OpenCat firmware.

## What comes next

1. Prove that G2 stays upright at pose and turn changes. Falls there are the main open problem.
2. Run the ball goal inside the voice service and compare it with the earlier standalone runs.
3. Explore a larger room to test the camera and speech timing.
4. Recalibrate the wall-distance estimate for the claw camera.
5. Find a gait that walks on carpet, and a higher-stepping gait that crosses small ledges.

Ideas that are not yet built include place memory, reflection on past sessions and a firmware change that would let the Pi act as a button press. They are not part of the running build.
