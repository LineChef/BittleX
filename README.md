# Bittle X Companion Robot

A Petoi Bittle X quadruped that learns to walk via reinforcement learning, perceives its environment through an onboard camera, holds voice conversations powered by Claude, and builds persistent memory of past interactions over time.

## Project Goals

- **Locomotion**: train a walking policy via reinforcement learning (simulation → sim-to-real transfer) rather than hand-scripted gaits
- **Perception**: obstacle avoidance and environment awareness via an onboard AI vision module
- **Voice**: natural conversation powered by the Claude API (speech-to-text → Claude → text-to-speech)
- **Memory**: persistent context that carries across conversations

## Hardware

| Component | Notes |
|---|---|
| Petoi Bittle X V2 (alloy servos) | Core quadruped platform, built on OpenCat |
| Raspberry Pi Zero 2 WH | Runs the voice/memory/Claude integration pipeline |
| PiSugar S 1200mAh | Independent Pi power (not shared with the servo battery) — see [`docs/pi-power.md`](docs/pi-power.md) |
| Petoi AI Vision Camera Module | Grove Vision AI V2, onboard neural processor for on-device inference |

Full parts list and cost breakdown: see [`docs/project-plan.md`](docs/project-plan.md)

## Project Status

🚧 Early build phase — see the project plan for the full roadmap.

## Repo Structure

```
rl_training/       # Simulation-based RL training (based on ger01d/opencat-gym)
pi_pipeline/
  voice/            # Speech-to-text, Claude API integration, text-to-speech
  memory/           # Persistent conversation memory / retrieval
  vision/           # Camera integration, obstacle avoidance, scene description
docs/               # Project plan, notes, learnings
```

## Setup

**Secrets**: managed via environment variables. Copy `.env.example` to `.env` and fill
in real values (`.env` is gitignored and never committed). Loaded at runtime via
`python-dotenv` (added once Phase 7 code lands).

**RL training**: requires Python >= 3.10 (macOS ships an EOL 3.8, so this project uses
a `.venv` built with Homebrew's `python@3.11`). See [`rl_training/README.md`](rl_training/README.md)
for setup (including a required macOS build workaround for `pybullet`).

## Background

This is a personal learning project — first hands-on hardware/robotics build, and first project written in Python (coming from a web dev background in HTML/JS/CSS). Follows the roadmap in `docs/project-plan.md`.
