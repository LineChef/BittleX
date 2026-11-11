---
audience: contributor
kind: reference
---

# Goals

A goal is a task G2 works toward in a session of attempts, scoring each attempt from its own sensors and changing the next one. Everything runs on the Pi with no API call.

Behaviour
---------

- Session: "G2, ball goal" (or `g2goal run ball_punt`) starts up to 10 attempts. It runs inside the voice service, borrowing its serial link, IMU fan-out and camera, so the BiBoard port is never closed.
- Approach: The ball chase finds a green ball, walks up to it and punts it. Walking follows the default gait, except the dialing-in steps close to the ball, which use Petoi's scripted walk, and line-up turns use `kwkL` and `kwkR`.
- Knobs: Each approach setting is free (G2 may change it), ask (the operator answers when the voice service restarts) or fixed.
- Judging: Per-knob records are judged by stage, one focus knob at a time, with Thompson sampling taking at most one step.
- Standing goals: A standing goal (the walls goal) is fed by every exploration and chase.
- Priority: Standing goals outrank task goals by default (`priority` in `goals.json`).

Interfaces
----------

- Journal and state: `~/.local/share/g2/goal_journal.jsonl` and `goal_state.json`.
- Commands: `g2goal run`, `report`, `pin`, `limit`, `undo`, `forget` and `verdict GOAL N wrong`.
- Records are keyed by attachment, floor and hardware epoch (`telemetry/hardware_epochs.json`).

Constraints
-----------

- No API call anywhere in goals.
- A new hardware change adds an epoch, so old results are not applied to new hardware.
- Turn and walk times come from G2's own measured pace once there are enough clean samples. Until then the defaults time the moves.

Failure handling
----------------

- A fall ends the attempt and rests G2.
- The stop-and-restart hand-over (`G2_GOAL_INPROCESS=0`) is the fallback if the in-service session cannot run.

Verification
------------

- `pi_pipeline/tests/test_goals.py` includes a made-up-world test that must stay at or above 85% within one step after 30 attempts.
- Robot: A session ends with a journal entry per attempt, readable with `g2goal report`.

See [Goals](../guides/goals.md) and [Punt](../guides/punt.md).
