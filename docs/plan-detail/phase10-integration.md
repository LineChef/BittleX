# Phase 10 — Full integration (detail)

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> Phase 10 and the integration runtime. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

## Phase 10 — Full integration

- [ ] All four systems running alongside each other without conflicts.
- [ ] Expect this phase to surface real timing/integration bugs even after each
      piece worked alone — budget real time.
- [ ] Update the README with final setup instructions and a demo.
- [ ] Ship a `requirements.txt` / dependency list for reproducibility.
- [ ] Optional: write up learnings in the repo.

### The integration runtime — built 2026-09-10

**`pi_pipeline/behavior/runtime.py` (`BehaviorRuntime`)** is the Phase 10 seam:
the loop that ticks `BehaviorDriver` at a fixed rate and feeds it its inputs
each tick from injected **sources** — a discrete-event queue (`post(**events)`,
drained per tick; the voice loop / a mic watcher / an IMU tap detector push
`wake_word` / `conversation_ended` / `told_sleep` / `say_hi` / `loud_sound` /
`imu_tap` / `meet_name` / … in), a `frame_source()` (wrap a `DetectionFeed`
with `latest_frame_source`), a `sensors()` dict (imu/held/person), a `recency()`
(`Memory.recency`) for mood, and a `roster()` (bonded labels). It dispatches the
resulting effects through the injected `DriverBindings` and exposes
`tick()` / `run_forever(max_ticks=…)` / `stop()` / `pause()` / `resume()`.
No threads, doesn't own the voice loop — the two run side by side, the voice
loop just `post()`s events. `python -m pi_pipeline.behavior` runs it against
`MockBindings` and prints the effect stream (idle → sit → rest → sleep →
wake-word → rouse). 11 tests.

**`pi_pipeline/app/` — the real I/O wiring, built 2026-09-10.** The one place
that ties everything together with hardware:
- `app/sinks.py` — serial + power backed `DriverBindings` sinks:
  `SerialActuatorSink` (raw safe-checked tokens — `k…`, `d`, `m0 …`, `b…`),
  `HeadSink` (head-pan `m0`), `WalkerSink` (firmware `wkF`/`wkL`/`wkR`,
  continuous), `PowerSink` (`pi_pipeline.power` profiles), `CameraSink`,
  `LockedLink` (mutex around the shared `SerialLink`); `build_bindings(link)`
  wires them.
- `app/sensors.py` — `SensorHub`: drains the serial IMU stream (`parse_imu_line`)
  → `imu_level` / `imu_stable` / `held`, reads the detection feed →
  `person_present`; `sample()` is the runtime's `sensors()` callable. Thresholds
  are FIRST-CUT / HARDWARE-GATED.
- `app/__main__.py` — `python -m pi_pipeline.app`: the `VoiceLoop` (main thread)
  + `BehaviorRuntime` (daemon thread) over one shared link; the voice loop's new
  `on_event` hook bridges `wake_word` / `conversation_ended` / `told_sleep` to
  `rt.post()`. **Mock by default** (null link, dry-run power — still exercises the
  real sink/sensor code); `--serial` on hardware, nothing else changes.
- `pi_pipeline/doctor.py` — `python -m pi_pipeline.doctor`: a bring-up readiness
  checklist (`.env` completeness, API key validity + expiry, Vosk/Piper/gait-ONNX
  files, Python deps, serial port, `--serial` board ping, audio devices, free
  disk); non-zero exit on any hard FAIL so it drops into a bring-up script.

