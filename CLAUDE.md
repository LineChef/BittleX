# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

This repo is in early scaffolding — only READMEs, `docs/project-plan.md`, and an empty
`requirements.txt` exist so far. No source code, build system, linter, or test suite
has been added yet. There are no commands to run yet; once code lands in a given
directory (see below), check that directory's README first, since dependencies and
tooling are meant to be added per-phase as described in `docs/project-plan.md`.

## What This Project Is

A Petoi Bittle X quadruped robot that learns to walk via reinforcement learning,
perceives its environment through an onboard AI camera, holds voice conversations
powered by the Claude API, and builds persistent memory across conversations. Full
context, hardware list, and phased roadmap: `docs/project-plan.md`. The builder has a
web dev (HTML/JS/CSS) background and no prior Python experience — favor explaining
Python idioms in terms of JS/CSS analogues when relevant, and keep in mind this is
their first hardware/robotics project.

## Repo Structure (intended)

```
rl_training/       # Simulation-based RL training (opencat-gym-sim2real based, PyBullet + Stable-Baselines3)
pi_pipeline/
  voice/            # Speech-to-text -> Claude API -> text-to-speech
  memory/           # Persistent conversation storage/retrieval (SQLite or lightweight vector store)
  vision/           # Camera integration, on-device obstacle avoidance, scene description via Claude
docs/               # Project plan, notes, learnings
```

`rl_training` and `pi_pipeline` are meant to remain independent systems (movement,
vision, voice, memory) rather than a single unified "brain" — this is a deliberate
design choice from the project plan, not an oversight, so avoid coupling them
unnecessarily as they're built out.

## Secrets

Never commit API keys/credentials. Per `.gitignore`, secrets live in `.env`,
`config.local.*`, or files matching `**/secrets.py` / `**/api_keys.py` — all
gitignored. The Claude/Anthropic API key used in `pi_pipeline` is billed separately
from a Claude Pro subscription (usage-based).

## Large / Local Files

Trained RL model checkpoints (`rl_training/models/`, `rl_training/logs/`, `*.zip`,
`*.pkl`) and the local conversation memory DB (`pi_pipeline/memory/*.db`,
`pi_pipeline/memory/data/`) are gitignored — don't try to commit these.
