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
  pipeline. The gait is a learned *residual* on Bittle's scripted `wkF` walk,
  IMU-corrected every control step, conditioned on speed/heading commands and the
  mounted Pi/camera payload. The frozen deployment base is **`run20m_ppo`** (20 M
  steps from scratch: tracks speed commands to 0.007 m/s, walks a −24° descent,
  0 % falls on the payload-on decathlon). It's exported to ONNX and sim-validated
  bit-for-bit against the on-robot control loop. A pre-hardware probe batch
  (2026-09-03) found the gait is *fall-proof but stalls* on terrain it can't
  perceive — root cause: no forward vision. The next gait training is
  **perception-in-the-loop** (Phase 8); the sim + Pi plumbing for the policy's
  own forward terrain feature is now in place. See
  [`docs/rl-runs/robustness-backlog.md`](docs/rl-runs/robustness-backlog.md) and
  [`docs/rl-runs/`](docs/rl-runs/) for history.
- **Companion pipeline** (`pi_pipeline/`) — voice conversation, persistent memory,
  vision / obstacle-avoidance, the BiBoard serial link, and a fall-recovery state
  machine are all scaffolded and run on a dev machine with the hardware mocked;
  **51 tests passing**.
- **Pre-hardware prep** — a headless Pi Zero 2 W bring-up runbook, an idempotent
  provisioning script, a model fetcher, and a voice-pipeline benchmark harness are
  ready to run the moment the SD adapter and robot arrive:
  [`docs/research/pi-bring-up.md`](docs/research/pi-bring-up.md).

For a plain-language tour of how each part works, see
[`docs/how-it-works.md`](docs/how-it-works.md). For the pre-hardware state and the
day-1 checklist, see [`docs/hardware-readiness.md`](docs/hardware-readiness.md).

## Walking policy — what it can do

What is actually trained into `run20m_ppo`, the frozen gait. *Kept current as
abilities land.*

**Trained & verified in sim:**

| Ability | Detail |
|---|---|
| Command-following trot | Forward speed on command — creep (~0.04) · cruise (0.10) · fast (~0.15) m/s, and backward to −0.10; tracks the command to ~0.007 m/s |
| Turn on command | Yaw-rate command; holds a straight heading otherwise (heading drift ~0.1° over 90 s on flat) |
| Stand | Freezes to a stable stance when the speed command is ≈ 0 |
| Slopes | Climbs to +15°, descends to −24°, walks across a cross-slope — 0 % falls |
| Obstacles / rough ground | Scattered terrain + a mild heightfield in training; clears the decathlon obstacle cells (to 85 mm) at 0 % falls |
| Disturbance recovery | Absorbs random pushes and hard impulse shoves (to 1.0 magnitude), sustained forces, a briefly stuck foot — a stumble-catch balance term fights back toward level |
| Payload-conditioned | Walks with the ~76 g mounted Pi + PiSugar + camera load (modelled as a rear spine mass + a forward camera mass); tolerates the mass swing of a draining battery |
| Pick-up / set-down | Re-acquires the gait after being lifted and dropped (emergent — 31/32 in probe testing) |
| Weak-servo tolerance | Keeps walking under simulated overheated-servo torque cutback |
| Long-duration stability | 90 s continuous on flat with no drift, limp, or oscillation |

**Not trained — known limits:**

- **No forward perception.** It only reacts *after* a foot makes contact, so it
  *stalls* (does not fall) against curbs, thin lips, and sustained rough ground.
  Fixing this is the Phase 8 perception-in-the-loop work — the terrain-feature
  plumbing is in place, training waits on hardware + a detection model.
- **No deliberate step-over / go-around.** Needs the forward terrain feature +
  vision (above).
- **No self-righting** — the hardware has no roll-axis joint. Stumble-catch only.
- **No stairs, no jumping.** A jump is planned as a discrete *on-command* skill,
  never folded into the gait ([`docs/behavior-ideas.md`](docs/behavior-ideas.md) B14).

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
