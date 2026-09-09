# behavior

What G2 does on its own between conversations. Pure logic, driven by the
`BehaviorParams` the `personality` produces — no I/O, mockable, same shape as
`vision/avoidance.py` and `link/recovery.py`.

## `ModeController` — the top-level switch

```
CONVERSE   a conversation is active — preempts everything, no autonomous movement
IDLE       awake, still. After `idle_secs_before_explore` of quiet → EXPLORE
EXPLORE    wandering / investigating. Ends after `explore_max_secs` or on any activity
```

The caller drives it: `on_conversation_start/end`, `on_activity()` (picked up,
addressed, told to stop), and `update()` once per tick for the current `Mode`.

## `Explorer` — wander + investigate

A detection `Frame` + a clock in, an `ExploreDecision` out (`WANDER` / `TURN` /
`APPROACH` / `INVESTIGATE` / `HOLD`, with a `turn` in radians). The caller maps
that onto skills and cues and runs an obstacle reflex underneath; the `Explorer`
only decides intent.

Curiosity (via `BehaviorParams`) makes it linger longer on a find, range wider
per leg, regain interest in seen things faster, and — above ~0.6 — actually
walk up to a novel object instead of only turning to look at it.

## `GesturePicker` — expressive Petoi behaviours (`gestures.py`)

The little "alive" moves, each a built-in OpenCat skill (`link/opencat.py`
tokens, `_ref.npy` for sim). Pure logic + a clock; the caller sends the token
and waits for it to finish, gated on "safe to gesture" (sitting, level, no task).

- **`update(idle_quiet_s, can_gesture)`** — while idle, occasionally emits an
  idle fidget: `STRETCH` / `SCRATCH` / `SNIFF` / `NOD` / `SIT_SHIFT`. Weighted,
  Poisson-ish spacing (`idle_interval_s`), per-gesture cooldown so it never
  repeats or spams.
- **`greeting()`** — one `WAVE` / `SHAKE_PAW` / `PLAY_BOW` at the start of a
  meeting. Call it when `Enrollment` enters `GREETING`, or on a "say hi" intent.
- **`sniff_find()`** — `SNIFF` when `Explorer` lands on a novel object
  (`ExploreAction.INVESTIGATE`).
- **`excited_hop()`** — a `HOP` (`kjpF`) for recognising a bonded person after a
  while / a big find. Hard rate-limited — it's loud.

`Gesture.PLAY_BOW` is also the gait layer's INSPECT peer pose (`buttUp_ref`).

## `Novelty` — what's been seen

Time-decayed record of detection labels and coarse heading bins. `revisit_secs`
later, a thing is "novel" again; a long-unvisited direction pulls hardest.
`is_novel_object()`, `stalest_heading()`.

## Not built yet

The runtime that ties `ModeController` + `Explorer` + the actuator + cues +
memory logging into a loop — that's the Phase 10 integration, and it needs the
camera. This layer is the tested logic it will sit on.
