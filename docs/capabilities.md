# What G2 can do

A running inventory of everything we have taught **G2** (a Petoi Bittle X
quadruped with a Raspberry Pi companion in the add-on pod and the Petoi AI Head on the neck) to do. Last brought up to date 2026-10-21.

For *how* the pieces work, see [`how-it-works.md`](how-it-works.md). For the
roadmap and decision log, see [`project-plan.md`](project-plan.md). This file is
the *what*, kept current as capabilities land.

**Status key**

| | meaning |
|---|---|
| ✅ | **Working now** — runs today, on a dev machine, on the camera, or in sim |
| 🧩 | **Built, hardware-gated** — code complete and tested against mocks; needs the physical robot or camera to exercise and tune |
| 🔬 | **Researched / parked** — investigated, outcome recorded, not currently active |

The 🧩 items are the ones not yet exercised on the robot; much has been since the first walk
(voice, memory, exploration, the wall avoider and the learned gait all run on G2). What has actually
been exercised, what is deployed, and what is broken right now is in [`STATUS.md`](STATUS.md) — this
file does not repeat it. Things not built yet (the robot-arm module, which has not been fitted, place memory beyond its log, reflection beyond its log-only mode, a gait that walks on carpet, a high-step gait) are in [`planned/`](planned/README.md), not here. Run
`pytest` for the current test results (no counts are quoted in the docs).

---

## At a glance

| Domain | Headline | Status |
|---|---|---|
| Locomotion — learned | An RL walk that tracks speed/heading commands, trained under G2's real control path (5 Hz IMU, firmware `i` command timing); which policy is deployed and how it does on the robot: [`STATUS.md`](STATUS.md) | ✅ sim / 🧩 robot |
| Locomotion — scripted | ~20 OpenCat keyframe skills wired with friendly names (walk, turn, back up, trot, crawl, carpet gait, get-up, sit, stretch, nod, play-bow); the one-foot and jumping moves (wave, scratch, shake paw, high five, hop) are refused because they tip G2 over on the pod payload | ✅ / 🧩 |
| Carpet mode | "G2, carpet mode" plays Petoi's firmware carpet gait (`kcarpetF`) instead of the learned walk; no gait yet walks reliably on the real carpet ([`rl/carpet-findings-2026-10-20.md`](rl/carpet-findings-2026-10-20.md)) | 🧩 |
| Attachments | One setting (`g2attach head\|arm\|none`) says what G2 wears on the neck; it picks the gait saved for it, checks the firmware and adds the arm's skills. G2 wears the Petoi AI Head | ✅ head / 🧩 arm |
| Real-data pipeline | Every real walk is logged with its floor and hardware epoch; the Mac gates the logs and fits numbered sim-calibration snapshots from the usable ones | ✅ |
| Sim → real | Policies export to ONNX with a sidecar carrying their residual scale, bit-for-bit validated against the on-robot control loop; the loop polls the 5 Hz IMU and sends the simultaneous `i` joint command; Pi inference 0.43 ms/call | ✅ built / 🧩 deploy |
| Autonomous behaviour | A `BehaviorDriver` that composes explore / idle / converse modes into abstract effects, plus novelty-seeking, gestures, enrollment choreography; exploration narrates what he sees and does and takes four scheduled survey pictures per roam | 🧩 |
| Smooth transitions | Every move into a firmware skill is eased by the serial link (speed-capped, 40 steps a second, balance off); moves that tip G2 over on the pod payload are refused with the wrong-answer sound ([`hardware/disabled-moves.md`](hardware/disabled-moves.md)) | ✅ |
| Personality | Composable traits (curiosity, playfulness, "Gir" character mode), mood model, per-person bonds — all `.env`-driven | ✅ |
| Voice | Wake-word → local STT → Claude conversation → local TTS, with `perform_skill` / `remember` / `diagnostics_query` tool-calls, live chirps/narration-verbosity toggles, and graceful degradation when the API is down. Mic → wake word → Claude → a real walk verified on G2 2026-10-03 | ✅ on G2 (mic, speaker, Claude, real walk) |
| Memory | Persistent fact store with recall, a CLI, and a localhost web UI | ✅ |
| Vision | Custom 3-class detector (household member + dog + cat) running **on the camera**; obstacle-avoidance reflex + "what do you see" narration wired to the feed | ✅ model / 🧩 mounted camera |
| Safety reflexes | Emergency stop, disabled-move refusal, servo thermal guard, watchdog, sleep mode, carpet detector, fall and stall guards (running); jam reflex and thermal governor (built, not wired in); cliff/edge guard (gated on a classifier) | ✅ / 🧩 |
| Diagnostics | Black-box structured logger with manifest + crash hook, SoC/throttle/battery sampler, gait watchdog that halts on stall, queryable by voice (`diagnostics_query`: session summary / last failure / feature status) | ✅ logic / 🧩 HW sensors |
| Power | Idle-REST staged descent + sleep mode (real power-profile switch, camera off) fully built and tested; on-demand vision is still just binary on/off, not scaled to activity | ✅ logic / 🧩 tuning |
| Robot link | One shared serial link with auto-reconnect, command builders, a dangerous-command denylist, and a bring-up self-test | ✅ |

---

## Locomotion

### Learned gait (RL) — ✅ in sim and on G2 (hardwood)
- **The deployed policy** (see [`STATUS.md`](STATUS.md)) is trained under a model of
  G2's real control path: the stock firmware's 5 Hz IMU with no rate signal, the
  `i` joint command's execution timing, realistic body mass, and small IMU /
  servo calibration errors. Lineage and results: [`rl/hw1-log.md`](rl/hw1-log.md).
