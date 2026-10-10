# Robotics Project with Bittle X

A robotics project where I teach a quadruped robot to:

- walk using reinforcement learning
- perceive its environment through an onboard AI camera that runs vision models on-device (Grove Vision AI V2)
- hold natural voice conversations powered by Claude
- build persistent memory of its interactions over time

The full roadmap and decision log are in
[`docs/project-plan.md`](docs/project-plan.md).

## Project Goals

- **Locomotion**: a *command-following* walking policy trained by reinforcement
  learning (simulation → sim-to-real), rather than switching between hand-scripted
  gaits. It takes a speed and heading command and produces the gait — stand,
  start/stop, forward, backward — and stays upright across slopes, obstacles,
  rough ground, shoves, and the weight shift from the mounted Pi/camera payload.
  Turning is deliberately **not** part of the trained policy — real turning
  depends on foot-slip and a firmware gyro-assist a training sim can't
  reproduce, so it's handled by falling back to scripted firmware gaits
  (`wkL`/`wkR`) instead.
- **Recovery**: detect a fall from the IMU, run the firmware get-up skill for the
  falls the hardware *can* recover from, and know when it needs a human.
- **Perception → navigation**: an onboard AI vision module for obstacle
  detection, and reactive skill-switching — recognize an obstacle or ledge it
  can't just walk over, and swap in the right scripted response (step over,
  climb, back out) before handing back to the walk policy.
- **Voice**: natural spoken conversation powered by the Claude API (speech-to-text
  → Claude → text-to-speech), with movement used as body language. Running on the Pi
  with a real microphone and speaker; "shut down" lies G2 down and powers the Pi off.
  It can also take a picture and describe what it sees.
- **Memory**: persistent context across conversations (facts ranked by importance,
  a sleep-time consolidation pass, and a log of which facts shape answers), and a
  sense of place (which room it's in) built up over time.
- **Power awareness**: low-battery alerts for G2's pack, a measured runtime estimate
  for the Pi's battery, and a Wi-Fi fallback to a phone hotspot.
- **Autonomy**: Claude as a slow deliberative layer on top of the reactive
  control — deciding where to go, what to look at, and whether to approach
  something, from what it sees and remembers.

## Hardware

| Component | Notes |
|---|---|
| Petoi Bittle X V2 (alloy servos) | Core quadruped platform, built on OpenCat / BiBoard V1 (ESP32) |
| Raspberry Pi Zero 2 W | Runs the voice / memory / vision / Claude pipeline |
| PiSugar S 1200 mAh | Independent Pi power, not shared with the servo battery — see [`docs/hardware/pi-power.md`](docs/hardware/pi-power.md) |
| Petoi AI Vision Camera Module | Grove Vision AI V2, onboard neural processor for on-device inference |

Full parts list, costs, and vendor-doc specs: [`docs/hardware/parts-and-decisions.md`](docs/hardware/parts-and-decisions.md)
and [`docs/hardware/specs.md`](docs/hardware/specs.md).

## Project Status

The current state — what is deployed, what has been tested on the robot, open problems and next steps — is in
**[`docs/STATUS.md`](docs/STATUS.md)**. Everything else:

- What G2 can do, item by item: [`docs/capabilities.md`](docs/capabilities.md)
- How each part works, in plain language: [`docs/how-it-works.md`](docs/how-it-works.md)
- Roadmap and decisions: [`docs/project-plan.md`](docs/project-plan.md); open work by ID: [`docs/backlog.md`](docs/backlog.md)
- Dated history and data: [`docs/history.md`](docs/history.md), [`docs/rl/real-walk-log.md`](docs/rl/real-walk-log.md)
- Index of all docs: [`docs/README.md`](docs/README.md)

## Voice commands

Say the wake word, "gee two" (or "hey buddy"), then the command. A short beep means he is listening, a lower boop means he has your words. The full list, with what each one does, is in
**[`docs/guides/voice-commands.md`](docs/guides/voice-commands.md)**; the ones you will use most:

| Say | What happens |
|---|---|
| "G2, explore" / "go ahead and look around" | exploration mode ([how it works](docs/guides/exploration-mode.md)) |
| "that's enough" / "end exploration mode" | ends the exploration |
| "walk forward for ten seconds", "come here" | a walk, or a walk to you |
| "hi step" / "walk normally" | switches the walking gait |
| "emergency stop" / "resume" | freezes him now / lets him move again |
| "go to sleep" / "shut down" | curls up and sleeps / lies down and goes dormant |
| "switch to English" | resets the voice module's language (when it falls back to Korean) |

Switches for sounds and behaviours: [`docs/guides/settings-switches.md`](docs/guides/settings-switches.md).

## Walking policy

The gait is a learned control layer over Bittle's built-in `wkF` walk: every control step (80 Hz) it reads the IMU, the
gait-phase clock and recent history and outputs a bounded correction to the scripted joint angles, following speed and
heading commands. What it learned, how it was trained and its limits: [`docs/rl/walking-policy.md`](docs/rl/walking-policy.md);
the training history: [`docs/rl/hw1-log.md`](docs/rl/hw1-log.md); how it does on the real robot:
[`docs/rl/real-walk-log.md`](docs/rl/real-walk-log.md).

## Repo Structure

```
rl_training/opencat-gym/   # Simulation-based RL training (based on ger01d/opencat-gym)
pi_pipeline/
  voice/       # Speech-to-text, Claude API integration, text-to-speech
  memory/      # Persistent conversation memory / retrieval
  vision/      # Camera integration, obstacle avoidance, scene description
  link/        # BiBoard serial link + fall-recovery state machine
  gait/        # On-robot policy loop, deploy map, servo thermal guard
  behavior/    # Autonomous layer: mode controller, explore, idle-REST posture
  personality/ # Composable traits -> BehaviorParams
  diag/        # Black-box session logger + ring buffer (hardware debugging)
  power/       # Pi power-management helpers (governor, Wi-Fi, peripherals)
tools/      # Report generators and other standalone utilities
docs/       # Current status, project plan, backlog, run logs, guides, research notes
blueprints/ # Hardware build record + wiring diagrams
```

## Setup

**RL training**: requires Python ≥ 3.10 (macOS ships an EOL 3.8, so this project
uses a `.venv` built with Homebrew's `python@3.11`). See
[`rl_training/README.md`](rl_training/README.md) for setup, including a required
macOS build workaround for `pybullet`.

**Companion pipeline**: `pi_pipeline/requirements.txt` for the core (text-mode)
deps, `requirements-audio.txt` for the voice backends. Pinned to versions verified
to have prebuilt ARM wheels so the Pi install compiles nothing.
