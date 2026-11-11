---
audience: visitor
kind: overview
---

# G2 documentation

G2 is a Petoi Bittle X robot dog that walks with a learned gait, sees through an onboard camera, talks through the Claude API and remembers past conversations. These pages explain how G2 works, how to build and run it, and how the software is organised.

New here
--------

Read these three pages in order.

1. [How it works](how-it-works.md) is a plain-language tour of walking, voice, memory, vision and behaviour.
2. [What G2 can do](capabilities.md) lists the abilities and how well each one works today.
3. [Current status](STATUS.md) says what is deployed, what has been tested on the robot and what is still broken.

Build and operate G2
--------------------

- Build G2 and bring up its software, from parts to a walking robot: [Reproducing G2](guides/reproduce-g2.md)
- Run G2 day to day, stop it safely and handle the batteries: [Operating G2](guides/operating-g2.md)
- Look up a command: [Cheat sheet](guides/cheatsheet.md)
- See every spoken command: [Voice commands](guides/voice-commands.md)
- Set up the Raspberry Pi: [Pi bring-up](guides/pi-bring-up.md)
- Bring the hardware up step by step: [Bring-up sequence](guides/bring-up-sequence.md)
- Change settings and switches: [Settings and switches](guides/settings-switches.md)
- Understand what G2 is made of: [As built](hardware/as-built.md)
- Follow the wiring, mounting and calibration record: [Blueprints](../blueprints/README.md)

The full list of guides is in [Guides](guides/README.md). Hardware pages are in [Hardware](hardware/README.md), and camera and detection pages are in [Vision](vision/README.md).

Under the hood
--------------

- How each subsystem behaves, with its settings and how to verify it: [Specification](specification/README.md)
- How the robot, the Pi and the dev machine fit together: [Architecture](architecture.md)
- Where each package of code is documented: [Code map](code-map.md)
- How the walking policy is trained and deployed: [Gait training](rl/README.md)
- The phases of the project and what comes next: [Roadmap](project-plan.md)

Conventions
-----------

- G2 is the name of this robot, so pages say "G2" and not "the robot".
- Distances and sizes are given in inches, with metric figures only where a part's specification uses them.
- Times are in Eastern time.