- **`run20m_ppo`** — the original frozen base the later policies were compared against. 20 M PPO steps from scratch in
  PyBullet; a learned *residual* on Bittle's scripted `wkF` trot, IMU-corrected
  every control step.
  - Tracks forward-speed commands to **0.007 m/s** and heading commands.
  - Climbs a **24° slope** (the benchmark labelled it a descent until 2026-09-23; its up/down labels were inverted).
  - **0 % falls** on the payload-on (Pi + camera mass) 27-cell decathlon.
  - Conditioned on the mounted-payload configuration, so the sim gait already
    "knows" it is carrying the companion stack.
  - `rl_training/opencat-gym/` — training, eval, and `watch_trained.py` replay.
- **On G2:** a series of policies has walked on hardwood without falls, the latest trained on the pod and AI Head payload; which one is deployed and how it did: [`STATUS.md`](STATUS.md), [`rl/real-walk-log.md`](rl/real-walk-log.md). Layers around it on the real robot: a per-policy front-left foot trim for steering (`gait/heading_hold.py`, with per-floor trims through `g2attach floor-trim`), an eased 0.8 s stand-up (`gait/standup.py`), a walk-start settle that never starts while tilted past 30° (`gait/walk_start.py`), gait switching by voice ("hi step", "carpet mode", "walk normally"), and the guards in "Safety reflexes" below. Tile drift is unresolved and carpet is open.
- **Continuous balance** — the policy re-decides every control tick from body
  tilt + recent joint history + a rhythm clock, so it corrects small shoves and
  low obstacles by construction.

### Scripted skills — 🧩
Friendly-named wrappers over OpenCat keyframe tokens
(`pi_pipeline/link/opencat.py`), so the rest of the stack never hard-codes raw
serial:
- **Move:** stand, rest/relax, walk L/R (curved / pivot), walk backward, jump.
- **Carpet gait** — Petoi's firmware `kcarpetF` (higher foot clearance). "G2, carpet mode" (or answering "carpet" to
  the floor question) makes every walk play it, with no learned policy; naming another floor or "walk normally" switches back.
  The carpet detector can switch to it on sustained slip. It fell to the right on the real carpet in its first test with the pod on.
- **Get-up / recovery:** `rc` self-right, `rl` roll-from-supine, `dropRec`
  last-ditch flail, `balance` settle. G2 flips himself back over from fully on
  his back using the firmware's own `rc` (confirmed 2026-09-28); the sim cannot
  reproduce it ([`hardware/self-righting.md`](hardware/self-righting.md)).
- **Expressive / social:** stretch, sit, sleep-curl, play-bow, nod, shake head, check-around head scan, push-ups, trot, crawl.
  **Disabled on the pod payload (2026-10-18):** wave, scratch, shake paw, high five and hop. They leave G2 on three feet or jump, and
  the wave flipped him twice. `SerialLink.send` refuses them for every caller and plays the wrong-answer horn; the voice skills `wave`
  and `scratch` stay in Claude's list, marked disabled. Audit and the borderline kept moves (stretch, push-ups):
  [`hardware/disabled-moves.md`](hardware/disabled-moves.md).

### Vision-chosen skills and teaching — 🧩

- **Vision skill layer** (`gait/skill_layer.py`, `skill_switch.py`, `walk_vision.py`, Phase E) — vision picks a scripted OpenCat keyframe skill on top of the frozen walk
  (no training involved) with a smooth hand-off so the switch does not lurch; the terrain-to-`GaitMode` decision is `vision/gait_selector.py`. Not yet run on G2 while walking.
- **Teach tool** (`gait/teach.py`) — show G2 a leg movement: relax the servos, move a leg by hand, read the eight angles back from the servo feedback and save them as a
  pose, one step at a time. Not yet run on G2.
- **Get-up test** (`gait/getup_test.py`) — tries one firmware get-up move from a fall on his side, logs the IMU and reports whether he came upright; one attempt per run. Paused: it failed from a side lie.

### RL training pipeline — ✅ (sim)

`rl_training/opencat-gym/` trains the walk in PyBullet with Stable-Baselines3: a learned residual on `wkF`, a frontier curriculum of hazards (slopes, ledges, rough ground, pushes)
capped by a passability audit, unattended staged chains with a plan doc and a watchdog each, a decathlon and load-ladder benchmark, a sim carpet model, a real-to-sim replay and a
calibration fit from real walk logs. `tools/eta.py` gives timing estimates from past runs. Plans and results: `docs/rl/` and `docs/plan-detail/`.

### Sim → real deployment — ✅ built and in use on G2
- ONNX export of `run20m_ppo`, **bit-for-bit validated**: 0 joint-degree cells
  differ between `model.predict` and the on-robot control loop.
- Pi bring-up completed when the Pi arrived: policy inference **0.43 ms/call** on the first benchmark, no thermal throttle (provisioning is now `pi_pipeline/setup_pi.sh`).
- `docs/guides/gait-deployment.md` — the full sim→real path.

### Ruled out — 🔬
- **Vision inside the gait policy** — four training campaigns (Phases A–F). A
  policy that can see forward learned to plow through obstacles, not brace. Now a
  reflex layer *above* the frozen walk instead. `docs/archive/rl/vision-in-gait.md`.
- **Learned big-stumble recovery** — can't be reward-tuned; ~18–25 %
  conditional-survival ceiling. `docs/archive/rl/phase4-decision-log.md`.
- **Learned turn-in-place** — sim-physics limit; turning routed to firmware gaits.
- **A learned carpet gait** — one day of sim work (a soft-pad model, an adaptive carpet level, clearance and grip changes) found no gait that walks on the
  real carpet; carpet mode plays the firmware gait instead. [`rl/carpet-findings-2026-10-20.md`](rl/carpet-findings-2026-10-20.md).
- **A heavy-load retrain** — a policy trained for up to 1 lb of extra weight was not better than the deployed one, and a fine-tune of it was tried as a one-time exception;
  neither was promoted. [`planned/heavy-load-training-plan.md`](planned/heavy-load-training-plan.md).
