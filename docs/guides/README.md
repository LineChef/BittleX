# docs/guides/

How to do a thing on the current build.

| | |
|---|---|
| [`cheatsheet.md`](cheatsheet.md) | Curated quick-reference, grouped by task (setup, robot, BiBoard tokens, walking, deploying, camera, voice, sim/RL) — command tables + full step sequences. |
| [`voice-commands.md`](voice-commands.md) | Every voice command G2 responds to — local commands + conversational skills, plus G2's character sounds. |
| [`exploration-mode.md`](exploration-mode.md) | How exploration mode works: starting it, legs, picture stops, wall steering and hit detection, sounds, ending it, where the logs are. |
| [`settings-switches.md`](settings-switches.md) | Every environment switch (sounds, exploration, walls, power, standing) with its default. |
| [`pi-bring-up.md`](pi-bring-up.md) | Headless Pi Zero 2 W OS setup runbook. |
| [`gait-deployment.md`](gait-deployment.md) | The sim→real path (ONNX export, on-robot loop, bring-up steps). |
| [`train-vision-model.md`](train-vision-model.md) | The SenseCraft capture→train→deploy flow. |
| [`swappable-llm.md`](swappable-llm.md) | Change the Claude model, or use a cheaper/free OpenAI-style model alone or routed with Claude. |
| [`api-setup.md`](api-setup.md) | Anthropic API key, workspace + spend-limit checklist. |
| [`feature-flags.md`](feature-flags.md) | `G2_FEATURES` staged-bring-up flags. |
| [`models.md`](models.md) | Every model G2 runs (voice, vision, policy): where it lives, source, size, SHA-256, license, and how to fetch or switch it. |
| [`shell-helpers.md`](shell-helpers.md) | Reference of every `g2*` shell helper (generated from `tools/g2_aliases.sh`). |
| [`operating-g2.md`](operating-g2.md) | **Start here for day-to-day use.** Safety rules, how to stop G2, bench mode, power on and off, batteries, first checks. Printable version: [`operating-g2-quick-guide.pdf`](operating-g2-quick-guide.pdf). |
| [`operating-lessons.md`](operating-lessons.md) | Lessons and standing practice from the hardware sessions: deploying and stopping safely, the voice service and microphone, session data processing, background jobs. |
| [`bring-up-sequence.md`](bring-up-sequence.md) | The ordered day-1 hardware bring-up (executable version: `python -m pi_pipeline.bringup`). |
