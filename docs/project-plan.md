# Bittle X Robot Companion — Project Plan

**Goal:** a Bittle X quadruped ("G2") that (1) learns to walk via reinforcement learning rather than scripted keyframes,
(2) perceives its surroundings with an onboard camera and avoids obstacles, (3) holds voice conversations through the Claude
API, and (4) keeps persistent memory of past interactions.

Movement, vision, voice, and memory are built as **independent systems running alongside each other**, not a single unified
controller.

**How this document works.** It is the roadmap and decision log — checklists, statuses and links, not narrative. Where things
live (one home per fact; see [`README.md`](README.md#where-to-update-what)):

| Looking for | Go to |
|---|---|
| What is true right now (deployed, tested on the robot, open problems, next steps) | [`STATUS.md`](STATUS.md) |
| Full detail behind a phase (moved here verbatim 2026-10-02) | [`plan-detail/`](plan-detail/) |
| Open work by ID | [`backlog.md`](backlog.md) |
| Dated data and findings | the logs: [`rl/real-walk-log.md`](rl/real-walk-log.md), [`rl/hw1-log.md`](rl/hw1-log.md), … |
| Parts list and hardware decisions | [`hardware/parts-and-decisions.md`](hardware/parts-and-decisions.md) |
| Day-1 bring-up sequence | [`guides/bring-up-sequence.md`](guides/bring-up-sequence.md) (executable: `python -m pi_pipeline.bringup`) |

Status key: ✅ done · 🧩 built and tested against mocks, needs the robot · 🔧 in progress · ⬜ not started.

## Phases at a glance

| Phase | State | Detail |
|---|---|---|
| 1 Repo setup | ✅ | below |
| 2 Orientation | ✅ (curriculum items deferred) | below |
| 3 RL training in simulation | ✅ policies built; sim locomotion work paused pending the real-robot comparison | [`plan-detail/phase3-rl-training.md`](plan-detail/phase3-rl-training.md) |
| Recovery (catch / get-up) | 🧩 built; partly tested on hardware | [`plan-detail/recovery.md`](plan-detail/recovery.md) |
| 4 Hardware assembly | 🔧 assembled and bring-up done; Pi mount is temporary | [`plan-detail/phase4-hardware-assembly.md`](plan-detail/phase4-hardware-assembly.md) |
| 5 Basic control | ✅ | [`plan-detail/phase5-basic-control.md`](plan-detail/phase5-basic-control.md) |
| 6 Sim-to-real deployment | 🔧 loop and safety layers built; first walks done | [`plan-detail/phase6-sim-to-real.md`](plan-detail/phase6-sim-to-real.md) |
| 7 Voice + Claude | ✅ voice loop running with the real mic and speaker on the Pi; command recognition still being tuned | [`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md) |
| 8 Perception | 🧩 model on the camera and "what do you see" works; navigation reflexes gated off | [`plan-detail/phase8-perception.md`](plan-detail/phase8-perception.md) |
| 9 Memory | ✅ built and live on the Pi; importance, consolidation (dry-run only) and a use log added | [`plan-detail/phase9-memory.md`](plan-detail/phase9-memory.md) |
| 10 Integration | 🧩 runtime built; not yet run on the robot | [`plan-detail/phase10-integration.md`](plan-detail/phase10-integration.md) |
| Petoi AI Head vs the Pi | ⬜ decision pending, head arriving ~2026-10-10 | below |

## Open TODOs that affect everything

- **Sim payload bug (found 2026-09-23, fixed in the env):** the welded payload bodies had no inertia, so the sim body could not tilt;
  every policy since `run20m_ppo` trained on it. Still to do: classify past resilience conclusions as unaffected/suspect/invalidated,
  list the trainings to re-test (including approaches closed on locked-body results), re-baseline the deployed policy and the scripted
  walk, and recheck the fall-recovery replay (and the URDF's ±90° joint limits against the real `rc` keyframes).
  Full text: [`plan-detail/sim-payload-bug.md`](plan-detail/sim-payload-bug.md). The replay tool `sysid_replay.py` carried the same bug
  and was fixed 2026-10-01.
- **Hardware first:** the front-left shoulder servo fault and the carpet failures come before any new walking work —
  [`rl/real-walk-log.md`](rl/real-walk-log.md), [`STATUS.md`](STATUS.md).

## Hardware (parts, power, enclosure)

Parts list ($567 as finalized), resolved questions (independent Pi power via the PiSugar S, BiBoard V1 is an ESP32-U4WDH, spec sheet) and
the battery-awareness plan: [`hardware/parts-and-decisions.md`](hardware/parts-and-decisions.md). Vendor specs: [`hardware/specs.md`](hardware/specs.md).
Build record and wiring: [`../blueprints/`](../blueprints/README.md).

Open:
- [ ] Mount the Pi/PiSugar stack properly (currently a temporary mount; the printed standoff is not impact-rated). See the build manual.
- [ ] Confirm the back cover closes over the mounted Pi (measured too shallow for Pi + PiSugar; a modified cover/clips is planned).
- [ ] Wire and test the microphone and speaker (parts ordered 2026-09-29) — if the Pi stays in the build. **Microphone done 2026-10-03, speaker/amp done 2026-10-04** (clear capture over I2S, spoken replies through the voiceHAT card; [`blueprints/biboard-pi-connector.md`](../blueprints/biboard-pi-connector.md)).
- [ ] Battery-aware behavior: get real runtime data (idle/walking/talking on a full charge) before building the low-charge warning.
- [ ] Measure G2's 2S pack runtime (BiBoard side) with a timed test, the way the Pi side was measured (Pi figure: [`STATUS.md`](STATUS.md); the pack's ~45–60 min of walking is only an estimate, [`hardware/pi-power.md`](hardware/pi-power.md)). Not scheduled. Why it matters: the Pi and pack look comparable on paper, so the result decides whether a second pack for the BiBoard is worth buying.

## Phase 1 — Repo setup ✅

- [x] Single repo (`rl_training/` + `pi_pipeline/` + `docs/` + `blueprints/`), README, `.gitignore`, secrets policy (`.env`, never committed).
- [ ] Commit incrementally per phase (ongoing).

## Phase 2 — Orientation ✅

- [x] Community Bittle simulator; browsed the OpenCat firmware ([`hardware/opencat-gait-structure.md`](hardware/opencat-gait-structure.md)).
- [ ] Deferred: Petoi's beginner coding curriculum and Python fundamentals (picked up while building Phase 3). No official Petoi browser simulator exists.

## Phase 3 — RL training in simulation ✅ (paused)

Software only. Operating model since 2026-09-07: every run is a **deployment candidate** judged against the frozen base; fresh tagged
runs, not serial finetunes; promote only if it keeps base walking quality, adds a capability, and clears the sim-to-real path. The
deployed policy and the lineage: [`STATUS.md`](STATUS.md), [`rl/hw1-log.md`](rl/hw1-log.md). What the gait does and its limits:
[`rl/walking-policy.md`](rl/walking-policy.md). Logs: [`rl/`](rl/README.md).

Open / deferred (detail in [`plan-detail/phase3-rl-training.md`](plan-detail/phase3-rl-training.md)):
- [ ] Real-time terrain adaptation is limited to what the IMU shows (no foot contact or torque feedback).
- [ ] Heading on hardware: no magnetometer, yaw is gyro-integrated and drifts; the sim's sub-degree heading hold will not carry over.
- [ ] Imitation-learning approaches from the Bittle research (optional).
- [ ] A taller-obstacle curriculum for a generally higher swing (the reactive "lift higher when blocked" version can't transfer without foot sensing).
- Closed: the reactive survive-loop hit an IMU-only ceiling (~18–25 %); learned vision-conditioning of the walk was ruled out.

## Recovery — walk / catch / get-up 🧩

Switch over separate skills: the learned gait (walking), its own reactive catch (stumbling), scripted `rc` (fallen on a side), `rl` then `rc`
(on its back), selected by `RecoveryFSM` in `pi_pipeline/link/recovery.py`. A real flip and self-right worked on 2026-09-28 using the
firmware's own auto-`rc` (the Pi was not in the loop). Reference: [`hardware/self-righting.md`](hardware/self-righting.md); detail:
[`plan-detail/recovery.md`](plan-detail/recovery.md).

- [ ] Test `rc` / `rl` against the fall types the policy produces; re-author the keyframes in Skill Composer if unreliable.
- [ ] Enable gyro assist and decide whether the push reflex should fire mid-walk (firmware fork or a Pi-side version).
- [ ] Point `RecoveryFSM` at the real IMU, wire its actions through `SerialLink`, tune thresholds — and **retest once the Pi is in the loop**:
      the firmware's own auto-recover and `RecoveryFSM` could conflict.

## Phase 4 — Hardware assembly 🔧

Done: Bittle X V2 assembled (2026-09-28); firmware erased and reflashed to current official (2026-09-29); servo calibration redone and
verified with `kbalance`; Pi Zero 2 W set up headless; 5-pin Pi socket soldered on the BiBoard; Serial-2 enabled with `XS` (2026-09-30);
Pi↔BiBoard link working; camera set up on the Pi. Detail: [`plan-detail/phase4-hardware-assembly.md`](plan-detail/phase4-hardware-assembly.md).

- [ ] Pi+PiSugar mount to the frame: power confirmed, mount mechanism not yet solved.
- [ ] Pi housekeeping: disable the serial login shell, the 1-wire interface, and Wi-Fi power-save (`raspi-config`).
- [ ] Use `ardSerial.py` from the OpenCat repo as the reference serial commander (optional).

## Phase 5 — Basic programming & control ✅

Movement commands from Python, the OpenCat command structure, and the vision module's on-device detection are done; the hardware link
(`check_serial ping`, IMU stream) was confirmed 2026-09-30. Detail: [`plan-detail/phase5-basic-control.md`](plan-detail/phase5-basic-control.md).

## Phase 6 — RL sim-to-real deployment 🔧

Done: Pi inference (<1 ms per step), ONNX export with a parity check, the 80 Hz on-robot loop, and the deployment-safety layers (thermal
guard, carpet detector, jam guard, fall guard, watchdog). On hardware: IMU format fixed and verified at 5.0 Hz, open-loop servo-sign check
and the first hard-floor walks done — [`rl/real-walk-log.md`](rl/real-walk-log.md). Detail:
[`plan-detail/phase6-sim-to-real.md`](plan-detail/phase6-sim-to-real.md).

- [ ] Real sim-to-real gap work: re-score on the real path, the scripted-vs-learned comparison ([`rl/h1-rubric.md`](rl/h1-rubric.md)),
      sysid against real logs, and retrain if warranted. Blocked first on the FL shoulder servo.
- [ ] **Training upgrade and the next 20M (2026-10-08, in progress):** a training-process review fixed 11 bugs (curriculum probes without their hazard, ignored seeds,
      level ledge blocks on slopes, a world-mismatched gate baseline, a stray rough floor in ~30% of benchmark episodes, ...); approved upgrades: native arm64 Python (about 3x
      training speed), 6 envs, larger PPO batches, a per-hazard frontier curriculum that finds each hazard's ceiling itself, forward-only commands, an optimizer bundle, longer
      hazard episodes, imitation on measured joints, a privileged critic (training-only; the policy keeps G2's inputs), health checks, best checkpoint and a plateau stop.
      Behaviour changes are screened two seeds at a time (`phase_v4.py`); the 20M follows on the user's go, then the V3 vs V4 benchmark report. State and decisions:
      [`plan-detail/handoff-2026-10-08.md`](plan-detail/handoff-2026-10-08.md) section 12.
- [ ] **Real-to-sim calibration from G2's own walks (approved 2026-10-08):** `rl_training/opencat-gym/real2sim.py` replays logged joint commands open-loop through the training
      env and compares roll / pitch spread and sway frequency with G2's IMU (heading excluded: real data is never a drift source); `--fit` ranks servo speed limit x motor
      force x ground friction (run with the Mac idle). First check (2026-10-06 tile walks): sway frequency matches (0.79 vs 0.78 Hz), sim roll about 10-13% low. Next: the
      controlled capture sessions at the next hardware visit (STATUS next steps 0b), then a fit; a fitted value enters training only through the real-data pipeline's gates.
- [ ] **V3 gait retrain: plan approved 2026-10-06 — [`rl/v3-retrain-plan.md`](rl/v3-retrain-plan.md) (start at §0).** It replaces the item
      below and the closed v2.2 campaign: calibrate the sim to G2, single-lever 3M screens (incl. mirror symmetry and a turning gate), a staged
      chain, a hardware check-in, then one 20M run with gait checks at 3M/5M/10M and no planned tuning runs after it. Why V2.1 drifts:
      [`rl/real-walk-log.md`](rl/real-walk-log.md) "Why V2.1 drifts right".
- [ ] *(Superseded by the V3 plan above; kept for its measurement list.)* **Fresh hardware measurements, then a new 20M training run on them (planned 2026-10-06; do not launch until asked).** G2 now has the case, camera,
      microphone and speaker mounted and weighs about 422 g, against the sim's roughly 377 g. (1) Measure: the six logged hard-floor V2.1 walks are done (2026-10-06, `tools/g2_baseline.sh`, voltage logged under load);
      still to do: weigh the body and the Pi stack separately and find the balance point.
      (2) Update the sim from the data in [`rl/real-walk-log.md`](rl/real-walk-log.md) "Candidate sim changes": the measured payload mass and position (backlog H2),
      more body-roll disturbance (real roll swing is about 1.7x the sim's), heading-drift randomization, a wider IMU bias range, and a friction / foot-slip check
      (the real robot travels about 16% farther). (3) Train a fresh from-scratch 20M run (not a fine-tune of V2.1), judged on its own 3M checkpoint against the
      previous 20M run's 3M checkpoint, then scored through the real path (`benchmark_decathlon.py --hw i`) and walked on G2 against V2.1.
      Goal: a sim that matches the real hardware more closely, and a better gait.
- [ ] **Heading hold on the Pi (2026-10-07: works on G2).** The closed-loop stride-difference hold kept six V2.1 walks within 6 deg of straight (details: [`rl/real-walk-log.md`](rl/real-walk-log.md) "Closed-loop heading hold works"). **Superseded the same evening:** the per-foot test showed the front feet steer, and a closed-loop hold on the front-left foot alone kept V2.1 within 13 to 21 deg over 25 s (against +148 without); it is now the default in every policy walk (voice, exploration, `run_gait.py`), see [`rl/real-walk-log.md`](rl/real-walk-log.md) "Which foot steers G2". To do: tile and longer-walk data, a turn command, and the question of whether the base walk also needs drift training ([`rl/v3-decisions-log.md`](rl/v3-decisions-log.md)).
- [ ] Find and test the self-right trigger command for BiBoard V1 (serial, not the IR remote).

## Phase 7 — Voice + Claude 🧩

Built: config-driven Claude client, `perform_skill` and `remember` tools, state cues, command acknowledgement, the real mic and speaker
(running on the Pi since 2026-10-04), a "shut down" that also powers the Pi off, battery alerts, and speech-recognition hardening for stop and
shut-down commands. Detail: [`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md).

- [x] Real-mic capture and the wake-word gate on the Pi — done 2026-10-03, including a first voice → Claude → walk run on the real G2
      ([`plan-detail/phase7-voice.md`](plan-detail/phase7-voice.md)).
- [ ] Settle how a Claude-started walk is stopped (the onboard module's "rest", a gait cap, or both) (`perform_skill` now takes an optional duration in seconds; a calibrated distance is still open).
- [x] Text-to-speech and mic input through the robot's own body — done 2026-10-04 (mic + speaker on the Pi; the Petoi AI Head is still to be evaluated).
- [x] Shut down also powers the Pi off cleanly (2026-10-05; the PiSugar S keeps powering the halted Pi, so the battery switch is flipped by hand).
- [ ] Reliable command recognition: three fixes deployed 2026-10-05 (wake word run into the command, first word lost at the wake-word handover,
      a stop / shut-down grammar recognizer). Collect transcripts (`G2_LOG_HEARD`); if misses continue, cost out a larger Vosk model, then cloud STT for open conversation only.
- [ ] Free LLM instead of paying per turn (decided 2026-10-03: the provider will be the Petoi head's service, XiaoZhi). The swappable-LLM code is built
      ([`guides/swappable-llm.md`](guides/swappable-llm.md)): `fast` and `routed` modes, with Claude as the fallback. To do when the head arrives: create the
      account at xiaozhi.me (phone-number registration; the privacy gate applies, use a throwaway number and no household names), then find out whether it offers
      anything our code can call. Today it is reached through the head's audio pipeline, with no documented developer API, so the likely route is the self-hosted
      backend in [`research/xiaozhi-esp32-review.md`](research/xiaozhi-esp32-review.md). Then measure its quality on G2's tools and personality.
- [ ] `SerialActuator` end-to-end for voice skills (the link is confirmed); confirm it runs independently of the 35+ built-in voice commands.
- [ ] A buzzer-pattern or posture implementation of the state cue; connect to Claude live and measure latency.

## Phase 8 — Perception 🧩

Built: obstacle-avoidance reflex (not wired into the app), camera serial format, custom detector on the camera (3 classes), scene description, and
the camera look (2026-10-04: a 240x240 picture goes to Claude when asked what G2 sees; exposure metered first; the camera warms up right before a picture).
Vision-based navigation is gated off (`features.vision`). Target capability and detail:
[`plan-detail/phase8-perception.md`](plan-detail/phase8-perception.md); detection-layer notes: [`vision/detection-layer.md`](vision/detection-layer.md).

- [ ] Improve the 3-class model (distance/pose variety, 300+ calibration images, a fourth class).
- [ ] Train obstacle and table-edge classes on the real mounted camera view.
- [ ] **Cliff/edge avoidance (`CliffGuard`)** — highest priority once the camera is mounted; the app does not construct one yet, so it needs both a classifier and wiring.
- [ ] "Reasoning" layer: structured detections to Claude over serial (the BiBoard cannot run a vision-language model).
- [ ] (Stretch) more robust self-righting with IMU-based flip detection.
- Deferred on purpose: wiring `Avoider` decisions to the actuator (the model only knows face/dog/cat, so it would back away from people and pets).

## Phase 9 — Memory ✅

SQLite store (exchanges log + facts), FTS5 recall, the `remember` tool, a CLI and a localhost web UI. Detail:
[`plan-detail/phase9-memory.md`](plan-detail/phase9-memory.md).

- [x] Importance, a core block, sightings log, sleep-time consolidation and a memory-use log (2026-10-05); consolidation has only been dry-run.
- [ ] Semantic recall (embeddings) if keyword matching feels too literal.
- [ ] Exercise it across real multi-session conversations once the voice loop runs live.
- [x] **Back up the memory DB off the robot** — manual `g2membackup` built 2026-10-04 (periodic scheduling still open). It is one SQLite file on the Pi's SD card
      (`~/.local/share/g2/g2_memory.db`, `G2_MEMORY_DB`); a bad card loses everything. Idea: a periodic copy to the dev machine with SQLite's
      online backup (not a plain `cp`), kept outside the repo, with a restore step. If the AI Head replaces the Pi, memory would live in its backend or
      on our own server instead.

## Decision pending — Petoi AI Head vs the Raspberry Pi (opened 2026-10-02)

The [Bittle AI Head](https://www.petoi.com/products/bittle-ai-head-upgrade-kit) ($39, 42 g; an ESP32-C3 with its own microphone and speaker; cloud LLM; no camera mentioned by Petoi)
is **ordered, arriving ~2026-10-10**. It might replace the mic and speaker parts; Petoi expects it to **complement** the Pi, not replace it (single-core C3, firmware to be open-sourced,
UART shared with the Pi by default). **Undecided; keeping the Pi is a fully valid outcome.** Criteria, behavior inventory, test steps and scorecard:
[`research/petoi-ai-head-evaluation.md`](research/petoi-ai-head-evaluation.md).

Judged on: (1) is the scripted gait about as good as the learned gait (the owner would prefer to keep the RL policy); (2) can G2 still do most of the
behaviors that make it feel alive; (3) the trade-off — a streamlined ~42 g module vs the Pi build's wiring, weight and exposed hardware, against what
would be lost (custom control and safety layers, our Claude/memory path, local voice, the SSH/Python dev loop, privacy, vendor dependence).
Outcomes: A keep the Pi · B Pi + head · C head only with scripted gaits · D head only with our logic elsewhere. **Do not remove the Pi before the
scorecard is filled.** Privacy gate before powering the head (throwaway account, no household faces or names).

## Phase 10 — Full integration 🧩

The behavior runtime (`BehaviorDriver`, `BehaviorRuntime`, `app/`) is built and tested against mocks; detail and the per-feature history:
[`plan-detail/phase10-integration.md`](plan-detail/phase10-integration.md).

- [ ] All four systems running alongside each other without conflicts; run `python -m pi_pipeline.app --serial` on the robot.
- [ ] Expect timing/integration bugs even after each piece passes alone.
- [ ] README final setup instructions and a demo; a pinned dependency list.
- [ ] INSPECT peer bow: done and sim-validated, needs on-robot tuning.

## Known risks / honest expectations

- Hardware debugging is a different skill than web debugging — no stack traces; a fault could be code, wiring, power, or the hardware itself.
- RL gaits look rougher than an animal's, especially early; sim-to-real rarely works first try — expect a gap and iteration.
- Full integration (Phase 10) is the hardest, messiest part.
- **No flipping or rolling tricks** (decided 2026-09-15): the Pi + PiSugar stack rides on a printed standoff that is not impact-rated and shifts the
  moment of inertia; `flip`/`flipD`/`flipF`/`bf`/`tbl`/`rl` (as a trick)/`bx`/`lucky`/`excited` are excluded from any voice or `perform_skill` set while that mount
  is in use. Detail: [`hardware/petoi-skills-survey.md`](hardware/petoi-skills-survey.md).
- Never put G2 on its back for a test: the Pi and BiBoard are exposed.

## Community & support

- r/petoi (Reddit) — Petoi's recommended community; Petoi Forum Archive (petoi.camp)
- `github.com/PetoiCamp/OpenCat` — firmware source; `github.com/PetoiCamp/NonCodeFiles` — community 3D-print files
- `github.com/ger01d/opencat-gym` — the RL training environment