- **A high-step creep gait** — the staged training chain ended without a policy that clears steps.
  [`archive/plan-detail/high-step-creep-training-plan.md`](archive/plan-detail/high-step-creep-training-plan.md).

---

## Autonomous behaviour

`pi_pipeline/behavior/` — a `BehaviorDriver` that turns sensor + mode state into
abstract **effects** (`SKILL / STOP / WALK / TURN / HEAD / SPEAK / CAPTURE / CUE /
CHIRP / POWER / DIAG`), which `DriverBindings` routes to whatever sinks are
injected. `BehaviorRuntime` (`runtime.py`) is the loop that ticks the driver at
a fixed rate, feeds it inputs from injected sources (event queue, detection
feed, sensors, mood recency, bonded roster), and dispatches the effects.
**`pi_pipeline/app/`** is the real-I/O wiring: serial + power backed sinks
(`app/sinks.py`), a `SensorHub` that turns the IMU stream + detection feed into
the driver's continuous inputs (`app/sensors.py`), and `python -m pi_pipeline.app`
— the voice loop and the behaviour runtime running side by side over one shared
link, **mock by default, `--serial` on the robot**. Exploration sessions (voice hand-over, `g2explore`) run the behavior runtime on G2; the full `app --serial` over a long run is still to do. Since 2026-10-18 an exploration can also run inside the voice service (`G2_EXPLORE_INPROCESS=1`, off by default and not yet tried on G2): one process, the same link, walker, memory, speech engine and microphone, no stop and restart of `g2-voice`.

- **Modes** — `converse` / `idle` / `explore`, with a controller that switches
  between them.
