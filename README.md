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
  start/stop, forward, backward, turn — and stays upright across slopes,
  obstacles, rough ground, shoves, and the weight shift from the mounted Pi/camera
  payload.
- **Recovery**: detect a fall from the IMU, run the firmware get-up skill for the
  falls the hardware *can* recover from, and know when it needs a human.
- **Perception → navigation**: an onboard AI vision module for obstacle detection,
  and vision-guided movement — pick a visible target, head toward it, and correct
  course along the way.
- **Voice**: natural spoken conversation powered by the Claude API (speech-to-text
  → Claude → text-to-speech), with movement used as body language.
- **Memory**: persistent context across conversations, and a sense of place
  (which room it's in) built up over time.
- **Autonomy**: Claude as a slow deliberative layer on top of the reactive
  control — deciding where to go, what to look at, and whether to approach
  something, from what it sees and remembers.

## Hardware

| Component | Notes |
|---|---|
| Petoi Bittle X V2 (alloy servos) | Core quadruped platform, built on OpenCat / BiBoard V1 (ESP32) |
| Raspberry Pi Zero 2 W | Runs the voice / memory / vision / Claude pipeline |
| PiSugar S 1200 mAh | Independent Pi power, not shared with the servo battery — see [`docs/research/pi-power.md`](docs/research/pi-power.md) |
| Petoi AI Vision Camera Module | Grove Vision AI V2, onboard neural processor for on-device inference |

Full parts list, costs, and vendor-doc specs: [`docs/project-plan.md`](docs/project-plan.md)
and [`docs/research/hardware-specs.md`](docs/research/hardware-specs.md).

## Project Status

The Pi Zero 2, PiSugar S, microSD card, and power supply have arrived; the Bittle
X and camera are still a few weeks out. Everything runs software-only or with the
hardware mocked for now.

- **RL locomotion** (`rl_training/opencat-gym/`) — a PyBullet + Stable-Baselines3
  pipeline. The best sim gait so far is `cov_r1_slope`: a learned *residual* on
  Bittle's scripted `wkF` walk, IMU-corrected every control step, that also
  handles slopes. It's currently in a **refinement cycle** — adding
  command-following locomotion (speed + heading commands; stand, backward, turn),
  wider correction authority, expanded domain randomization, and a modeled
  Pi/camera payload — building toward a qualified recipe and one large
  consolidation training run. History in [`docs/rl-runs/`](docs/rl-runs/); a survey
  of other Bittle RL projects in
  [`docs/research/bittle-rl-projects.md`](docs/research/bittle-rl-projects.md); the
  staged plan in
  [`docs/rl-runs/refinement-regimen.md`](docs/rl-runs/refinement-regimen.md).
- **Companion pipeline** (`pi_pipeline/`) — voice conversation, persistent memory,
  vision / obstacle-avoidance, the BiBoard serial link, and a fall-recovery state
  machine are all scaffolded and run on a dev machine with the hardware mocked;
  **42 tests passing**.
- **Pre-hardware prep** — a headless Pi Zero 2 W bring-up runbook, an idempotent
  provisioning script, a model fetcher, and a voice-pipeline benchmark harness are
  ready to run the moment the SD adapter and robot arrive:
  [`docs/research/pi-bring-up.md`](docs/research/pi-bring-up.md).

For a plain-language tour of how each part works, see
[`docs/how-it-works.md`](docs/how-it-works.md). For the pre-hardware state and the
day-1 checklist, see [`docs/hardware-readiness.md`](docs/hardware-readiness.md).

## Repo Structure

```
rl_training/opencat-gym/   # Simulation-based RL training (based on ger01d/opencat-gym)
pi_pipeline/
  voice/    # Speech-to-text, Claude API integration, text-to-speech
  memory/   # Persistent conversation memory / retrieval
  vision/   # Camera integration, obstacle avoidance, scene description
  link/     # BiBoard serial link + fall-recovery state machine
tools/      # Report generators and other standalone utilities
docs/       # Project plan, run logs, research notes
```

## Setup

**RL training**: requires Python ≥ 3.10 (macOS ships an EOL 3.8, so this project
uses a `.venv` built with Homebrew's `python@3.11`). See
[`rl_training/README.md`](rl_training/README.md) for setup, including a required
macOS build workaround for `pybullet`.

**Companion pipeline**: `pi_pipeline/requirements.txt` for the core (text-mode)
deps, `requirements-audio.txt` for the voice backends. Pinned to versions verified
to have prebuilt ARM wheels so the Pi install compiles nothing.
