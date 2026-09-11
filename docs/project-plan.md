# Bittle X Robot Companion — Project Plan

**Goal:** a Bittle X quadruped ("G2") that (1) learns to walk via reinforcement
learning rather than scripted keyframes, (2) perceives its surroundings with an
onboard camera and avoids obstacles, (3) holds voice conversations through the
Claude API, and (4) keeps persistent memory of past interactions.

Movement, vision, voice, and memory are built as **independent systems running
alongside each other**, not a single unified controller.

This is a living document — update phases, specs, and findings as the work
progresses. Behavior ideas to pick from live in
[`docs/behavior-ideas.md`](behavior-ideas.md) — the reference list for "what
should we work on next."

---

## Parts list (finalized — $567)

| Item | Price |
|---|---|
| Petoi Bittle X V2 (alloy servos) | $380 |
| Raspberry Pi Zero 2 WH kit (pre-soldered headers, heatsink, mini-HDMI adapter, OTG cable) | $115 |
| SanDisk 32 GB Ultra microSDHC (A1, Class 10, UHS-I) | $22 |
| 5 V / 2.5 A micro-USB power supply | $10 |
| Petoi AI Vision Camera Module (Grove Vision AI V2, Arm Cortex-M55 + Ethos-U55) | $40 |
| PiSugar S 1200 mAh (independent Pi power — fits Pi Zero W/WH/2W; **not** the "S Plus") | — |
| Calibration stand (G2 sits with legs off the ground) — servo/gait bring-up without ever risking a fall; see `docs/guides/gait-deployment.md` step 6 | — |

### Resolved