**Deployment-easing batch — built 2026-09-10** (agreed earlier, executed now):
- **Black-box logging in `pi_pipeline.app`** — `diag.start_session("app", ...)` +
  `install_excepthook()` + `bridge_stdlib_logging()` at startup, `diag.close()`
  in the shutdown path — the first real hardware session is now recorded like
  any gait run, not silently unlogged. **Extended 2026-09-10 to every CLI
  entrypoint**, not just the integrated app — the actual first thing you run
  during bring-up (`check_serial`, `doctor`) is usually one of those, not
  `pi_pipeline.app`. Added `Diag.session(subsystem_hint, **kw)`
  (`pi_pipeline/diag/core.py`) — a context manager wrapping the same
  start/hook/bridge/close sequence, treating `SystemExit`/`KeyboardInterrupt`
  as a clean exit (not a FATAL crash) so `doctor`'s own `sys.exit(1)` on a
  failed check doesn't get misreported. Wired into `check_serial.py`,
  `doctor.py`, `voice/__main__.py`, and `gait/bench_real.py` (the last via the
  same optional-import + dual sys.path pattern `run_gait.py` uses, since it can
  run as a bare script). `pi_pipeline/tests/conftest.py` gained an autouse
  fixture pointing `G2_LOG_DIR` at a tmp dir, so the test suite no longer
  writes real session logs to the developer's `~/g2_logs`.
