# behavior

What G2 does on its own between conversations. Pure logic, driven by the
`BehaviorParams` the `personality` produces — no I/O, mockable, same shape as
`vision/avoidance.py` and `link/recovery.py`.

## `BehaviorDriver` — the runtime that ties it together (`driver.py`)

`BehaviorDriver.tick(DriverInputs) -> DriverTick` composes `ModeController` +
`Explorer`/`Novelty` + `IdlePosture` + `SleepMode` + `MoodModel` + `Chirper` +
`GesturePicker` + `Enrollment` + optional `CliffGuard` and returns an ordered
list of abstract `Effect`s
(SKILL / STOP / WALK / TURN / HEAD / SPEAK / CAPTURE / CUE / CHIRP / POWER /
DIAG). Priority each tick: mood (scales the idle-descent timing) → deep-idle
**sleep** gate (owns the robot while DOZING / ASLEEP; wakes on wake word / tap /
lift / loud sound / spoken-to / command) → enrollment → a running
WAKE/settle/PEEK choreography (safety preempts) → CliffGuard reflex → CONVERSE →
EXPLORE (+ a sniff at a find) → IDLE descent (+ idle fidgets). A bonded person
seen after an absence fires one excited hop. Emotive `CHIRP`s (one shared
`Chirper`, ≤1/tick) fire on recognition, a startle, a greeting, an edge reflex,
and sleep entry. `DriverTick` also carries `mood`, `sleep_state`, and
`seek_attention`. Still no I/O — `bindings.py` maps the effects onto real sinks.

## `DriverBindings` — the binding layer (`bindings.py`)

`DriverBindings.dispatch(tick)` routes each `Effect` kind to an injected sink
(`actuator` / `tts` / `camera` / `cue` / `walker` / `head` / `power` /
`on_diag`); a missing sink drops-and-warns. `CHIRP` → `actuator.perform` with an
`opencat.beep(...)` string; `POWER` → `power.set_profile("headless"|"interactive")`.
`MockBindings` records every call, so the whole driver loop is exercised
end-to-end in tests. On hardware: supply the real sinks (`voice/actuator.py`,
`voice/tts.py`, `voice/cues.py`, `pi_pipeline.power`, a frame grabber, the
session log) + the input plumbing (vision frame, IMU state, mic events).

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

## `IdlePosture` — staged descent when idle (`idle_posture.py`)

ACTIVE → SIT → RESTING → WAKING. Sits after `sit_after_s` of quiet, lies down
after more quiet (if `safe_to_rest`, not told to "stay", person-present stretches
the timer), emits periodic PEEK life-signs while resting, rouses (not snaps)
awake. Emits abstract `PostureAction`s.

## `SleepMode` — deep idle below RESTING (`sleep_mode.py`)

AWAKE → DOZING → ASLEEP → ROUSING. Auto-sleeps after long continuous RESTING
(person-present blocks the *auto* path, not the explicit command), `min_sleep_s`
anti-thrash, wakes on IMU tap / wake word / loud sound. Emits `ENTER_SLEEP`
(curl `kzz` + camera off + `power headless`) / `WAKE`.

## `Enrollment` — "G2, meet <name>" (`enrollment.py`)

The capture FSM for teaching G2 a new face: greeting → guided capture prompts →
done / abort, with quality nudges. Feeds the vision capture library.

## `ThermalGovernor` — servo-thermal Layer 2 (`thermal_governor.py`)

Turns `ThermalGuard`'s per-joint tier into a behaviour decision: AMBER →
throttle speed + soften gait + avoid-uphill hint; RED → hold a folded
cooldown pose for a minimum, with hysteresis on de-escalation.

## `chirps.py` — emotive buzzer vocabulary (B5)

`ChirpMood` (happy / confused / alert / sleepy / question / greeting) →
`b<tone> <ms> …` melodies via `opencat.beep`; `cue_chirp(stage)` for the voice
cue. `Chirper` rate-limits. Tone values are a first cut — tune by ear.