- **Pi power: independent, via PiSugar S 1200 mAh.** Drawing the Pi from Bittle's
  shared battery causes "reduced motion capability" (Petoi's own docs) and risks
  servo-spike brownouts. The PiSugar pogo-pins to the Pi's underside pads, leaving
  the GPIO header free, and provides UPS safe-shutdown. To avoid two 5 V sources,
  wire BiBoard → Pi **data-only (RX/TX/GND)**, no 5 V. Full reasoning:
  [`docs/hardware/pi-power.md`](hardware/pi-power.md).
- **Enclosure:** Petoi ships an official back-cover STL with a Pi cutout
  ([`Bittle_Cover_with_hole_for_Pi.stl`](https://github.com/PetoiCamp/NonCodeFiles/blob/master/stl/Bittle%20%26%20BittleX/BittleCover/Bittle_Cover_with_hole_for_Pi.stl)),
  so the cover can close over the mounted Pi.
- **BiBoard V1 MCU:** standard **ESP32-U4WDH** (Xtensa dual-core LX6, via an
  ESP32-MINI-1 module), not an S3/C3. This is why Phase 8 sends structured
  detection results over serial rather than streaming raw frames. Flash is
  **4 MB**, SRAM **520 KB** (Petoi pages citing "16 MB / WROOM-32D" describe
  BiBoard V0). Board also carries a **6-axis MPU6050 IMU (no magnetometer)**, an
  onboard offline voice-recognition module, and a speaker.
- **Full vendor-doc spec sheet** for every part — with the "why it matters" for
  each — is in [`docs/hardware/specs.md`](hardware/specs.md).
  Key downstream effects: no magnetometer ⇒ favour **yaw-rate** over absolute
  heading in the RL reward (Phase 3); the vision module can stream **detections
  or a raw frame but not both**, and runs at 192×192 / ~10–30 FPS (Phase 8);
  the PiSugar S has **no battery-percentage readout** (hardware-only).

### Open (check when hardware arrives)

- Confirm BiBoard V2 can be wired data-only, or whether its mount ties 5 V to the
  data lines by default.
- BiBoard V1's spec lists Pi compatibility as "Pi 3A+, 4, 5" — the Pi Zero 2 WH
  isn't listed (the PiSugar S side *does* officially list Pi Zero 2 W/WH). Verify
  the 5-pin socket and serial wiring are compatible.
- Confirm the back cover fits once the Pi is mounted.
- BiBoard V1's onboard voice-recognition module + speaker: decide whether the
  wake trigger / offline fallback commands use it instead of the Pi (Phase 7).

### Power awareness — G2 warns when it thinks it's running low

The PiSugar **S** gives no battery %, voltage, or low-battery signal (only
"external power present"), so G2 can't *measure* its charge — it has to
*estimate* from elapsed run time.

- **Plan:** track uptime since the last time it was on the charger; when it
  passes a learned threshold, G2 proactively says something in character ("I'm
  getting tired, might need to rest on the charger soon") via the voice
  pipeline, and repeats/escalates as it gets closer to the empirical limit. On
  the charger ("external power present" flips true) it resets and can say it's
  charging.
- **Needs first:** real battery-life data — run G2 doing representative work
  (idle, walking, talking, vision on) on a full charge until the Pi browns out,
  a few times, to get mean runtime and its spread. Do this early in hardware
  bring-up.
- **Built 2026-09-05:** `pi_pipeline/power/` (CPU governor / Wi-Fi power-save
  toggle / disable-unused peripherals) and `behavior/idle_posture.py` (idle-REST
  staged descent — sit, then lie down, with life signs). Battery-*aware*
  behaviour (rest sooner on low charge) is blocked on the estimate above.
  **Sleep-mode FSM built 2026-09-10** (`behavior/sleep_mode.py`). On-demand
  vision (the two-stream safety/rich split) is still a design task (B18). Full
  analysis: [`hardware/pi-power.md`](hardware/pi-power.md).
- **Later upgrade for a real signal (not just a timer):** an ADC on a BiBoard
  Grove analog pin (G3/G4) reading the pack voltage, so the warning is based on
  actual cell state. Optional; the timer is enough to start.

---

## Phase 1 — GitHub repo setup ✅

- [x] Create the repo (single repo, `rl_training/` + `pi_pipeline/` + `docs/`).
- [x] Starter README with goals, hardware, and this roadmap.
- [x] `.gitignore` from the start — secrets, trained models, venvs.
- [x] Secrets policy: `.env`, `config.local.*`, `**/secrets.py`, `**/api_keys.py`
      (documented in `.gitignore`); never committed.
- [ ] Commit incrementally per phase, not one dump at the end (ongoing).

## Phase 2 — Orientation (while hardware ships) ✅ / deferred

- [x] Community Bittle simulator (grgv.xyz/blog/bittle) — done, for gait feel.
- [x] Browse the OpenCat firmware (`PetoiCamp/OpenCat`, `PetoiCamp/OpenCatEsp32`)
      to see how gaits are structured in code. See "How OpenCat gaits are
      structured" below.
- [ ] ~~Petoi's official browser simulator~~ — none exists. The full
      `bittle-x.petoi.com` manual and Doc Center were searched; the only
      simulation options are NVIDIA Isaac Sim (relevant to Phase 3, not a quick
      demo) and OpenCatWeb (a UI for a *real* Pi-mounted robot).
- [ ] Petoi beginner coding curriculum — deferred; jumped ahead to Phase 3.
- [ ] Python fundamentals — deferred; picked up while building Phase 3.

## Phase 3 — RL training in simulation

Software only; no physical robot needed until Phase 6 deployment.

### Operating model (pre-hardware, 2026-09-07)

Everything we train now is a **deployment candidate**. `run20m_ppo` is already a
deployment-quality policy and stays frozen and untouched, so no experiment can
leave us without a shippable gait — worst case is a wasted overnight.
- Fresh tagged runs against deliberately-designed envs, **not serial finetunes**
  on the frozen base (history: finetunes erode more than they add).
- A candidate is promoted only if it (1) holds the decathlon's **obstacle-free /
  cruise / commanded cells** at ≥ `run20m_ppo` — no base-walking regression;
  (2) adds a capability or robustness `run20m_ppo` lacks; (3) clears the
  sim→real path (ONNX + parity + Pi budget, already built for `run20m_ppo`).
- **Eval caveat:** a vision policy that correctly slows/stops at obstacles will
  score lower mean speed on an obstacle course — that is not a regression. Judge
  base capability on obstacle-free cells; judge obstacle cells on
  traverse-success / cleared count / fall rate, not speed. See
  [[feedback_deployment_candidate_model]].

### Current state

- **Phase 3 gait locked:** `auto_gait_final`, tag `phase3-gait`. Straight
  level-ground walk at 0.256 m/s (≈50 Hz-basis; see the control-rate note below),
  1.29 m per 251-step episode, heading drift 0.16° (non-accumulating), 4.5 cm
  lateral wander, never falls, stride 0.103 m, `diagonal_trot_corr` −0.59.
  Config: `FAC_HEADING=5.0`, `PAW_Z_TARGET=0.020`, `FAC_GAIT_SYMMETRY=3.5` on top
  of v6. On `development`; checkpoint at
  `rl_training/opencat-gym/trained/phase3-gait_ppo.zip` (gitignored).
- **Later gait, on `development` via Run 6:** `auto_rec_r5_ppo`, tag
  `gait-v7-stumble-catch` — crisper trot (`diagonal_trot_corr` −0.58), tighter
  heading (7.6° max drift), always-on stumble-catch balance term, no
  obstacle-course falls; ~7% slower forward than `phase3-gait`.
- **Run 7 ("walk"), closed:** best checkpoint `walk_r2`, tag `walk-v8-r2` — 0%
  falls, best heading of the project, but converges slow (~0.07 m/s vs the 0.11
  target). The Run 7 env config (273-dim observation, `TARGET_SPEED` tracking
  bonus, impulse drills) is now on `development`, but `phase3-gait` and
  `gait-v7-stumble-catch` remain the reference gaits until a real-hardware
  head-to-head. Established that big-stumble recovery can't be reward-tuned
  further on this control setup.
- **Sim benchmark, learned vs scripted** (`benchmark_gaits.py`,
  [`docs/rl/gait-benchmark.md`](rl/gait-benchmark.md)): on flat ground the learned
  gaits win — `phase3-gait` covers ~4× the distance of open-loop `wkF` keyframes.
  On obstacle courses the scripted keyframes are hard to beat; `phase3-gait` does
  markedly worse (brittle, trips), `gait-v7-stumble-catch` only reaches parity.
  RL earns its place for flat efficiency, not (yet) for obstacle robustness. The
  scripted side is open-loop only here — the firmware's gyro-balance layer would
  widen its obstacle lead — so confirm on hardware.
- **Refinement regimen + Phase 4 stance-recovery — DONE (2026-09-03).** The
  pause was lifted 2026-09-02 for a pre-hardware push; the regimen produced
  **`run20m_ppo`** (20M from-scratch, G4b recipe — command-conditioned residual
  gait, payload-conditioned, tracks speed commands to 0.007 m/s, walks a −24°
  descent, 0% falls on the payload-on decathlon). That is now the **frozen base
  gait for hardware.** Phase 4 then tried three reversible continuations for
  active stance recovery (ledge terrain in DR / phase-clock revival /
  diagonal-support catch shaping) — **none was a keeper; no gait change.** Also
  fixed a silent bug where every `--from` continuation diverged (LR restart at
  3e-4 on a converged policy). Details:
  [`docs/rl/refinement-regimen.md`](rl/refinement-regimen.md),
  [`docs/rl/phase4-decision-log.md`](rl/phase4-decision-log.md).
- **Sim gait work is now done pending hardware.** The open question — is a
  learned gait actually better than OpenCat's scripted `wkF` for plain walking —
  has a sim answer above; the real-robot head-to-head confirms it against the
  *firmware* gait. Next steps are ONNX export + Pi bring-up, then that
  head-to-head. Learned-gait work otherwise resumes only when
  perception-in-the-loop becomes active — see the **Phase 8 Target capability**.
- **Pre-hardware robustness push — CONCLUDED (see the 2026-09-05 update below +
  the hardware-gated backlog).** Reopened 2026-09-03 to harden the walk for
  *walk-anywhere* use; every finetune-continuation on the new course collapsed
  (one geometry bug, fixed), and the fresh from-scratch `run20m_newcourse` 20M
  came back a **negative result** — `run20m_ppo` stays the frozen base. Learned
  vision-in-the-gait was then ruled out across Phases A–F. **Sim locomotion work
  is done pending the real-robot H1 head-to-head.** The remaining scenario ideas
  live in [`docs/rl/hardware-gated-backlog.md`](rl/hardware-gated-backlog.md),
  each with a trigger. Detail of the push itself is kept below for history.
  - **Rough-terrain training.** The base recipe's `ROUGH_TERRAIN` was ~1.8 mm
    amplitude — cosmetic. Built a proper rough course: `CARPET`, a single
    `GEOM_HEIGHTFIELD` body (no scattered obstacles), 13 mm multi-octave bumps +
    a broad ~±11 mm/1.5 m rolling swell, std-normalised so it fills the height
    range and stays passable (`run20m_ppo` crosses it at ~0.07–0.10 m/s, 0 falls).
    Earlier iterations: scattered-box `RANDOM_TERRAIN` bump-up, then tumbled
    "rubble" (`run20m_rough` 3.5 M, `run20m_rough2` stopped ~1.4 M) — both
    retired; the single heightfield deflects feet instead of catching edges and
    is one collision body (cheaper sim). Branch `gait-rough`.
  - **`run20m_carpet`** — continuation from `run20m_ppo`, `CARPET` on for 50 % of
    DR episodes (rest keep the flat/sloped plane so slope/obstacle DR is
    unchanged), `--finetune-lr 1e-4 --finetune-target-kl 0.05`, 4 M steps.
    Launched 2026-09-03. Verdict pending its learned-vs-scripted + decathlon eval.
  - **Robustness backlog** — the categorised list of real-world scenarios still
    to train/eval (single-servo failure, IMU bias/mount tilt, pick-up &
    set-down, directional terrain catches, slope transitions, friction
    asymmetry, …): [`docs/rl/robustness-backlog.md`](rl/robustness-backlog.md).

  **Update 2026-09-05 — the training collapse + fresh retrain.** `run20m_carpet`
  was reverted (no capability gain, eroded flat speed — R0 in the robustness
  log). The training ground was then redesigned (rubble-primary, wider slopes,
  placement tuning) — and **every** finetune-continuation on the new course
  collapsed `ep_rew_mean` at ~1.1 M steps (6/6). Isolated to one geometry bug
  (commit `01cf87e`): the 2026-09-04 "hills can carry a slope grade" change
  rotated the `_rough`/`_carpet` heightfield about its placement centre (x≈1.5 m
  from the robot), so at pitch ≳ 3.4° the terrain rose 8–12 cm under the spawn
  point → robot embedded in the mesh → runaway `r_height` penalty (−100 k
  episodes, no visible fall) → PPO critic divergence. Fix: heightfields carry no
  overall grade (pre-2026-09-04 behaviour); everything else in the redesign
  kept. Confirmed 4 ways; validated by two clean 3 M continuations + a
  rough+pitch 0–14° sweep. **Now running:** `run20m_newcourse` — a fresh 20 M
  from-scratch run on the fixed course, to answer whether the redesigned course
  produces a better policy or `run20m_ppo` stays the base. Benchmark upgraded:
  T9 held-out generalization tier, per-cell command-following + tail stats,
  Wilson-CI comparison, ledge cells lowered to 15–20 mm + step-down restored.

### Environment

`rl_training/opencat-gym/` is a curated copy of
[`ger01d/opencat-gym`](https://github.com/ger01d/opencat-gym) (MIT, commit
`12b39ff`) — PyBullet + Stable-Baselines3 + Gymnasium. It ships
`models/bittle_esp32.urdf`, our exact hardware. `opencat_gym_env.py` is the whole
environment and the main lever; `train.py` runs 8 parallel envs with PPO.

Setup blockers hit and resolved (kept in case they recur elsewhere):

- System Python 3.8 is too old for SB3/Gymnasium (need ≥3.10) → Homebrew Python
  3.11 in a project `.venv`.
- `brew install python@3.11` failed against an outdated Xcode → `xcode-select
  --install`, then `sudo xcode-select --switch /Library/Developer/CommandLineTools`.
- `pybullet` has no macOS wheel and its bundled zlib defines `fdopen` to `NULL`,
  breaking the source build → install with `CPPFLAGS="-Dfdopen=fdopen"`
  (documented in `requirements.txt`).
- Skipped `stable-baselines3[extra]` (Atari deps need SDL2) — plain
  `stable-baselines3` + `gymnasium` + `tensorboard`.

**Control rate:** one `env.step()` runs 3 PyBullet substeps at the default
1/240 s → **80 Hz control** (`CONTROL_HZ`). `evaluate_policy.py` assumed 50 Hz
through Run 6; Run 7 corrected it — multiply pre-Run-7 reported m/s by 1.6 to
compare. The real BiBoard control rate is ~48–50 Hz (servo PWM limit), relevant
for Phase 6.

### Training history (condensed)

The full per-round working logs (v1–v7 tuning, the automated loops, the survive
loop) were removed 2026-09-10 — git history has them. The load-bearing results:

**v1–v6 — getting to a stable trot (Aug 2026).** Four early runs collapsed
mid-training (`approx_kl` spike, reward → ~0) regardless of the reward function.
Root cause was **structural, not any one term**: `PENALTY_STEPS` equalled the run
length (the smoothness penalty never finished ramping) and the LR / clip range
never decayed. **Fix (v5):** `PENALTY_STEPS` 2e6 → 5e5 + a linear LR decay in
`train.py` — reward then climbed smoothly to ~1100. **v6** (`PAW_Z_TARGET`
5 → 15 mm, tag `gait-v6-known-good`) was the first clean converged trot, but
curved slightly right.

**Automated loop 1 — the curve fix.** `FAC_HEADING = 5.0` (penalise *accumulated*
heading error, not just yaw rate) killed the rightward curve: end-of-episode
drift 12.5° → 0.16°, never falls. Result **`auto_gait_final` (tag `phase3-gait`)**,
merged. Loops 2–4 then established that **reward-weight tuning cannot crisp the
trot further** — `auto_gait_final` sits at a local optimum; the remaining levers
are structural (diagonal-pair phase in the obs, `wkF` imitation, a CPG action
space).

**Run 5 — DR + `wkF` imitation.** Wired the domain-randomisation knobs
(friction / link-mass / IMU-noise / shoves / obstacles) behind a curriculum ramp,
and added `FAC_IMITATION` — a DeepMimic-style phase-by-phase match to Bittle's
`wkF` keyframes (`reference_gait/`, open-loop verified). **The imitation reward is
what finally produced a real diagonal trot** that weight tuning alone could not.

**Run 6 — fall recovery.** **Key finding: a Bittle cannot self-right from a full
tip-over (> 1.3 rad) — no roll-axis actuation.** An escalating recovery reward
(weight 8 → 22, torque-boosted, eased criteria) converged at 0 % recovered every
time. The loop pivoted to the learnable version — *catching a stumble before it
becomes a fall* — via `FAC_BALANCE`. Winner **`auto_rec_r5_ppo` (tag
`gait-v7-stumble-catch`)**: trot −0.58 (crispest in the project), no
obstacle-course falls, ~7 % slower than `phase3-gait`. Merged. The recovery
window code stays in `opencat_gym_env.py` but dormant (`FAC_RECOVERY = 0`).
Firmware's own scripted self-right covers only slow side/forward falls and has no
BiBoard-V1 IR trigger — [`docs/hardware/self-righting.md`](hardware/self-righting.md).

**Run 7 — target speed + more recovery.** `big_stumble_recovery_rate` stayed 0.0
across three rounds — **recovery is bounded by the control setup (reactive,
IMU-only, weak sagittal legs), not by reward tuning** (confirms Run 6). Best
checkpoint `walk_r2` (tag `walk-v8-r2`): 0 % falls, best heading of the project,
but converges slow (~0.07 m/s) — not merged. **Decision: stop reward-tuning
recovery; settle RL-vs-scripted on real hardware (the H1 head-to-head).**

### Evaluate and lock ✅

- [x] Evaluate in simulation and save the best checkpoint(s) for deployment —
      **done: `phase3-gait`** (see Current state). `gait-v7-stumble-catch` is the
      later candidate from Run 6. Both are sim-to-real starting points for Phase
      6 and will need re-tuning against real hardware.

### Open / deferred (Phase 3)

- Real-time terrain and disturbance adaptation is where RL beats scripted gaits,
  but Bittle has no torque/force feedback and no foot-contact sensing — the only
  real-time body-state signal is the IMU (orientation/tilt). So the policy can
  learn to recover from pushes, slopes, and minor unevenness, but not
  foot-level terrain awareness. Real robustness needs a reward that explicitly
  values balance recovery (not just forward speed) plus domain randomization —
  both now in place from Run 5 on.
- **Heading signal on real hardware:** the BiBoard IMU (MPU6050/ICM42670) is
  6-axis — **no magnetometer**, so there's no absolute yaw reference; real yaw is
  gyro-integrated and drifts over seconds-to-minutes. The sim optimises against a
  perfect quaternion yaw. Bias the reward/observation toward **yaw rate** (clean
  from the gyro) rather than accumulated heading error, and expect real-world
  heading hold to be looser than the sim's sub-degree numbers. Affects the
  resid-tuning loop directly. See
  [`docs/hardware/specs.md`](hardware/specs.md).
- Imitation-learning approaches from the UVA/Harvard Bittle research (stretch,
  optional).
- **Reactive obstacle purchase:** teach the policy that when a front foot is
  blocked it should lift higher to get on top. Learnable in sim but needs
  per-foot contact/height in the observation, which the real Bittle can't sense —
  so it wouldn't transfer. The transferable version is a taller-obstacle
  curriculum plus a loose/decaying imitation weight, for a generally higher,
  more adaptive swing. Revisit after the reactive-robustness gait is solid.

**Survive-loop (Session A, closed 2026-09-01).** 10 rounds tried to lift the
residual gait's *conditional survival* — the fraction of courses where scripted
`wkF` falls but the learned gait stays up. Neither a bespoke survival reward
(capped ~25 %) nor the `legged_gym` / PA-LOCO field-standard recipe (18 %) cleared
the 30 % target — **the reactive stumble-catch ceiling on this platform (IMU-only,
no roll DOF, weak sagittal servos) is real**, matching Runs 6–7. Approved gait
**`surv_r5`** (18 %, passes every other gate: flat speed 0.094, trot −0.55,
obstacle fall rate at parity with scripted); `opencat_gym_env.py` on `development`
is at its config. Field-standard insights (`projected_gravity` obs, explicit
terminal fall penalty, dominant soft speed reward) are worth a *hardware-in-the-loop*
pass, not more blind sim iteration.

## Recovery — walk / catch / get-up (separate from the gait)

Architecture from the ANYmal recovery work (Lee/Hwangbo/Hutter 2019): a **switch
over separate skills**, not one monolithic policy.

| body state | who handles it |
|---|---|
| walking, upright | the learned residual gait (Phase 3) |
| stumbling (tilted, not down) | the gait's own reactive catch — survive-loop ceiling ~18–25% |
| fallen on a side / front | scripted `rc` skill (`krc`) |
| fallen on its back (supine) | scripted `rl` then `rc` (`krl` → `krc`) |
| the switch | `pi_pipeline/link/recovery.py` — a `RecoveryFSM` on IMU roll/pitch |

Bittle has no roll-axis joint, so a *learned* self-right is off the table (Run 6).
The scripted `rc`/`rl` keyframes lever the body over with the legs; the firmware
also auto-runs `rc` on an IMU-detected flip when gyro assist is on. Full detail:
[`docs/hardware/self-righting.md`](hardware/self-righting.md).

**Built pre-hardware (2026-09-01):**
- `pi_pipeline/link/opencat.py` — `RECOVER`/`ROLL_OVER`/`BALANCE`/`STAND` tokens.
- `pi_pipeline/link/recovery.py` — `RecoveryFSM(roll, pitch) → RecoveryAction`
  (`NONE` / `RECOVER` / `ROLL_THEN_RECOVER` / `SETTLE` / `GIVE_UP`), with a
  fall debounce, a get-up timeout + bounded retries, and a "needs a human"
  give-up. `ACTION_COMMANDS` maps actions to serial strings. 11 unit tests
  (mock orientation traces + a fake clock).

**On hardware (Phase 4–6):**
- [ ] Test the stock `rc` / `rl` against the fall types training produces; if
      unreliable, re-author the keyframes in Skill Composer.
- [ ] Enable gyro assist (`g`) → the firmware's `IMU_EXCEPTION_PUSHED`
      stand-still push reflex works for free. Decide whether to extend it to
      fire mid-walk (firmware fork or a Pi-side reimplementation).
- [ ] Point `RecoveryFSM` at the real IMU (read roll/pitch over serial), wire
      `ACTION_COMMANDS` through `SerialLink` with a wait between skills, and tune
      the thresholds (`fall_rad`, `supine_rad`, `getup_timeout_s`).

## Phase 4 — Hardware assembly

- [ ] Assemble Bittle X V2 (~40–90 min).
- [ ] Check servo calibration — pre-assembled units ship calibrated, so this is a
      check/fine-tune, not an assumed step. Only dig in if movement looks off.
- [ ] Get it moving on stock firmware first, before any custom code.
- [ ] Set up the Pi Zero 2 WH: pre-configure Wi-Fi + SSH in Raspberry Pi Imager
      (headless), confirm SSH access.
  - **Can start NOW (Pi + PiSugar + card + PSU arrived 2026-09-01; robot/camera
    not yet).** Full researched runbook + open-question answers in
    [`docs/guides/pi-bring-up.md`](guides/pi-bring-up.md): flash Bookworm
    64-bit Lite, kill Wi-Fi power-save, zram+swapfile, disable-BT for the PL011
    UART, deploy `pi_pipeline` on ARM, then `benchmark_pi.py` (Vosk / Piper /
    Claude-API / RAM). PiSugar **S** = dumb UPS: no I²C, no battery %, power-
    present only.
- [ ] Mount the Pi; test power and serial **independently** (power can work while
      serial doesn't). Per Petoi's Raspberry Pi serial docs:
  - Power the Pi from the PiSugar S, not the BiBoard. Wire BiBoard → Pi
    data-only (RX/TX/GND), Pi 5 V unconnected. See [`docs/hardware/pi-power.md`](hardware/pi-power.md).
  - Install the 5-pin Pi socket on BiBoard V1; use Petoi's back-cover STL with
    the Pi cutout.
  - `sudo raspi-config` → Interface Options → Serial Port → disable the serial
    login shell, enable the serial hardware → reboot.
  - Disable the Pi's 1-wire interface (GPIO 4 reset-signal conflict).
  - Disable Wi-Fi power-save (`sudo iw wlan0 set power_save off`) proactively —
    the `brcmfmac` power-save bug drops SSH under CPU load and is a nightmare to
    diagnose later.
  - On the BiBoard: serial command `XS` (or edit `OpenCat.h` and reflash) to
    enable Serial-2 working mode.
  - Serial device: likely `/dev/ttyS0` on the Pi Zero 2 W (Pi-3-family SoC);
    confirm once wired.
  - Use `ardSerial.py` from the OpenCat repo as the reference serial commander.
- [ ] Set up the AI Vision Camera Module: mount at the head, connect to the Grove
      socket, upload firmware via Petoi Desktop App or Arduino IDE.

## Phase 5 — Basic programming & control

**Status:** the serial control layer is built and tested (mock/offline) —
`pi_pipeline/link/`. `SerialLink` (lazy open, auto-reconnect, non-raising
`send()`), `opencat.py` (command-string builders + `is_safe()` calibration
block), and `check_serial.py` diagnostics. `voice/SerialActuator` now goes
through it. Command reference and a hardware bring-up checklist are in
`pi_pipeline/link/README.md`.

- [x] Send movement commands from Python — `link.opencat.skill()` →
      `SerialLink.send()`; `check_serial send <cmd>` / `skills` / `rest`.
- [x] OpenCat command structure captured — `k<skill>`, `m<idx> <deg>`,
      `b<tone> <ms>`, `d` (rest), `XS` (Serial-2). Provisional: `g`/`v`/`V`/`p`.
      A **battery-voltage query token still needs finding** in the firmware
      serial parser.
- [ ] Hardware bring-up: `check_serial ports` → set `G2_SERIAL_PORT`; enable
      Serial-2 on the BiBoard; `check_serial ping` / `skills` to confirm.
- [x] Test the vision module's on-device detection via the SenseCraft AI Model
      Assistant web debug GUI. **Done 2026-09-05** — stock classification model
      deployed, live feed + labels confirmed.
- **Camera → Pi is over USB, not the Grove/GPIO pins** (decided 2026-09-05 from
      the Seeed wiki): the Grove 4-pin connector is **I²C** (`0x62`), not UART.
      Link the module USB-C → the Pi's USB *data* port (Pi Zero 2 W: the *inner*
      micro-USB) → it enumerates as `/dev/ttyACM0`, same SSCMA AT/JSON protocol,
      `VISION_SERIAL_BAUD` 921600. `SerialDetectionFeed` sends `AT+INVOKE=-1,0,1`
      on open (the module doesn't self-stream) and `AT+BREAK` on close.

## Phase 6 — RL sim-to-real deployment

**Status (2026-09-03): the deployment stack is BUILT and sim-validated;
remaining work is hardware-gated.** Full plan + state: `docs/guides/gait-deployment.md`.

- [x] **Pi bring-up** (`scripts/pi_setup.sh`) — Zero 2 W runs the policy-sized
      net in **0.43 ms** (3% of the 80 Hz budget), no thermal throttling. The
      "can a Pi Zero 2 W run `predict()` fast enough" open question is **answered
      yes** — no on-MCU / decision-transformer route needed (backlog H8 closed).
- [x] **ONNX export + parity check** — `export_onnx.py` / `verify_onnx.py`;
      `trained/run20m_ppo.onnx` (max|diff| vs torch 9.5e-7). ONNX + `onnxruntime`
      instead of PyTorch — torch's RAM footprint is the problem, not the math.
- [x] **On-robot control loop** — `pi_pipeline/gait/`: `residual_policy.py`
      (exact 278-d obs mirror + phase clock + residual→joint map),
      `deploy_map.py` (URDF→OpenCat servo indices, sign/offset calibration
      hooks), `run_gait.py` (80 Hz loop: BiBoard `V` IMU stream → policy → `m`
      command). `validate_deploy.py` confirms **0 joint-degree cells differ**
      from `model.predict` across 5 commands × 251 steps.
- [x] **Deployment-safety infrastructure (2026-09-05), built + unit-tested,
      hardware-validation pending:**
  - `pi_pipeline/gait/thermal_guard.py` — servo thermal guard on `run_gait.py`.
    Estimates per-joint heat from commanded motion (no P1S sensor).
    **Layer 1+2 done 2026-09-10:** 3-tier per-joint indicator (`ThermalTier`
    GREEN/AMBER/RED at 50/85 % of trip) + per-joint spoken warning; new
    `behavior/thermal_governor.py` (`ThermalGovernor`) — AMBER throttles
    speed + softens gait, RED holds a folded cooldown pose. All constants
    placeholders; [`hardware/servo-thermal.md`](hardware/servo-thermal.md).
  - `pi_pipeline/diag/` — **Phase 1 + the non-hardware parts of Phase 2 done
    (2026-09-10).** JSONL event log + black-box ring + manifest +
    `summarize/replay/tail/sync`; taxonomy events from `run_gait` / `serial_link`
    / the behaviour driver. Phase 2: `diag/watchdog.py` (heartbeat +
    stall→black-box-flush→safe-stop, wired into `run_gait`),
    `diag.incident()` + expanded auto-flush names, `install_excepthook()`,
    manifest finalize on close, `diag/sysmon.py` (`# HARDWARE` battery /
    Pi-thermal stubs). Left: validating the black box on a real fall / link drop.
    [`hardware/diagnostics.md`](hardware/diagnostics.md).
  - `pi_pipeline/power/` — zero-risk power levers (CPU governor, Wi-Fi
    power-save, disable-unused peripherals). idle-REST built; **sleep-mode FSM
    built 2026-09-10** (`behavior/sleep_mode.py` — curl + vision off +
    power-save, wakes on IMU/wake-word/sound). Driver-side wiring of both
    pending. [`hardware/pi-power.md`](hardware/pi-power.md).
  - `pi_pipeline/util/supervisor.py` — **new 2026-09-10.** `Supervisor` +
    `WatchdogPolicy`: restart-on-death/hang with exponential backoff + a
    give-up ceiling, for the audio / serial worker threads on hardware.
  - `pi_pipeline/behavior/bindings.py` — **new 2026-09-10.** `DriverBindings`
    maps every `BehaviorDriver` `Effect` onto an optional sink; `MockBindings`
    lets the whole driver loop run end-to-end in CI. Real sink impls +
    input plumbing are the on-hardware step.
  - `pi_pipeline/gait/jam_guard.py` — **new 2026-09-10.** `JamGuard` (B9a):
    vision-free servo-strain jam reflex (bump-and-turn). Constants HW-gated.
  - `pi_pipeline/gait/speed_estimate.py` + `run_gait.py --carpet` — **new
    2026-09-10.** `ZuptSpeedEstimator` (IMU-accel + per-cycle ZUPT) feeds
    `CarpetDetector`; BOOST_CMD / firmware-`kcarpetF` hand-off wired. Body-X
    accel plumbing through `parse_imu_line` + threshold tuning are HW-gated.
- [ ] **On hardware:** wire Pi↔BiBoard, `run_gait.py --probe-imu` (fix
      `parse_imu_line` if the format differs) → `--openloop` (verify servo
      signs) → `--cmd` (learned gait) → the H1 head-to-head vs firmware `kwkF`.
- The older `ger01d/opencat-gym-sim2real` firmware path is **not used** — the
  stock OpenCat `m` command + `V` IMU stream carry the loop; no firmware flash.
- **No firmware fork (decided 2026-09-10).** `pi_pipeline` stays an application
  layer on **stock** OpenCatEsp32 over serial — that already exposes the
  keyframe library, gyro-balance, IMU exception reflexes, and calibration. New
  skills go via Skill Composer ("Newbility" slots), not a rebuild. Fork only
  narrowly + later if a capability genuinely can't be done Pi-side.
- [ ] Expect a real sim-to-real performance gap — normal, not failure.
- [ ] Iterate: adjust the reward and/or retrain in sim based on real-hardware
      behavior, redeploy.
- [ ] Find and test the **self-right trigger command** for BiBoard V1 (the IR
      remote path doesn't apply — likely a serial command). Add it to
      `pi_pipeline/link/opencat.py`. Falls will be frequent during RL sessions
      and the firmware skill only covers slow side/forward ones — see
      [`docs/hardware/self-righting.md`](hardware/self-righting.md).

## Phase 7 — Voice + Claude integration

**Status:** the pipeline runs end-to-end on a dev machine in text mode —
`pi_pipeline/voice/` (own venv). `wake → STT → Claude → TTS → skill`, every
hardware-specific stage behind an interface (`MockActuator`/`SerialActuator`,
`MacTTS`/`PiperTTS`, `TextSTT`/`VoskSTT`, `AlwaysAwake`/`VoskWakeWord`). Claude
replies parsed into spoken text + `perform_skill` / `remember` tool calls.
**Audio backends installed + validated offline (2026-09-10)** — Piper synth →
WAV → Vosk transcribe round-trips at 94 % word recall (`benchmark_pi.py`). A
character mode (`gir`, opt-in, toggleable by voice) rides on the personality
trait system. Remaining: a live-API run (needs a key —
`python -m pi_pipeline.voice.livecheck`), real mic/speaker on the Pi, and the
Pi Zero 2 W voice-stack benchmark.

- [x] **Config-driven Claude client** — `pi_pipeline/config.py` (env: key, model,
      max tokens, timeout, history depth, persona) + `voice/conversation.py`
      (rolling history, retry-on-timeout, memory seam for Phase 9).
- [x] **Response → spoken text + action commands** — `perform_skill` tool;
      `voice/skills.py` maps skill names to OpenCat `k<token>` serial commands;
      one reply can both talk and move.
- [x] **State-cue interface** — `voice/cues.py` (`LogCue` now; buzzer/posture
      later). Chirp vocabulary drafted 2026-09-10 (`behavior/chirps.py`), wired
      into `BehaviorDriver` as `CHIRP` effects 2026-09-10 (see Phase 10).
- [x] **Command acknowledgement (user request 2026-09-10)** — *every* recognised
      local command (`match_local_command` non-`None`) **and** every
      conversational turn fires `DriverInputs.ack` → an un-rate-limited
      `ChirpMood.ACK` "heard you" blip + a `"heard"` cue, *before* the slower
      spoken reply; and a bare skill from Claude with no speech now still gets a
      spoken "Okay". Rationale: a misheard command is immediately audible so it
      can be cancelled ("resume" / activity). `ack` in `_EVENT_BOOLS`; the voice
      loop bridges it via `on_event`.
- [~] **Live API end-to-end check — harness built 2026-09-10, needs a key to run.**
      `pi_pipeline/voice/livecheck.py` (`python -m pi_pipeline.voice.livecheck`) /
      `test_livecheck.py` (skips without a key): a few billed calls that verify a
      plain reply, `perform_skill` parsing on "do a happy wiggle", `remember`
      fact parsing, and the `memory_context` seam. Put `ANTHROPIC_API_KEY` in
      `.env` and run it.
- [x] **Audio backends installed + validated offline (2026-09-10).**
      `requirements-audio.txt` deps are in `pi_pipeline/.venv`
      (`vosk 0.3.44`, `piper-tts 1.7.0`, `sounddevice 0.5.6`, `onnxruntime
      1.23.2`); models fetched (`models/piper` 301 MB incl. `en_US-ryan-low`,
      `models/vosk` 68 MB small-en). New offline-testable methods
      `PiperTTS.synth_to_wav()` / `VoskSTT.transcribe_wav()` + a round-trip test
      (Piper synth → Vosk transcribe) that **passes** — the STT/TTS path works
      end-to-end with no mic/speaker. Still hardware: real mic capture on the Pi,
      speaker playback, and the Pi Zero 2 WH RAM/latency check (`benchmark_pi.py`).
- [ ] Speech-to-text — real-mic capture + wake-word gate on the Pi (`voice/stt.py`
      / `wake_word.py` `sounddevice` path). Health-monitor for the audio + serial
      worker threads is built (`pi_pipeline/util/supervisor.py`).
  - Bookworm's PEP 668 blocks plain `pip install` on-device — use the venv.
- [ ] Text-to-speech through the robot's speaker (`PiperTTS` → Pi audio out).
- [ ] Text-to-speech through the robot's speaker (`PiperTTS` → Pi audio out).
- [ ] `SerialActuator` end-to-end: `XS` "Serial-2" mode on the BiBoard, confirm
      the skill commands land.
- [ ] Confirm this runs independently of the 35+ built-in voice commands (they're
      a separate firmware path; these commands go over serial).
- [ ] A buzzer-pattern / posture implementation of the state cue.
- [ ] Speech-to-text — cloud API vs. local (Whisper/Vosk); affects Pi RAM
      headroom. From similar Pi-based LLM voice robots (SunFounder PiDog docs,
      `marceld23/Ai-Robo-Dog`, `rockywuest/pidog-embodiment` — all target Pi
      4/5 with 2 GB+, so treat as directional):
  - A local always-on wake-word detector (Vosk) that only triggers full STT on
    activation — cheap, avoids constant network calls on a weak board.
  - Local TTS (Piper, e.g. `en_US-ryan-low`) is viable and skips cloud latency.
  - On the Pi Zero 2 WH's small headroom, even lightweight Whisper may be too
    heavy — evaluate Vosk for both wake-word and full STT on real hardware.
  - Health-monitor and auto-restart any long-running audio/hardware threads —
    pidog-embodiment logs worker threads dying silently with no restart.
  - Bookworm's PEP 668 blocks plain `pip install` on-device — use a venv (already
    planned) or `--break-system-packages`.
- [ ] Connect to Claude via the Anthropic API (usage-billed, separate from any
      Claude subscription).
  - Config-driven LLM client (env vars for key/model/timeout) with a request
    timeout tuned for the Pi's slower CPU.
  - Split Claude's response into spoken text + structured action commands
    (PiDog's pattern) — maps onto the OpenCat serial interface, so one reply can
    both talk and trigger a skill.
- [ ] Text-to-speech through the robot's speaker.
- [ ] Confirm this runs independently of the 35+ built-in voice commands (two
      separate systems).
- [ ] A simple state cue (buzzer pattern or posture) for listening / thinking /
      speaking — Claude round-trips will have noticeable latency on this hardware.

## Phase 8 — Environment perception

### Target capability — the near-term goal once vision is working

The concrete definition of done for perception-driven locomotion (the bullet
below on revisiting the gait policy):

> G2 walks confidently across a cluttered floor, steps over cables and small
> objects it sees, slows or stops at a big obstacle or a table edge, and stumbles
> noticeably less.

Explicitly **not** in scope: parkour, recovering from a hard kick or shove,
reliable stair climbing. Those are bounded by the hardware (weak sagittal-plane
servos, no roll-axis joint, a detection — not depth — camera at head height) and
by the reactive-recovery ceiling established in Runs 6–7.

**Status:** `pi_pipeline/vision/` is scaffolded and testable against a mock
detection feed — same mock-interface pattern as voice/memory. `DetectionFeed`
(`MockDetectionFeed` / `SerialDetectionFeed`), a local `Avoider` reflex
(debounced, urgent hazards preempt the cooldown; `none → turn → stop → back up`),
and `scene.summarize` / `scene.narrate` (LLM-injected, decoupled from `voice`).
Remaining items are the serial wire format, a trained detection model, threshold
tuning, and the Phase 10 wiring — all hardware-gated.

> **2026-09-08 — vision-navigation is flag-gated OFF.** The camera now runs a
> working **3-class detection model** (household member + `dog` + `cat`,
> 2026-09-09) — but that's *recognition*, still not an obstacle/edge detector,
> so nothing on the bot perceives objects in its path and the gate stays on.
> Master flag **`features.vision`** (default
> `False`) forces `vision_safety` / `vision_perception` / `avoidance_act` /
> `explore` off; `BehaviorDriver(vision_available=False)` drops EXPLORE,
> recognition hop, CliffGuard reflex and "G2 meet X" enrollment;
> `run_gait.py --skills` refuses without it. Re-enable the whole stack with
> `G2_FEATURES="+vision"` once a real detector is deployed. Nothing deleted.
> Rationale + the multi-class model options: `docs/vision/detection-layer.md`.

- **Hardware constraint:** Bittle X has one module slot, taken by the AI Vision
  Camera. A separate proximity/distance sensor is not an option alongside it — so
  cliff/edge detection, if pursued, must be a camera-based visual classifier
  (SenseCraft-trained "floor" vs. "edge ahead"), not a dedicated sensor. Use the
  module's `classes()` output for that — a boxless classification path, lighter
  than object detection.
- **Vision module limits** (vendor docs — full detail in
  [`docs/hardware/specs.md`](hardware/specs.md)):
  - **Detections *or* a raw frame, never both at once.** The `Avoider` reflex
    (needs the detection stream) and `scene.narrate` (needs a frame for Claude)
    must timeshare or mode-switch, not run concurrently. Results and frames use
    different links (UART vs USB), which helps.
  - Model input is **192 × 192**; object detection runs **~10–30 FPS**. Thin
    objects (cables) are only detectable when close/large in frame. A
    vision-conditioned gait policy gets a fresh obstacle read only every ~3–8
    control steps — assume stale-between-frames data.
  - Swapping the deployed model takes **1–2 min** — one multi-class model, no
    runtime switching.
  - Camera-mode toggle over serial is `XC` on / `Xc` off (distinct from `XS`).
- [x] **Obstacle-avoidance reflex** — `vision/avoidance.py`. Local, no network;
      box `area` as the closeness proxy, bearing from `center_x`; consecutive-
      frame debounce + cooldown, with `STOP`/`BACK_UP` preempting. Thresholds
      (`AvoiderConfig`) need tuning against real detections + the robot's
      stopping distance.
- [x] **Camera→Pi serial format confirmed** (SSCMA AT protocol): JSON lines,
      921600 baud, `{"name":"INVOKE","data":{"boxes":[[x,y,w,h,score,target_id]]}}`
      — box centre + size in model-input pixels, score 0–100, numeric class id
      (labels set out-of-band via `VISION_LABELS`). `SerialDetectionFeed` parses
      it; `Detection.from_center_px()` normalises. Link is **USB** (module USB-C
      → Pi USB data port, `/dev/ttyACM0`), not the Grove connector — that's I²C
      (`0x62`), not UART. **Verified on real hardware 2026-09-05**: box `(x,y)`
      IS the centre (`from_center_px` correct as-is), input size IS 240 px
      (`resolution` field says so). `feed.py` fixed to send `AT+INVOKE=-1,0,1`
      on open (module doesn't self-stream) and `AT+BREAK` on close; only
      `type==1` messages carry results.
- [x] **First custom model trained + deployed + pipeline-validated (2026-09-06):**
      a single-class face detector (B15, one household member). SenseCraft "Image
      Collection Training" → Grove Vision AI V2. 161 daylight positive frames + 12
      empty-room negatives (added with **no box** — that's how the flow learns the
      negative class). Positives-only first cut over-fired confidently on a bare
      wall; the negatives killed it. Runs through `g2vision` (`SerialDetectionFeed`
      → `scene` → `Avoider`), acquires/drops the subject instantly, scores ~60–80.
      Wired into `.env` (`VISION_LABELS` / `VISION_MIN_SCORE=45`). Full workflow:
      `docs/guides/train-vision-model.md`.
- [x] **Multi-class detection model WORKING on device (2026-09-09):** 3 classes
      (household member + `dog` + `cat`), YOLOv8n @ 192 px, mAP@50 0.907. Root
      cause of a week of dead flashes: the GV2 firmware is **frozen at Jan 2025**
      and only decodes ~2024-era export heads. The path that works —
      `ultralytics==8.2.8` trained on Colab, then `yolo export format=tflite
      int8` run **locally on arm64 Python 3.9** (Colab's 3.13 can't), then vela.
      All of it is repo tooling now: **`tools/gv2/`**
      (`split_yolo_dataset.py`, `export_yolov8_gv2.sh`, `vela_config_we2.ini`) +
      `tools/autobox_coco.py` + `tools/vision_diag.py`. Full 12-step process:
      `docs/vision/custom-model-recipe.md`. Known limit of this first
      model: detects up close only (100-image INT8 calib set; 300+ wanted) —
      improvement loop speced in `docs/vision/capture-progress.md`.
- [ ] **Improve the 3-class model** — diagnostic `vision_diag` logging pass →
      shot list → recapture (distance/pose variety) → retrain with a 300+
      calibration set. Then add a 4th class (2nd household member) at `nc: 4`.
- [ ] Train the **obstacle / table-edge** classes (cables, small objects, desk
      edge) — the desk-edge class is `CliffGuard`'s detector and is gated on the
      camera being **mounted on the frame** (real POV; hand-held frames won't
      transfer). See B16.
- [ ] **Cliff/edge avoidance — `CliffGuard`, designed 2026-09-04, HIGHEST
      PRIORITY once the camera lands** (G2 lives on the user's desk; must never
      walk off it). Full design: `docs/behavior-ideas.md` **B16**. Confirmed not
      trainable into the gait (no forward perception, no real foot-force
      sensing either) — a zero-debounce local reflex that preempts every other
      behavior, using the light `classes()` floor-vs-edge path, custom-trained
      on the real desk, biased hard toward false-stops over a missed edge.
      Physical backstop (a desk-edge lip, supervision-gated autonomy) is the
      honest answer for a true "never," since vision alone can't promise it.
- [x] **Scene description path** — `vision/scene.py`: `summarize()` (deterministic
      text from detections) and `narrate(frame, ask)` where `ask` is an injected
      `str -> str` (the voice layer's Claude call, or a dedicated one). Structured
      detections → text → Claude → spoken, no raw frames.
- [ ] "Reasoning" about what it sees: BiBoard V1's ESP32-U4WDH can't run a vision-
      language model, so send structured detections (type/position) over serial to
      the Pi and hand descriptions to Claude — no raw frames.
  - pidog-embodiment's Pi 4 benchmarks for on-device VLM (SmolVLM): 27–37 s per
    call, ~400 MB RAM — borderline on a Pi 4, infeasible on a Pi Zero 2 WH.
    Confirms cloud reasoning is the right call.
  - PiDog attaches images to LLM calls only for occasional "what do you see"
    queries, not continuous avoidance — matches the split above.
- [~] **Perception-in-the-loop locomotion — RL approach CLOSED 2026-09-07; now a
      behaviour-layer reflex.** A 3-campaign autonomous investigation
      (`docs/rl/vision-in-gait.md`) tried to bake a
      forward-terrain feature + goal-bearing command + cliff feature into the
      gait policy so it could slow / step-over / detour / halt from vision.
      **Result: goal-directed turning is not achievable in this sim** — an
      open-loop test showed the firmware scripted turn gaits (`wkL`/`wkR`)
      produce ~0° of yaw in PyBullet with this URDF (real Bittle turning leans on
      foot-slip + the firmware gyro turn-assist the sim doesn't model). No 20M
      ever ran; `run20m_ppo` untouched.
      **New plan:**
      - **Turning → firmware.** Heading changes use the scripted `kbk`/`wkL`
        turn gaits (they work on the real robot), triggered by the behaviour
        layer. `AvoidanceAction.TURN_*` map to these.
      - **Vision-while-walking → the `Avoider` reflex** (`pi_pipeline/vision/
        avoidance.py`), which sets the *speed command* the RL walk policy already
        tracks. Added 2026-09-07: `AvoidanceAction.SLOW` (obstacle ahead but not
        near → `ACTION_SPEED_SCALE` 0.4) for anticipatory slowing. Sequence as an
        obstacle nears: NONE → SLOW → STOP / BACK_UP (dead ahead) or TURN
        (firmware, to a side). Calibrate the area→speed thresholds on hardware.
      - **Cliff/edge stop** — the `CLIFF` sim feature is built; the real-robot
        path needs the vision model trained to detect a desk edge (hardware-
        gated). Until then `CliffGuard` stays a hard reflex spec (B16).
      - **Tier B (a fresh vision-baked ~20M) is reserved** for *if* hardware
        shows the command-level reflex isn't fine enough — i.e. the robot still
        clips cables it can see, or the decel is too abrupt (within-stride,
        sub-command-timescale things a speed command can't express). Not
        justified pre-hardware: the obstacle-reward package measured ~neutral in
        isolation (Phase 0), and **Phase D (2026-09-08) confirmed it directly** —
        a from-scratch 20M with the terrain feature in the observation was no
        more capable than an identical blind 20M (same 0% falls, less obstacle
        anticipation, no regression). Vision-in-the-loop ruled out; the `Avoider`
        speed reflex is the path. Report:
        `claude.ai/code/artifact/bfb58d90-71ca-4681-9c72-d14e15e56b7a`.
      - Built + kept dormant for a future Tier B run: `G2E_TERRAIN_FEATURE` /
        `GOAL_MODE` / `CLIFF` / `TURN_BLEND`, `run20m_graft28x`, `benchmark_goal.py`.
      - **Phase E (2026-09-08) — vision picks a SCRIPTED skill on the frozen
        walk. IMPLEMENTED, hardware-gated.** No training: `run20m_ppo` stays
        frozen; a vision reading selects a `GaitMode` (cruise / careful /
        step-over / back-out / brace / inspect / halt) and `SkillSwitch` plays a
        scripted OpenCat keyframe with a phase-gated via-stance blend. Sim
        results (0 training): +48% through low obstacles (step-over attributed),
        0% vs 34% edge-falls with `CliffGuard`. `smoke_vfix3` (a fresh 3M
        vision-conditioned run with the Phase D fixes) confirmed learned
        vision-in-the-policy is a dead end a second way (it stalls). next-1..5
        done: high-step A/B (trot kept), `INSPECT` + near blind zone, per-ray
        slope grounding, `BRACE`, deployment wiring. Stack:
        `pi_pipeline/gait/skill_layer.py` (`SkillLayer` = `GaitSelector` +
        `SkillSwitch` + `CliffGuard`), `run_gait.py --skills` (serial Grove
        Vision AI feed or mock). Walk-around maneuver **can't be scripted** —
        no lateral leg DOF; a detour needs a firmware turn (nav-layer decision).
        Report: `claude.ai/code/artifact/88ea1a14-ab32-4000-8e87-422264667150`.
        Plan: `docs/rl/vision-in-gait.md` (`>>> RESUME (Phase E)`).
        The adapter skill probe (`docs/rl/adapter-skill-probe-spec.md`)
        stays the route for *one* genuinely-learned skill if a scripted one
        proves too fragile on hardware.

      --- superseded plan (2026-09-03), kept for context ---
      The current gait is reactive and IMU-only, so it can't anticipate terrain
      or deliberately step around an obstacle — it only learns a lip exists
      *after* a foot hits it (2026-09-03 probe batch: never falls but *stalls*
      against curbs / lips / on carpet, blind forward).

      **DECIDED ARCHITECTURE (2026-09-03) — NOT ADOPTED:** the walk policy gets **its own
      low-bandwidth forward terrain feature, fed directly into its 278-d
      observation at control rate**, *separate from* the vision→Claude /
      vision→`Avoider` command-setting path. Not "vision biases the command" —
      that keeps the policy blind and caps it at "creep on command"; Claude is
      also far too slow (seconds/call) for foot-placement timescale. Instead:
      - An **on-Pi module** turns the camera's detection stream into a compact
        feature and appends it to the policy observation. **Frozen layout** (4
        floats, `[-1,1]`), refreshed at detection rate (~10–30 Hz), held stale
        between frames:
        `[ present, dist_norm, bearing_norm, tall_flag ]` —
        seen-or-not, distance/range, angle-off-heading/half-FOV, and
        low-enough-to-step vs go-around/stop.
        Sim generator: `opencat_gym_env._scan_terrain` (a forward ray fan, gated
        by `TERRAIN_FEATURE`, off by default so `run20m_ppo` is unaffected).
        Pi generator: `pi_pipeline/vision/terrain_feature.py` (`terrain_feature()`
        + `TerrainFeatureExtractor`), from the detection `Frame`. **Both ends
        must stay in sync** — the plumbing (both sides + tests) landed
        2026-09-03; the constants get calibrated on hardware.
      - Claude stays *above* this loop (navigation goals, narration); the
        `Avoider` reflex may still set coarse speed/yaw commands in parallel.
        The terrain feature and the command path are independent inputs.
      - **Sim training:** synthesize that same feature from PyBullet ground-truth
        obstacle geometry, with realistic detector noise / miss-rate / latency
        (tuned to the real model's measured stats, `sysid`-style), add it to the
        observation, and retrain. **Claude does not need to be in the sim** — it
        isn't in this loop; the loop is camera→feature→policy, all Pi-local, and
        Claude's high-level commands are already covered by the sim's command
        randomisation.
      - Expected payoff: anticipatory slowing / go-around / stop for *large*
        obstacles and curbs (camera + detector are good at these). Fine
        foot-placement over a 12–15 mm lip stays marginal — head-height forward
        camera + 192×192 detector is weak on small low-contrast terrain edges.
      - The **"don't stall" reward idea** (dense forward-progress term + sparse
        breakthrough bonus, `robustness-backlog.md` R-NOSTALL) is **deferred to
        here** — it only makes sense once the policy can see far enough ahead to
        slow *before* contact; on the blind policy it just produces frantic
        scrabbling, not intentional stepping.

      Only possible once perception exists; a distinct effort from the
      flat-ground gait.
- [ ] (Stretch, with vision + IMU in place) More robust self-righting — flip
      detection from the IMU plus a dedicated recovery policy (or the firmware
      skill for the cases it covers, a learned fallback for the rest). Ruled out
      as a pure reward-shaping target in Run 7; becomes incremental once the IMU
      is already feeding the policy. See
      [`docs/hardware/self-righting.md`](hardware/self-righting.md).

## Phase 9 — Memory system

**Status:** built and tested on the dev machine — `pi_pipeline/memory/`, wired
into the voice loop through the `Memory.recall` / `Memory.record` seam.

- [x] **Persistent store** — SQLite (`memory/data/g2_memory.db`, gitignored;
      stdlib `sqlite3`, inspectable, light for the Pi). Two kinds: an
      `exchanges` log (every turn, mirrored to an FTS5 index) and `facts` (short
      durable notes). Chose SQLite over plain JSON (retrieval wouldn't need a
      full load) and over a vector store (an embedding model/API per turn is too
      heavy/costly for v1).
- [x] **Retrieval** — `recall(user_text)` injects the current fact set plus up
      to `G2_MEMORY_RECALL` older exchanges that match the input (BM25 via FTS5),
      excluding the recent turns `conversation.py` still holds in-context. A
      `remember` tool lets G2 choose what facts to keep (no extra API call).
      Surfacing a fact bumps its `last_recalled`, so stale facts fall off the
      injected set once it hits `G2_MEMORY_MAX_FACTS` — a light decay without a
      scheduler.
- [x] **Kept separate** — Memory only touches the voice loop via one seam;
      nothing in movement or vision imports it.
- [ ] Semantic recall (embeddings) if FTS keyword matching feels too literal —
      weigh model/latency cost on the Pi first.
- [x] **Small web UI to browse / prune memory — BUILT 2026-09-10.**
      `pi_pipeline/memory/webui.py` (`python -m pi_pipeline.memory.webui`,
      stdlib `http.server`, no deps, binds 127.0.0.1): facts list with
      add / delete, searchable conversation log (FTS), a `recall()` preview,
      and a confirm-gated wipe. HTML-escaped. 8 tests (page render + a live
      server round-trip). The CLI still covers everything headless:
      `python -m pi_pipeline.memory {facts,log,search,recall,remember,forget,wipe}`.
- [ ] Exercise it across real multi-session conversations once the voice loop
      runs live (needs an API key / hardware) — and at that point re-check
      whether recall quality, the fact cap, and the decay ordering feel right on
      genuine history rather than test data.

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
  any gait run, not silently unlogged.
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
`run_gait --probe-imu` / firmware `c16` calibration own the serial link with
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

## When the hardware arrives — ordered bring-up

The phases above are grouped by system; this is the sequence to actually work
through once the Bittle X + BiBoard land (the Pi bring-up is already done — see
Phase 6). The camera arrived first and its bench bring-up is done (Phase 8).

**Assembly & mechanical**
1. Assemble Bittle X V2; check servo calibration (ships calibrated — fine-tune
   only if movement looks off).
2. **Weigh the final build** on a kitchen scale, with the Pi + PiSugar S + camera
   + mount actually on the robot. Weigh the **camera cluster and the PiSugar S
   battery separately** (the battery is >½ the current spine estimate; if it
   mounts somewhere distinct, it needs its own sim body). Balance each piece on
   an edge for height + fore/aft CoM. Then set `PAYLOAD_MASS_*` / `HEAD_MASS_*` /
   positions in `opencat_gym_env.py` and retrain (or `--finetune-lr`) if the
   delta from ~76 g is real — [`rl/hardware-gated-backlog.md`](rl/hardware-gated-backlog.md) **H2**.
3. **On the calibration stand, before it touches the ground:** full
   range-of-motion pass by hand / `check_serial` (watch for binding / leg-on-leg
   collision), then firmware `c16` auto joint calibration. Safe place for first
   power-on. Detailed gait steps: [`guides/gait-deployment.md`](guides/gait-deployment.md) step 6.
4. Wire Pi ↔ BiBoard **data-only** (RX/TX/GND); PiSugar S is the sole power
   source. Confirm the back cover still fits.

**Serial link (Phase 5)**
5. `python -m pi_pipeline.link.check_serial ports` → set `G2_SERIAL_PORT` in
   `.env` (likely `/dev/ttyS0` → `/dev/ttyAMA0` after `disable-bt`).
6. Enable Serial-2 on the BiBoard (`XS`, or edit `OpenCat.h` + reflash).
7. `check_serial ping` (firmware banner) → `send kbalance` (robot stands) →
   `skills` (runs the conversational set).

**Voice (Phase 7)**
8. `python -m pi_pipeline.voice --mode text` → Claude + memory end-to-end (key is
   already set).
9. `check_audio wake` / `stt` on the Pi's mic → tune `G2_WAKE_WORD`,
   `G2_STT_SILENCE_S`. `--mode voice --actuator serial` for the full loop.
10. `benchmark_pi.py` on the actual Pi — confirm `en_US-ryan-low` + Vosk hit
    real-time on 512 MB. If sluggish: shorter `CLAUDE_MAX_TOKENS`, streaming TTS,
    a longer "thinking" cue.

**RL sim-to-real (Phase 6 — stack already built + sim-validated)**
11. `pi_pipeline/gait/bench_real.py` — real-time joint control on the Pi (sim
    bench: 0.43 ms/step).
12. `run_gait.py --probe-imu` → `--openloop` (verify servo signs) → `--cmd` (the
    learned gait) → **the H1 head-to-head** vs firmware `kwkF`. Methodology +
    decision rule: [`rl/h1-rubric.md`](rl/h1-rubric.md); `h1_score.py` produces the verdict.

**Vision on the robot (Phase 8)**
13. Mount the camera on G2, train the **desk-edge classifier** on the real
    mounted POV (B16 — highest priority), wire `Avoider` decisions to the
    actuator, build the `CliffGuard` reflex against the trained classifier.

**Integration (Phase 10)**
14. Voice + vision + memory concurrently; resolve timing/resource conflicts
    (historically the messiest phase). Then revisit locomotion with perception in
    the loop toward the Phase 8 Target capability.

---

## Known risks / honest expectations

- Hardware debugging is a different skill than web debugging — no stack traces; a
  fault could be code, wiring, power, or the hardware itself.
- RL gaits will look rougher than an animal's, especially early.
- Sim-to-real rarely works on the first deploy — expect a gap and iteration.
- Full integration (Phase 10) is the hardest, messiest part.

## Reference: how OpenCat gaits are structured

From `PetoiCamp/OpenCat` (AVR/NyBoard) and `PetoiCamp/OpenCatEsp32` (ESP32/BiBoard
— the actual Bittle X firmware). Background for Phase 3 (contrast with the RL
approach) and Phase 5 (sending commands).

- Every named skill (walk, trot, crawl, sit, kick, …) is a **hand-authored
  keyframe animation** — a compact `const int8_t[] PROGMEM` array of servo angles,
  one per skill, in flash. `InstinctBittleESP.h` defines ~93 of them.
- Two parallel arrays connect it: `skillNameWithType[]` (e.g. `"wkFI"`, `"trFI"`,
  `"sitI"` — trailing `I`/`N` = Instinct/built-in vs. Newbility/user-taught) and
  `progmemPointer[]` (pointer to each skill's frames). A serial command like
  `kwkF` looks up the name and plays its frames.
- Each array's header encodes frame count/period and a direction/type flag. A
  positive period is a **looping gait** (walk, trot — cycled continuously, blended
  in real time with IMU balance correction via `gyroBalanceQ`); a negative period
  is a **one-shot behavior** (sit, push-up — some wait on an IMU trigger angle
  mid-sequence).
- 16 servo channels total: 4 for head/tail/gripper, 12 for the legs — 8 of those
  (shoulder + knee ×4) are `WALKING_DOF`, the joints gait keyframes drive.
- **Why it matters here:** this is the opposite of the RL approach. The trained
  policy needs its own runtime path to drive the same 8 walking servos — either
  bypassing the skill-array system or injecting learned frames in the same format
  — rather than selecting from `skillNameWithType`.

## Community & support

- r/petoi (Reddit) — Petoi's recommended community
- Petoi Forum Archive (petoi.camp)
- `github.com/PetoiCamp/OpenCat` — firmware source
- `github.com/PetoiCamp/NonCodeFiles` — community 3D-print files
- `github.com/ger01d/opencat-gym` — the RL training environment