- **Explore, two tiers:**
  - **Tier 0 "attentive"** (`behavior/attentive.py`) — *stationary*, always
    active as a life-signs layer on IDLE: turns toward a sound ("what was
    that?"), gaze-follows a person with head/body then **satiates** (drops to
    occasional glances so it doesn't stare), reacts to something new in view
    (look → peer bow → curious chirp), does a periodic head pan-scan, greets
    known people. **No walking, ever** — safe on desk or floor.
  - **Tier 1 "roam"** — walking exploration (wander stalest heading, investigate
    novelty). **Voice-armed only** ("G2, go ahead and look around" / "exploration
    mode"); no time-based entry. Emits an audible "I'm roaming" chirp on entry
    and periodically, so movement is never a surprise. Ends on any activity, a
    bout cap, a leg-budget leash, or "that's enough" — and disarms, so each bout
    needs re-arming. Gated by `features.vision`; the desk-edge classifier (B16)
    upgrades it for near-edge use.
  - **Exploration, as of 2026-10-09** (user decisions): the start is a rising "ba nun na NAAA" fanfare (buzzer arpeggio, brass-like on the speaker); each leg is 8 s (since 2026-10-10) and ends
    in the standing pose, never lying down (rest only at the end of the session or on a fall); picture stops are at most one a minute and only when something is worth a picture
    (`behavior/interest_watch.py`: an unknown object-like thing or an unfinished named object, never a person; a slow fallback every 5 min), and the camera prep (the settle frames)
    is done for the first picture and once half way; no head gestures and no recognition hop (`G2_HEAD=1`, `G2_EXCITED_HOP=1` bring them back), a short play bow at a find instead;
    the wall estimator (`vision/wall_distance.py`) is wired in since 2026-10-10: a near wall makes G2 turn away with a sound, and an IMU contact signal starts the hit sequence (oof, back up, turn around); see [`guides/exploration-mode.md`](guides/exploration-mode.md).
    Gait switching: "hi step" / "walk normally" from any mode (voice loop or exploration), a double beep on a switch; today hi step is the scripted hsF gait (experimental), because the deployed policy has no hi-step mode.
    Since 2026-10-18: four scheduled survey pictures per capped roam, narration of walls, bumps and new directions, the floor question before every roam (by voice and in
    `g2explore start`), and a pass/CHECK report written at the end of each roam (`g2explore report`). A roam can also run inside the voice service
    (`G2_EXPLORE_INPROCESS=1`, off by default). Guide: [`guides/exploration-mode.md`](guides/exploration-mode.md).
    Stop a running session with `tools/g2_safe_stop.sh` (stop, balance, rest), never a plain service stop.
  - **"Come here"** (`behavior/approach.py`) — a directed one-shot walk toward
    the nearest person; stops close, or gives up (with a confused chirp) if it
    loses sight. Voice command, `Mode.APPROACH`.
  - **Place memory** (`behavior/place_memory.py`, B11) — while roaming, G2
    accumulates *stable* spatial patterns ("the dog is often to the left") — no
    timestamps — and writes them as durable facts once a direction repeats.
- **Idle-posture staged descent** — what pose G2 holds with nothing to do:
  peek → sit → rest → sleep, backing off gradually rather than freezing.
- **Graceful shutdown** — "shut down" / "go dormant" → G2 lies flat (`d`) first,
  holds ~2 s, then goes dormant (power-save + camera off, stays flat). Distinct
  from the emergency freeze and from "go to sleep" (which curls).
- **Deep-idle sleep** — below RESTING: after a long quiet stretch (or on
  command) the driver curls up (`kzz`), drops the Pi to the power-save profile,
  and turns the camera off, then wakes on the wake word / a tap / a loud sound /
  being spoken to — emitting the rouse choreography and restoring full power.
- **Mood-scaled idle timing** — the slow mood (below) shortens the descent
  delays when LONELY (settle sooner, seek attention) and lengthens them when
  SUBDUED.
- **Gestures** — the behaviour layer decides *when* to fire expressive skills
  (bow, wave, nod…) from context.
- **Person enrollment choreography** — speak / orient / capture-on / capture-off
  steps to walk a new face through a capture session.
- **Emotive chirps** — the driver emits a `beep`-melody mood (happy / alert /
  sleepy / greeting …) on recognition, a startle, a greeting, an edge reflex,
  or sleep entry, rate-limited to at most one per tick.

---

## Personality

`pi_pipeline/personality/` — composable, all `.env`-driven, all ✅.

- **Traits** (`G2_TRAITS`, levels 0–1) — each contributes a prompt fragment,
  behaviour-param biases, and event cues:
  - **curiosity** — investigate longer, approach novelty.
  - **playfulness** — more vocal / fidgety / wandering; deliberately pulls
    *against* curiosity's patience.
  - **"Gir" character mode** (`gir`) — an opt-in manner overlay, default level
    0.4, **off unless you turn it on** (env or by asking G2 "enable Gir mode").
    Task-guarded at every level so it never derails a real instruction.
- **Mood model** — NEUTRAL / CONTENT / PLAYFUL / LONELY / SUBDUED from recent
  interaction history; notices being rebuffed. Wired: the voice loop feeds it
  interaction recency each turn and folds its one-line hint into the system
  prompt; the behaviour driver applies its idle-timing bias.
- **Body state** (`personality/body.py`, 2026-10-18; 🧩 not yet tried on G2) — a low-battery alert, a recent fall and how the
  last exploration went add one sentence to each turn's mood hint and make idle settling come sooner (low battery, after a fall).
  Every note expires by itself; servo heat is not an input.
- **Bonds** (`G2_BONDS`) — per-person familiarity + disposition
  (affectionate / playful / fearful …) that colours how G2 greets and reacts.
  Personal identifiers live only in the gitignored `.env`.
- **Runtime character state** — turning a character on by voice persists across
  restarts (`character.json`), outranking the env default.

---

## Voice

`pi_pipeline/voice/` — ✅ end-to-end against mocked audio and the **live Claude
API** (`livecheck.py`), and on G2's real mic + speaker since 2026-10-04.

- **Full loop** — wake word → Vosk local speech-to-text → Claude conversation
  turn → Piper local text-to-speech, with follow-up windows and silence timeouts.
- **Tool-calls Claude can make mid-turn:**
  - `perform_skill` — G2 acts out a skill while it talks.
  - `remember` — commit a fact to persistent memory.
  - `await_reply` — keep the microphone open for the answer to a question.
  - `diagnostics_query` — ask G2's own diagnostics what happened.
- **Local commands** (no API) — emergency stop / resume, shut down, go to sleep, come here,
  explore arm / disarm, "walk for N seconds", gait switching ("hi step", "walk normally"), the floor ("the floor is tile"),
  narration level, forget, character on/off, "carpet mode" / "walk normally", "dismissed" (after a false wake: closes the window silently and logs the trigger as false),
  and conversation mode ("let's talk" until "that's all") — parsed
  on-device, checked before Claude (emergency stop wins over everything).
  Full phrase list + the conversational skill catalogue:
  [`docs/guides/voice-commands.md`](guides/voice-commands.md).
- **Questions answered locally** (no API): battery (in percent), "what floor", "what did you do" (the last exploration's recap), "what have you learned"; and "switch to English"
  resets the BiBoard voice module's language.
- **Command acknowledgement** — *every* recognised voice command (and every
  conversational turn) fires an instant "heard you" chirp + a `heard` cue before
  the slower spoken reply, and G2 never moves silently (a bare skill still gets
  a spoken "Okay"). Makes a misheard command obvious so you can cancel it.
- **Memory seam** — every turn pulls memory context before the API call and
  writes back after.
- **Real mic + speaker** — ✅ the I2S mic and amp are wired and in daily use on the Pi; wake word, Vosk, Claude and Piper run
  end to end. Wiring: [`blueprints/wiring/g2-wiring-guide.html`](../blueprints/wiring/g2-wiring-guide.html); bring-up: [`hardware/i2s-audio-build-log.md`](hardware/build-logs/i2s-audio-build-log.md).
- **Never silent** — a turn that would end with no spoken words (a tool call only, or an empty reply) is retried once with
  tools disabled to force a sentence, then falls back to a short spoken line; API errors in conversation history are
  self-healed (orphaned tool calls, thinking blocks). Fuzz-tested.
- **Shut down also powers the Pi off** — "shut down", "power down", "power off", "shut off", "turn off" (the last two only as the
  bare phrase) lie G2 down, announce a short countdown ("say cancel to stop me"), then run `sudo shutdown -h now` so the memory
  database and logs close cleanly. Only a short, non-question command powers the Pi off; anything longer just lies G2 down. The
  PiSugar S keeps powering the halted Pi, so G2's goodbye asks for the battery switch to be flipped by hand. The BiBoard has no
  software power-off.
- **Wake log** — every wake trigger and what followed it is logged (`python -m pi_pipeline.voice.wake_log`); `G2_WAKE_MIN_CONF` can ignore
  low-confidence triggers once the log shows where real and false ones split.
- **Speech-recognition hardening** — a second Vosk recognizer limited to the stop / shut-down phrases hears the same audio and
  overrides a short misheard transcript (never a long sentence); a mis-transcribed wake word run into a command ("gee to shut
  down", "she to power down") is stripped before matching. `G2_LOG_HEARD=1` logs every transcript; `G2_STT_COMMAND_GRAMMAR=0`
  turns the grammar recognizer off.
- **Sounds** — a wake chime, a cue when your words are captured, closing notes when the follow-up window ends, a double click for every picture, an API
  tone on each billed call, battery alerts (a whistle for G2's pack, a siren for the Pi), the exploration fanfare and the wall, fall and refusal sounds.
  They play one at a time (`voice/audio_gate.py`); every level is in `sound_levels.py` and the switches in
  [`guides/settings-switches.md`](guides/settings-switches.md).
- **Ready and quiet-mic helpers** — "G2 online" is spoken when the voice loop has finished starting (`G2_ANNOUNCE_ONLINE=off` silences it); the very quiet I²S mic gets a software gain
  (`voice/mic_gain.py`); synthesised lines are cached on disk so a repeated line costs no CPU (`voice/speech_cache.py`).
- **API usage counter** — calls and tokens are counted per day in `~/.local/share/g2/api_usage.json`
  (`voice/usage.py`).
- **Graceful degradation** — auth / rate-limit / billing failures each map to a
  spoken line instead of a crash; rate-limits retry with backoff.
- **API-key expiry warning** — startup warns when `ANTHROPIC_API_KEY_EXPIRES` is
  within the warning window.
- **Offline helpers** — `synth_to_wav`, `transcribe_wav` (no audio device
  needed), used by the Pi voice benchmark (`benchmark_pi.py`, ~94 % word recall).

---

## Memory

`pi_pipeline/memory/` — ✅.

- **Persistent fact store** with tagged recall, backing the voice `remember` tool, plus a full exchange log searched by relevance (SQLite FTS5) so older turns come back when they matter.
- **Review and undo** — `python -m pi_pipeline.memory.review` (and `tools/g2_review.py`) lists facts, exchanges and observations and deletes the ones you do not want, with an undo.
- **Reflection** — each exploration leaves a recap counted from G2's own events (no picture, no API call); one Claude call per new session can turn recaps into up to three short notes about
  his own experience (`G2_REFLECT`: off, dry or on; dry by default, so the notes are logged but not saved). Memory-processing calls are limited to one per session (`memory/call_log.py`).
- **CLI** — `python -m pi_pipeline.memory` to add / recall / forget / list.
- **Web UI** — `python -m pi_pipeline.memory.webui`, a localhost-only page to
  browse, add, forget, and (confirmed) wipe.
- **Importance and a core block** — facts carry an importance and a core flag; core facts are always in the prompt, the rest are
  recalled by relevance. A privacy rule keeps dates, times and schedules out of facts.
- **Exploration recaps as sightings** (2026-10-18; 🧩 not yet tried on G2) — each exploration's recap (what the detector saw at the
  survey stops, the room, bumps, falls) is saved as a sighting, and "where's the chair?" / "what did you find exploring?" recall it.
  Local data only, no extra API call.
- **Sightings and consolidation** — a date-only, text-only sightings log; a sleep-time consolidation pass merges and prunes
  facts with an audit log (`python -m pi_pipeline.memory consolidate`; only dry-run so far).
- **Memory-use log** — per-fact counters of how often a fact was injected, declared and matched, with a report
  (`python -m pi_pipeline.memory usage`); the free `match` mode is on, the `declare` mode costs extra API calls and is opt-in.
- **Backup** — `tools/g2_memory_backup.sh` (`g2membackup`) copies the Pi's database to the Mac.

---

## Vision

`pi_pipeline/vision/` + `tools/gv2/` — ✅ model on the camera; 🧩 the reflexes
that need the camera mounted on the frame for a real point of view.

- **Custom on-camera detector** — a 3-class YOLOv8n model (a household member +
  `dog` + `cat`) runs **on the Grove Vision AI V2 itself**, 100 % on the NPU.
  All three classes detect; verified on the real dog and cat.
- **Reproducible build recipe** — the camera firmware is frozen at Jan 2025 and
  broke every modern export toolchain; the working path (`ultralytics==8.2.8` +
  local arm64 export + `vela`) is fully written up in
  [`vision/custom-model-recipe.md`](vision/custom-model-recipe.md), with repo
  tooling: `export_yolov8_gv2.sh`, `split_yolo_dataset.py`, `vela_config_we2.ini`,
  `autobox_coco.py`.
- **Capture pipeline** — motion-gated capture → curate → contact sheet → promote
  to a keep-library → combine for upload, with a per-session checklist and a
  dataset tracker (`vision/capture-progress.md`, `vision/capture-checklist.md`).
- **Obstacle-avoidance reflex** — watches detection boxes; a large centred box →
  stop / back up / steer. No API, no network; debounced, with an urgent-hazard
  override.
- **"What do you see"** — detections summarised to a sentence and handed to Claude
  through the voice layer's callable.
- **Camera look** — ✅ asking what G2 sees takes one 240x240 picture from the Grove Vision AI V2 over USB and sends it to Claude
  with the detector's hint; the camera warms up (opens and settles the exposure) right before a picture, never on the wake word.
  Exposure is metered first, lifted in software for dim rooms and re-taken at a lower register setting for bright ones. A
  mirror phrase teaches G2 what he looks like (saved as a memory fact); recall questions are answered from memory with no
  picture. Pictures are saved only if `G2_VISION_SAVE_DIR` is set, with duplicates pruned and a 7-day expiry.
- **Cliff / edge guard** — a reflex whose input is a table-edge detector (the
  detector itself is the main remaining vision work).
- **Wall avoider and picture workflow** — ✅ on G2 since 2026-10-10: a wall estimator turns an exploring G2 away from a near wall with a sound
  (`vision/wall_distance.py`), an IMU contact signal starts the hit sequence, pictures wait for the IMU to show he has stopped swaying, and the review page
  (`g2pics`) names, filters and promotes the pictures G2 takes ([`vision/picture-library.md`](vision/picture-library.md)).
- **Detection filter and local description** — a filter between the camera and everything that reacts to it removes false cats and dogs (floor texture read as a cat); "what do you see"
  has a free local fallback that lists the detections in a sentence (`vision/describe_local.py`, `scene.py`).
- **Picture workflow** — contact pictures (what the camera sees when G2 seems to push into something), survey and naming pictures with a JSON sidecar each, a wait for the IMU to show he has stopped swaying
  before each shot, a shutter click, and exposure metering. Pictures are reviewed, filtered and promoted in the `g2pics` page.
- **Object recognition gallery** (B20, `vision/object_gallery.py` +
  `behavior/object_seek.py`) — 🧩, behind `features.object_gallery` (off by
  default). Recognises *specific* objects it's personally seen before by
  visual-similarity fingerprint, not a trained category — grows on its own,
  no retraining. Dedup, a quality gate, a capacity cap with eviction that
  never touches a named/locked entry, and "enough data" auto-locking are all
  built and unit-tested; opportunistically triggers during explore mode's
  already-stationary moments (never interrupts walking), rate-limited,
  structurally lowest-priority (only reachable after every other behaviour
  has had first claim on the tick). `tools/label_objects.py` is the fully
  local review/labeling interface (name / note / a complete flag / discard),
  nothing published or uploaded. The localizer, embedder and recognizer are built and
  evaluated on a small sample (DINOv2 had no wrong names there) but not yet wired into exploration; the labelled pictures to tune
  their thresholds are still to be collected — see [`behavior-ideas.md`](planned/behavior-ideas.md) B20.

---

## Safety reflexes & guards

Mixed: the emergency stop, sleep mode, the watchdog, the servo thermal guard and the fall and stall guards run on G2; the items marked *built, not wired in* below are complete and unit-tested but no runtime module uses them yet (listed in [`../pi_pipeline/README.md`](../pi_pipeline/README.md)). Thresholds for the rest need the real robot.

- **Emergency stop** (`behavior/emergency.py`) — the manual override: latches
  `BehaviorDriver` above *everything* (enrollment / sleep / safety / mode), emits
  stop + an alert chirp + one hold command (`kbalance` by default, configurable),
  and holds until explicitly released. Triggered by a voice phrase ("emergency
  stop" / "freeze" / "halt" / "stop moving"), `python -m pi_pipeline.app --halt`,
  or `kill -USR1 <pid>`; cleared by "resume" / `--release` / `SIGUSR2`.
- **Disabled moves** (`link/opencat.py` `DISABLED_SKILLS`) — five firmware moves are refused for every caller, with a wrong-answer horn (see "Scripted skills").
- **Eased moves** (`link/transitions.py`) — every move into a firmware skill steps the legs from the known pose, capped at 80 deg/s; stand-up uses its own 0.8 s ramp.
- **Jam reflex** (`gait/jam_guard.py`, B9a) — *built, not wired in* — vision-free: from commanded-vs-actual
  front-leg joint angle, detect a stuck push and run a fixed bump-and-turn.
- **Servo thermal guard** (`gait/thermal_guard.py`) — per-joint temperature
  tiers GREEN / AMBER / RED, with a spoken "getting warm" warning.
- **Thermal governor** (`behavior/thermal_governor.py`, backlog B26) — *built, not wired in* — NORMAL → THROTTLED →
  COOLDOWN: scales speed, softens the gait, avoids uphill, and can hold a
  cooldown pose; escalates immediately, de-escalates only after a hold.
- **Sleep mode** (`behavior/sleep_mode.py`) — AWAKE → DOZING → ASLEEP → ROUSING;
  enters after a rest period (blocked while a person is present), wakes on loud
  sound / tap / wake word / command. **Wired into `BehaviorDriver`**: emits
  `SKILL kzz` + `POWER headless` + `CAPTURE off` on sleep, `POWER interactive` +
  `CAPTURE on` + the rouse choreography on wake.
- **Carpet detector** (`gait/carpet.py`) — sustained forward-slip → boost the speed command or hand off to the
  `carpetF` gait; opt-in on the policy walk loop (`run_gait.py --carpet`).
- **Speed estimator** (`gait/speed_estimate.py`) — per-gait-cycle ZUPT bias-corrected leaky integrator over the IMU; the carpet detector's slip source.
- **Stall suspect** (`gait/imu_stall.py`) — the IMU heading jitter of a walk pushing against something; log-only. The contact signal that starts the exploration hit sequence uses it.
- **Stand guard** (`gait/stand_guard.py`) — keeps firmware balance off while G2 stands idle (re-sent every minute) and trips if the IMU shows the standing wobble.
- **Watchdog** (`diag/watchdog.py`) — no heartbeat within the stall window →
  latch STALL and send `d` (lie down, relax).
- **Supervisor** (`util/supervisor.py`, backlog B27) — ✅ restart-with-backoff for long-running workers; it supervises the camera reader and the
  microphone stream (systemd restarts the whole voice service).

---

## Attachments and the Petoi AI Head

`pi_pipeline/attachments/` — ✅ for the head, 🧩 for the arm. Guide: [`guides/attachments.md`](guides/attachments.md).

- **One setting for the neck** — `G2_ATTACHMENT` (environment) over `~/.local/share/g2/attachment.json` (`g2attach head|arm|none`) over `none`.
  `none` never sends the firmware question or adds a skill and keeps the legacy behaviour exactly.
- **Per-attachment gait** — `gait_profiles.json` holds the saved gait for each attachment (current plus history), checked against the policy's
  payload profile; if nothing saved is usable, the default policy runs and the reason is logged (`g2attach status`, `doctor`).
- **Firmware check** — for head and arm, start-up compares the BiBoard's `?` banner with the firmware the attachment needs; the arm adds its skill tokens
  (pick, put, toss, show-off, clap). The arm module has not been fitted, and its firmware and skills are untested.
- **Petoi AI Head** — 🧩 mounted on G2 (42 g, on stock Petoi firmware). It is an extra LLM used by pressing its button; Claude stays the main brain and
  nothing is integrated for now. Because it shares the serial link it can move G2, so it is used only while G2 is idle or at rest.
  [`planned/ai-head/README.md`](planned/ai-head/README.md).

---

## Real-data pipeline

`pi_pipeline/telemetry/`, `tools/g2_ingest.py`, `tools/g2_calibrate.py` — ✅. Plan: [`rl/real-data-pipeline.md`](rl/real-data-pipeline.md).

- **Always-on capture** — every walk without an explicit log file is written on the Pi (CSV plus a JSON sidecar with the hardware epoch, floor, policy and why it ended);
  it never stops a walk (`G2_AUTOLOG=off` disables it).
- **Floor labels and hardware epochs** — set by a person, never named automatically (`python -m pi_pipeline.telemetry surface|status|epochs|label|exclude`; "the floor is tile" by voice).
- **Ingest and calibration on the Mac** — runs are gated into usable, quarantined or excluded (nothing is deleted), and numbered sim-calibration snapshots are fitted from the usable ones.
  Drift and heading are measured for audit only and never feed a fit.

---

## Diagnostics & ops

`pi_pipeline/diag/` — ✅ the logging logic; 🧩 the Pi-specific sensor reads.

- **Black-box structured logger** — a full event taxonomy, a run manifest
  (start/end, duration, event + incident counts, clean-exit flag), and an
  `install_excepthook()` that logs unhandled crashes and finalises the manifest.
- **System monitor** (`diag/sysmon.py`) — SoC temperature (any Linux),
  `vcgencmd` throttle flags, battery voltage sag — emits rate-limited
  `battery.sag` / `pi.thermal_throttle` events; no-ops where a reader returns
  nothing.
- **Session report** (`python -m pi_pipeline.diag report [SESSION] [--html out.html]`, 2026-10-18) — one page per session from
  the logs that used to be read one by one: walks (end reasons, late ticks, floor), behaviour transitions, narration timing,
  walks that did not stop in time, wake triggers, billed API calls, camera timeouts, worker restarts, every WARN+ event, the profile.
- **Supervised workers** — the camera reader and (since 2026-10-18, backlog B27) the microphone stream are restarted by
  `util/supervisor.py` when they die or stall; restarts are diagnostics events.
- **Lint** — `ruff check` with correctness rules only (undefined names, mutable defaults, syntax errors), run by the pre-commit hook.
- **Feature flags** (`G2_FEATURES`, `docs/guides/feature-flags.md`) — staged
  bring-up: perception / vision-nav stack gated **off** until a real detector
  exists.
- **`doctor` preflight** (`python -m pi_pipeline.doctor`) — one-command bring-up
  readiness check: `.env` completeness, API key validity + expiry, model files
  (Vosk / Piper / gait ONNX), Python deps, serial port + optional passive board
  handshake (`?` banner + `P` voltage readback — confirms it actually speaks
  OpenCat, not just that the port opened), audio devices, free disk. Non-zero
  exit on any hard failure.
- **Black-box logging on every CLI entrypoint** — `diag.session(name)` (a
  context manager: start + crash hook + stdlib-logging bridge on entry, close
  on exit) is wired into `pi_pipeline.app`, `doctor`, `check_serial`,
  `pi_pipeline.voice`, and `gait/bench_real.py`, alongside the pre-existing
  `run_gait.py` — so the very first command you run during bring-up is
  recorded, not just the ones that happen to reach the integrated app.
  `SystemExit` / `KeyboardInterrupt` are recognised as a clean exit, not a
  crash.
- **Guided bring-up runbook** (`python -m pi_pipeline.bringup`) — the
  hardware sequence (Phase 0 bare hardware → Phase 1+ with the Pi wired in)
  as a resumable, interactive checklist (progress persists to disk);
  auto-runs only read-only/passive steps, always shows movement commands as
  text instead of executing them. Steps 1–13a are enforced stand-only; step
  13b (the first floor test) sits behind an explicit `[y/N]` confirm.
- **Guided first movement** (`check_serial firstmove`) — one joint at a time
  (head, then the 8 leg servos) with a confirm before and after each, then
  `kbalance`, then a single timed `wkF` burst — always ends at rest, including
  on abort.
- **Full movement sweep** (`check_serial allmoves`) — cycles every move G2
  knows (the voice-conversation skills, the non-duplicate autonomous
  behaviour gestures, sleep, the carpet gait, and the recovery/get-up
  keyframes, deduped), logging battery voltage and reply latency
  after each one against a logged idle baseline — a data-gathering pass run
  on the stand at bring-up TWICE (runbook step 3c on BiBoard's own USB
  before the Pi is wired in, then again at step 8c through the Pi, so the
  two sessions can be diffed for a voltage/latency delta from the Pi stack)
  that can point at a joint or sequence worth a closer look before it
  matters on the floor. Each move gets a numbered, ruled-off terminal
  announcement ("`[7/N] walk_forward (skill) -> kwkF`"), a bell, and a
  lead-time pause (`--announce-s`, default 1.5s) before it fires — so which
  move is currently running is never ambiguous while watching the robot
  instead of the screen. Doesn't yet verify a recovery keyframe's *outcome*
  (body upright or not) — that needs the IMU stream, whose line format isn't
  confirmed until step 13a's `--probe-imu`, which comes later in the
  sequence.
- **Crash forensics** (`diag/crashwatch.py`) — a heartbeat file, a fault trace and a clean-exit marker, read back at the next start, so a native crash of the voice service or an exploration session (Vosk, PortAudio, onnxruntime) leaves a report: `python -m pi_pipeline.diag.crashwatch` (`g2crash`).
- **Noise log and IMU fan-out** — a record of every command that makes the BiBoard make a noise (`link/noise_log.py`), and a per-reader copy of the shared IMU stream so the stand guard, the sensor hub and the walk loop do not steal each other's lines (`link/fanout.py`).
- **Housekeeping** — old logs and walk files are deleted at start-up (`util/tidy.py`), and a disk-space warning fires once the SD card passes a threshold (`util/disk.py`).
- **Sysid and calibration tools** — a policy-free calibration sequence logs the IMU and every joint command for sim replay (`gait/sysid_collect.py`), a servo speed fit from stepped moves (`gait/servo_step.py`), a gyro-bias check (`gait/yaw_drift_check.py`) and a fresh-baseline walk series (`gait/baseline_runs.py`).
- **Serial trace + replay** (`pi_pipeline/link/trace.py`) — every command sent
  to the BiBoard logged to a timestamped file (`--trace <path>` on the app);
  `trace.py replay` re-sends the same sequence with the same relative pacing.
- **Bench mode** (`python -m pi_pipeline.app --bench`) — for when G2 is on the
  calibration stand: no autonomous movement, voice actuator forced to mock, a
  clear banner — so `check_serial` / `run_gait --probe-imu` / joint calibration
  own the serial link without the behaviour loop fighting them.

---

## Power

`pi_pipeline/power/` — ✅ logic; 🧩 tuning + the behaviour-aware design session.

- **Idle-REST staged descent** — drop to progressively lower-power postures the
  longer G2 is idle.
- **Camera power** — the camera is switched off when G2 goes to sleep; scaling it to activity (on-demand vision) is not built.
- **Sleep mode hook** — deepest tier, shared with the behaviour sleep FSM.
- **BiBoard battery alerts** — the voice service reads the pack voltage at start, at the wake word, before a walk and on a 30-minute backstop (every read makes the board tick), also in exploration sessions, and a walk checks it every 5 s; a low reading sounds the alarm plus a spoken line, and a critical reading under load rests the legs. Thresholds are settings ([`guides/settings-switches.md`](guides/settings-switches.md)); G2 answers power questions in percent, never volts.
- **Pi battery estimate** — the PiSugar S has no telemetry, so the Pi's runtime is learned from deliberate timed tests
  (`python -m pi_pipeline.power runtime test start|collect|cancel`, `runtime list|add|forget`); the warning fires at 70 % and
  80 % of the measured runtime, counted from boot. `python -m pi_pipeline.power runtime unplugged|plugged` starts and pauses the count.
- **Wi-Fi fallback** — `tools/g2_wifi.sh` (`g2wifi`) manages a backup phone-hotspot network on the Pi.
- **Standing-wobble guard** — the firmware's gyro balance, run on a 5 Hz IMU, can sit in a ~1.9 Hz limit cycle when G2 stands.
  The voice service keeps `gb` (balance off) while G2 is idle, re-sends it every minute, and trips the guard if the IMU shows the
  wobble. Since 2026-10-19 every pose plays with the firmware gyro balance on and the guard turns it off once G2 is still (not yet tried on G2) (`gait/stand_guard.py`, `gait/stand_log.py`). Diagnosis: [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md).

---

## Robot link

`pi_pipeline/link/` — ✅ logic and the physical serial cable (in use since the first bring-up).

- **One shared serial link** — voice, vision, and RL deployment all send through
  it; opens and **reconnects on cable pull** without crashing its caller.
- **Command builders** — friendly names → OpenCat serial strings; joint-move
  string builder for streamed policy output.
- **Dangerous-command denylist** — calibration / factory-reset prefixes are
  refused.
- **Fall-recovery state machine** (`link/recovery.py`) — *built, not wired in* — detect a flip → run the
  scripted get-up → settle. Today the firmware's own `rc` handles a flip.
- **Bring-up self-test** (`link/check_serial.py`) — list ports, ping the board,
  send one command, cycle the conversational skill set, or run the full
  `allmoves` sweep (every move G2 knows, voltage + latency logged) as a
  hardware smoke test.

---

## Operator tools (Mac side)

`tools/` and the `g2*` shell helpers (`g2help` lists them) — ✅.

- **Deploy and ops:** `g2_deploy_when_online.sh` ships a clean export of the last commit to the Pi when it is online; `g2_safe_stop.sh` stops a session safely; `g2_wifi.sh` manages the phone-hotspot fallback;
  `g2_memory_backup.sh` copies the Pi's memory database to the Mac; `g2_pi_ssh_setup.sh` reaches the Pi when its name does not resolve.
- **Hardware sessions:** `g2_explore.sh`, `g2_turns.sh`, `g2_baseline.sh`, `walk_log_summary.py`, and servo response tests.
- **Vision data:** capture, curate, label (`label_objects.py`, `g2_review.py`), promote and combine for upload; the on-camera model export in `tools/gv2/`.
- **Data and calibration:** `g2_ingest.py` and `g2_calibrate.py` (see "Real-data pipeline").
- **Housekeeping and docs:** `g2_cleanup.py` removes leftover scratch files; `check_docs.py` guards the docs; generated pages (backlog, env reference, helpers, results index) and a docs bundle for a website.

---

## What comes with the repo (for a fork)

- **RL training pipeline** — `rl_training/opencat-gym/`: PyBullet + SB3, the
  residual-on-`wkF` gait design, curriculum + domain randomisation, eval
  decathlon, `watch_trained.py` with a vision ray-fan overlay, and `run20m_ppo`
  itself.
- **Companion pipeline** — `pi_pipeline/`: every module above, every
  hardware-specific stage behind a mock/real seam, `.env`-driven config, a
  test suite that needs no network, audio or key, `setup_pi.sh` + `fetch_models.sh` for a headless Pi Zero 2 W.
- **The vision recipe** — a reproducible path to a custom on-camera detector for
  the frozen-firmware Grove Vision AI V2, with tooling in `tools/gv2/`.
- **Deployment stack** — ONNX export + on-robot control loop, sim-validated.
- **Documentation** — `docs/`: the living [`project-plan.md`](project-plan.md),
  [`how-it-works.md`](how-it-works.md), [`architecture.md`](architecture.md), a behaviour-ideas backlog ([`planned/`](planned/README.md)), and
  subject-organised guides / vision / hardware / RL folders.

---

*Keeping this current:* when a capability lands (a trait, a skill, a guard, a
model), add or flip its line here in the same change — same as
`project-plan.md` and `README.md`. This file is the showcase; the plan is the
rationale.