- **The voice actuator shares the real serial link** — `voice/actuator.py`
  `SerialActuator(port, baud, *, link=None)` accepts an existing link (the
  app's `LockedLink`) instead of always opening its own on the same port, and
  only closes a link it opened itself (`_owns_link`). `make_actuator(..., link=)`
  passes it through. `--bench` still forces the voice actuator to mock
  regardless of `--serial`, per its documented guarantee. Fixes a real gap:
  previously a conversational `perform_skill` never moved G2 even under
  `--serial`, because `_build_voice` hardcoded a mock actuator. (Also fixed in
  passing: `make_tts("mac")` was missing the now-required `piper_model_path`
  kwarg — `python -m pi_pipeline.app` would have crashed on its first TTS call.)
- **`doctor --serial` deeper handshake** — beyond the port existing, sends the
  firmware `?` query and reads the `P` battery-voltage reply (both passive,
  nothing moves) so "the board actually speaks OpenCat" is verified, not just
  "the port opened."
- **`pre-hardware` git tag** — a rollback point on `development` before
  bring-up churn starts.

**The three bigger deployment-easing items — built 2026-09-10:**
- **`pi_pipeline/bringup.py`** — `python -m pi_pipeline.bringup`: the (now
  17-step, after splitting step 12 into 12a/12b and adding 7c below;
  **renumbered again 2026-09-20 to a 20-step Phase 0/Phase 1 split matching
  the "When the hardware arrives" section below exactly** — see that
  section's own 2026-09-20 callout)
  "When the hardware arrives" sequence above, as a guided, resumable checklist
  instead of a doc to re-read and lose your place in. Progress persists to
  `<G2_STATE_DIR>/bringup_progress.json` (`--restart` clears it, `--from <id>`
  jumps to a step, `--list` prints everything non-interactively). At each step:
  `Enter`=done, `r`=run the suggested command (only offered for read-only /
  passive ones — port listing, `doctor`, a text-mode voice check, the
  benchmark), `s`=skip, `q`=quit-and-save. **Movement commands (`c`
  calibration, `kbalance`, `kwkF`, `--probe-imu`, `bench_real.py`) are always
  shown as text, never auto-run** — anything that moves a joint needs your
  hands free to catch it, not a confirm prompt inside this script.
- **`check_serial firstmove`** — a guided, confirmed first movement: one joint
  at a time (head, then the 8 leg servos by the confirmed Petoi map from
  `gait/deploy_map.py` — FL/FR/BR/BL shoulder then knee), each nudged by
  `--deg` (default 15°) with an explicit confirm before AND after, then (only
  if you keep saying yes) `kbalance`, then a single timed `wkF` burst
  (`--walk-s`) that **always ends at `d` (rest)** — including on `q` or
  Ctrl-C at any point, via a `finally`.
- **`pi_pipeline/link/trace.py`** — `TracingLink` wraps any link and appends
  every outbound command to a timestamped JSONL file
  (`{"t", "cmd", "reply"}`); `python -m pi_pipeline.app --trace <path>` wires
  it in transparently (both the voice actuator and the behaviour runtime's
  sinks log through the same file, since they share one link).
  `python -m pi_pipeline.link.trace replay <path> [--dry-run] [--speed N]
  [--serial]` re-sends the same commands with the same relative pacing — "it
  did something weird, what did we send it" becomes a file to read and a
  sequence you can reproduce, not a memory to trust.

**Full movement sweep — built 2026-09-10.** `check_serial`'s `skills` cycle
only ever exercised `voice/skills.py`'s 17-item conversational catalogue —
entirely missing `behavior/gestures.py`'s autonomous-behaviour gesture set (6
non-duplicate tokens after dedup), sleep (`kzz`), the carpet gait
(`kcarpetF`), and the recovery/get-up keyframes (`krc`/`krl`/`kdropRec`),
which nothing else exercises at all. New `check_serial allmoves`: `_all_moves()`
returns every distinct move across both catalogues plus those four, deduped by
serial token (28 total); `_allmoves()` cycles them, reading back battery
voltage and reply latency after each one against a logged idle baseline
(so a review afterward sees sag/slowdown, not just an absolute number) and
logging it all to the diag session — a data-gathering pass, not a pass/fail
check. The recovery keyframes get their own confirm first (they move the body
through its full range) and can be skipped (`--skip-recovery`). Always ends
at `d` (rest). Deliberately does **not** yet verify a recovery keyframe's
actual outcome (did the body end up upright) — that needs the IMU stream,
whose line format isn't confirmed until step 13a's `--probe-imu`, which comes
later in the sequence than this sweep does; worth revisiting as a v2 once
that format is known. Wired into the runbook as new step **7c** (renumbered
to **3c**/**8c** in the 2026-09-20 Phase 0/Phase 1 split), right after
the `skills` cycle, still on the stand.

**Real-time feedback pass — same day.** The original sweep printed a move's
name right before sending it and moved straight to the next one with nothing
between them — fine for the diag log, but easy to lose track of which move is
currently happening if you're watching the robot instead of the terminal.
`_announce()` now prints a numbered, ruled-off header per move
(`[7/28]  walk_forward  (skill)  ->  kwkF`) against the *effective* total
(excludes the 3 recovery keyframes when `--skip-recovery`), rings a terminal
bell, and pauses `--announce-s` (default 1.5s) before the move actually
fires — a beat to look up from the screen to the robot before, not after, it
moves. Both the bell and the lead pause are configurable
(`--no-bell`, `--announce-s 0`) for a faster unattended run once the sweep's
familiar.

**Deployment scope fixed — 2026-09-14.** `pi-bring-up.md` §7 and
`gait-deployment.md`'s automated path both used to say `git clone` the **whole**
repo onto the Pi. Fixed to deploy only what actually runs there:
- `pi-bring-up.md` §7 — `rsync`s just `pi_pipeline/` (the code) and
  `rl_training/opencat-gym/trained/run20m_ppo.onnx` (<1 MB, the one exported
  policy file) from the Mac, `--delete` on the directory sync so a local
  rename/delete doesn't linger stale on the Pi. A git-sparse-checkout
  alternative is noted for anyone who wants `git pull` instead.
- `gait-deployment.md`'s `pi_setup.sh` needed even less — it's fully
  self-contained (builds its own synthetic ONNX stub in-line just to
  benchmark inference speed) — so that's now `scp` of the one script file,
  fixed in both the doc and the script's own header comment.
- **`docs/` is never deployed at all**, by construction — the `rsync` source
  is `pi_pipeline/` specifically, not the repo root, so nothing outside that
  directory (`docs/`, `rl_training/`'s checkpoints/logs/GIFs, the RL
  toolchain) ever reaches the Pi. The only markdown that does ride along is
  `pi_pipeline/`'s own handful of small per-module `README.md` files (code
  documentation living next to the code it documents), not the `docs/` tree.
- **Why it matters, concretely:** `rl_training/` alone was ~4.7 GB the day
  this was caught (and only grows with every training run on `development`)
  — zero benefit to a Pi that never executes any of it, on a 32 GB card.

**B20 object-recognition gallery — decided + core built 2026-09-14.** Design
conversation settled the open question from the 2026-09-10 session: **option 2
(separate Pi-side layer) is decided, not just leaning** — a 6th model class is
off the table, precisely because a broad, visually-incoherent class sharing
the trained detector's weights risks diluting the 5 it already does well.
Then a follow-up conversation about storage (don't fill the Pi's limited
space with dupes/junk, cap it, know when an object has "enough" data) plus a
request to have G2 collect candidates *during* explore mode rather than
requiring a manual capture session, landed the mechanism itself, behind new
`features.object_gallery` (off by default, needs `vision` + `explore`):
- `vision/object_gallery.py` — `ObjectGallery`, pure decision logic (no I/O,
  no ML): dedup via cosine-similarity thresholds (same-instance vs.
  near-duplicate), a quality gate, a capacity cap with oldest-`last_seen`
  eviction that **never** touches a named or `locked` entry, and
  auto-`locked` ("enough data") at a configurable sample count or manually
  via the review tool. JSON persistence at `G2_OBJECT_GALLERY_DIR`
  (`~/.local/share/g2/object_gallery` default — outside the repo, same rule
  as `memory_db_path`).
- `behavior/object_seek.py` — `ObjectSeek`, the *when is it safe* gate: only
  proposes a scan when `Explorer`'s decision this tick was `HOLD` or
  `INVESTIGATE` (already stationary for its own reasons — this never asks G2
  to stop walking for a photo, and never interrupts locomotion), cooldown
  rate-limited, skipped once the gallery signals no capacity. Composed into
  `BehaviorDriver._from_explore()` as a same-tick `CAPTURE` on/off pulse
  (reusing the effect enrollment already uses) + a `DIAG` event. Priority
  over every other system is structural, not re-checked: `_from_explore()`
  is only reached after emergency stop / sleep / enrollment /
  choreography-safety / "come here" / conversation have already had first
  claim on the tick, per the driver's existing order.
- `tools/label_objects.py` — the review/labeling interface, entirely local
  (`generate` writes a local `review.html` with a field for every piece of
  data that matters — name, note, a complete flag, discard — and a
  client-side-only "download labels.json" button, no server; `apply` writes
  it back into the gallery and deletes discarded crop files). Nothing
  published or uploaded, matching the `training_data/` privacy rule.
- **Still hardware-gated, deliberately not built:** the localizer (what
  decides "something's here" — motion/frame-diff or a generic saliency
  model) and the embedding model (what fingerprints a crop). Both need the
  real camera to tune/choose, but **both are also independently testable
  NOW, pre-hardware** — the Grove Vision AI V2 and the Pi Zero 2 W are both
  already bench-bring-up-done (Phase 6 / Phase 8), just not mounted on the
  body — worth doing before wiring a model in, not after.
- 22 new tests (`test_object_gallery.py`, `test_object_seek.py`, 4 in
  `test_driver.py`) — all tests passing total.

**Emergency stop — built 2026-09-10** (`behavior/emergency.py`, `EmergencyStop`).
A latching manual freeze that outranks *everything* in `BehaviorDriver.tick()`
(checked at step 0, above enrollment / sleep / safety / mode): on `halt` it emits
stop + an ALERT chirp + one hold command (`kbalance` default, `estop_freeze_token`
configurable to `ksit` / `d`), then re-asserts stop every tick until `release`.
`BehaviorRuntime.halt()` / `.release()` dispatch it immediately even while
`pause`d. Triggers: the voice phrases "emergency stop" / "freeze" / "halt" /
"stop moving" / "abort" (`commands.match_local_command` → `"halt"`, checked
first, no Claude call), `python -m pi_pipeline.app --halt`, or `kill -USR1 <pid>`
(the app writes a pidfile); cleared by "resume" / "as you were" / `--release` /
`SIGUSR2`. This is the human backstop for the not-yet-trained `CliffGuard`.

**Bench mode** — `python -m pi_pipeline.app --bench`: for when G2 is on the
calibration stand. Suppresses the behaviour runtime entirely and forces the
voice actuator to mock, with a `=== BENCH MODE ===` banner, so `check_serial` /
`run_gait --probe-imu` / firmware `c` calibration own the serial link with
nothing autonomous competing.

**Explore mode — two-tier redesign, built 2026-09-10** (user design session).
The single time-based `EXPLORE` mode is split:
- **Tier 0 "attentive"** (`behavior/attentive.py`, `AttentiveLook`) — stationary,
  *always active* as a life-signs layer the driver runs in the IDLE branch while
  a posture holds steady: gaze-follow the nearest person (`HEAD` bearing),
  react to a novel object (look → `kbuttUp` peer bow → QUESTION chirp), a
  periodic head pan-scan (`scan_every_s`), and greets known people via the
  existing recognition hop. Never emits `WALK`/`TURN`. `vision_available=False`
  → periodic scan only. G2 still settles (sit → rest → sleep) underneath.
- **Tier 1 "roam"** — `Mode.EXPLORE` is now **voice-armed only**:
  `ModeController.arm_explore()` / `disarm_explore()`, entered solely when armed
  (+ the post-conversation `settle_secs` grace); **no time-based entry**. Ends on
  any activity, `explore_max_secs`, the new `Explorer` leg budget
  (`ExploreConfig.max_legs`, a no-odometry distance proxy → driver disarms), or
  "that's enough" — and disarms on every exit, so each bout needs re-arming.
  `DriverInputs.arm_explore` / `disarm_explore`; voice phrases "go ahead and
  look around" / "exploration mode" → `commands` `"explore"`, "that's enough" /
  "come back" → `"unexplore"`. Still gated by `features.vision`; the desk-edge
  classifier (B16) upgrades it for near-edge use. Operating contract: G2 is
  always supervised, and the operator only arms Tier 1 when G2 is on the floor.

**Explore polish, built 2026-09-10** (follow-up pass):
- **Tier 0 sound reaction** — `AttentiveLook.decide()` takes `sound` / `loud` /
  `sound_bearing`; turns the head toward a sound (or a quick scan if the bearing
  is unknown). A loud sound interrupts a gaze-follow. No camera needed.
- **Gaze-follow satiation** — after `follow_satiate_s` of continuous follow it
  drops to `follow_glance_cooldown_s` glances so it doesn't stare; a big bearing
  change or the person leaving view re-engages.
- **"Come here"** — `behavior/approach.py` (`ApproachTarget`), voice command
  `"come"` ("come here" / "come to me" — *not* "come back", which is
  `"unexplore"`). `DriverInputs.come_here` → `Mode.APPROACH`: a one-shot directed
  walk toward the largest person detection, `STOP` + happy chirp on arrival
  (`close_area`), `STOP` + confused chirp on give-up (`give_up_s`). Preempts
  IDLE / EXPLORE / CONVERSE; enrollment / choreography / safety / sleep still
  win. Cancelled by `told_stop` / pickup / wake word; needs `_vision`.
- **Audible roam state** — the driver emits a `GREETING` chirp on entering
  EXPLORE and a `QUESTION` chirp every `ExploreConfig.roam_chirp_s` while
  roaming, so autonomous movement is never a surprise.
- **Place memory (B11 start)** — `behavior/place_memory.py` (`PlaceMemory`):
  `observe(label, bearing)` on each Tier-1 investigate/approach; once a label
  repeats in the same 4-way direction `min_sightings` times it emits a durable
  sentence ("The dog is often to the left…"), surfaced as
  `DriverTick.place_notes` and forwarded by `BehaviorRuntime` `on_observation`
  → `Memory.store.add_fact` (the app wires this when memory is enabled). No
  timestamps — the memory store rejects temporal detail anyway.

**Graceful shutdown, built 2026-09-10** — voice "shut down" / "shutdown" /
"power down" / "go dormant" (`commands` → `"shutdown"`) → `DriverInputs.shutdown`
→ `SleepMode.on_command_shutdown()`: G2 emits `d` (lie flat), holds
`shutdown_settle_s` (~2 s, `SleepAction.LIE_DOWN`), then transitions to DOZING /
`ENTER_SLEEP` with `SleepMode.shutting_down` set so the driver skips the `kzz`
curl and just does POWER headless + camera off + a sleepy chirp. Any activity /
wake word cancels a pending shutdown or rouses from it. Not an OS power-off;
"go to sleep" stays the lighter curl variant.

**Left for hardware:** plumb a real `SerialDetectionFeed` into `SensorHub` +
`BehaviorRuntime.frame_source`; tune the `SensorConfig` IMU thresholds against
`--probe-imu`; confirm the head-pan joint index + range; the `WalkerSink` is
firmware-gait only (the RL gait is `gait/run_gait.py`, run separately).

### Ready logic, not yet wired to a runtime

Built + unit-tested pure-logic modules. "Wire" = feed them their inputs each
tick and act on their outputs in an actual control/behaviour loop.

**The behaviour driver loop is built** (`pi_pipeline/behavior/driver.py`,
2026-09-08). `BehaviorDriver.tick(DriverInputs) -> DriverTick` composes
`ModeController` + `Explorer`/`Novelty` + `IdlePosture` + `GesturePicker` +
`Enrollment` + optional `CliffGuard` and returns an ordered list of abstract
`Effect`s (SKILL / STOP / WALK / TURN / HEAD / SPEAK / CAPTURE / CUE / DIAG).
It runs today against mock feeds + a fake clock (11 tests). The **binding layer**
is built (`pi_pipeline/behavior/bindings.py`, 2026-09-10) — `DriverBindings`
routes every `Effect` kind to an optional sink (actuator / tts / camera / cue /
walker / head / diag), missing sinks drop-and-warn; `MockBindings` records every
call so the whole loop is exercised end-to-end (idle descent → `ksit` → `d`,
wake choreography → head/skill) in 7 tests. Still needs, on hardware: the real
sink implementations (some exist — `voice/actuator.py`, `voice/cues.py`,
`voice/tts.py`) and the input plumbing (vision frame, IMU state, mic events).
**Behavior-audit finding, 2026-09-16 — Enrollment specifically:** `app/sinks.py`'s
`build_bindings()` hardcodes `tts=None, cue=None` (comment: "the voice loop
owns TTS; SPEAK effects are rare here") — true for most of the driver, but
**`Enrollment`'s entire interaction is SPEAK effects** ("What's your name?",
capture progress, completion/abort). No bridge exists from `BehaviorDriver`'s
effect stream into the voice loop's real `TTS`/`Cue` objects (`voice/loop.py`
and `behavior/runtime.py` never cross-reference each other's I/O). Right now
"G2, meet Sam" runs the full enrollment flow with no audible feedback at all.
Needs a real design decision — give `BehaviorRuntime` a reference to the voice
loop's live `TTS`/`Cue`, or special-case enrollment's SPEAK effects to route
through the voice loop directly — not a quick wire-up.
The `DIAG` effects are the hook for Diagnostics Phase 1. Gestures, idle-posture descent + WAKE/settle/PEEK choreography,
personality→idle-timing knobs, sniff-on-investigate, greeting-on-enrollment and
excited-hop-on-recognition are all wired *inside* the driver now — see
`docs/behavior-ideas.md` for the per-item status (a few sub-items, e.g. the
breathing-bob motion and LED life-signs, are still caller-side).

- [~] **CARPET MODE — decision logic + runtime wiring done (2026-09-10);
      hardware-gated on the accel source + threshold tuning.**
      `pi_pipeline/gait/carpet.py` (`CarpetDetector`, tested): commanded vs.
      measured forward speed → `NORMAL` / `BOOST_CMD` (raise the speed command
      to punch through pile) / `CARPET_GAIT` (hand off to firmware `kcarpetF`).
  - **Forward-speed estimate — BUILT:** `pi_pipeline/gait/speed_estimate.py`
    `ZuptSpeedEstimator` — integrates body-X accel with a per-gait-cycle ZUPT
    bias correction + a leak (steady walking ⇒ ∫accel over a cycle ≈ 0). Pure
    logic, 6 tests. **Accel not plumbed yet:** `parse_imu_line` returns
    ypr+gyro only; body-X accel needs the `--imu-format 6axis` stream. Passing
    `accel_fwd=None` makes it inert, so `--carpet` is safe to leave off.
  - **Runtime wiring — DONE:** `run_gait.py --carpet` (default off) runs the
    estimator + detector each tick; `BOOST_CMD` → `pol.set_command(cmd_with_boost)`,
    `CARPET_GAIT` → send `opencat.CARPET_WALK` and skip the policy send, re-anchor
    the policy (`STAND` + `pol.reset`) on return to `NORMAL`. `carpet.mode` diag
    events on transitions.
  - **Still hardware-gated:** plumb body-X accel through `parse_imu_line`; tune
    `boost_below` / `carpet_below` / `enter_s` / `boost` on real carpet; tune
    `ZuptSpeedEstimator`'s `leak_hz` / `bias_lerp`.
  - **Optional, better:** retrain the walk with `CARPET` domain-randomisation so
    the RL policy itself handles pile (backlog H10 covers the carpet sysid);
    then `CARPET_GAIT` hand-off is only for deep pile.
- [x] **Personality gestures** — `GesturePicker` is now driven by
      `BehaviorDriver`: idle fidgets while sitting & settled, `greeting()` on
      `Enrollment` GREETING, `sniff_find()` on `ExploreAction.INVESTIGATE`,
      `excited_hop()` on a bonded label seen after an absence (driver takes the
      roster as `DriverInputs.known_person_labels`; `bonds` stays un-imported).
      A **"say hi" voice intent hook** is wired 2026-09-10 —
      `DriverInputs.say_hi` → a `greeting()` gesture skill (suppressed during
      enrollment / a non-wake choreography).
- [x] **Idle-posture descent** — driven by `BehaviorDriver`; `kstr` is wired
      into the WAKE choreography. **Sleep mode** (`opencat.SLEEP` / `kzz`
      deep-sleep below RESTING) — FSM built 2026-09-10, **wired into
      `BehaviorDriver` 2026-09-10**: a sleep gate above enrollment / mode
      auto-sleeps after long RESTING (or on `DriverInputs.told_sleep`, which
      overrides person-present), and while DOZING / ASLEEP owns the robot. It
      emits `SKILL kzz` + `POWER headless` + `CAPTURE off` + a `CHIRP` on sleep;
      on a wake signal (wake word / tap / lift / loud sound / spoken-to) it
      emits `POWER interactive` + `CAPTURE on` and hands back to IdlePosture's
      rouse choreography. New effect kinds: `CHIRP` (payload `ChirpMood`) and
      `POWER` (`"headless"` | `"interactive"`), routed by `DriverBindings`.
- [x] **Emotive chirps (B5) + mood (B6) wired 2026-09-10.** The driver emits a
      rate-limited `CHIRP` on recognition (HAPPY), a startle (ALERT), "say hi"
      (GREETING), an edge reflex (ALERT), and sleep entry (SLEEPY). The
      `MoodModel` runs in the driver (scales the idle-descent timing:
      LONELY settles sooner + `DriverTick.seek_attention`, SUBDUED holds
      longer) and in the voice loop (`Memory.recency()` → `last_interaction_s` +
      session exchange count each turn → `Conversation.set_mood_hint()` folds a
      one-line note into the system prompt; a "leave me alone"-style phrase
      (`commands.looks_like_rebuff`) nudges it to SUBDUED). Recency is
      in-process only — `exchanges.ts` is a date, not a clock time, by privacy
      design.
- [ ] **INSPECT peer bow** — done + sim-validated (`buttUp_ref`, +22° nose-down);
      the earlier "author on hardware" caveat is resolved. Confirm on the real
      robot that the mounted camera's downward view actually improves the near
      obstacle read (the A/B is: swept/bow profile vs. plain forward scan into
      the selector).

---
