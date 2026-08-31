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

### Resolved

- **Pi power: independent, via PiSugar S 1200 mAh.** Drawing the Pi from Bittle's
  shared battery causes "reduced motion capability" (Petoi's own docs) and risks
  servo-spike brownouts. The PiSugar pogo-pins to the Pi's underside pads, leaving
  the GPIO header free, and provides UPS safe-shutdown. To avoid two 5 V sources,
  wire BiBoard → Pi **data-only (RX/TX/GND)**, no 5 V. Full reasoning:
  [`docs/pi-power.md`](pi-power.md).
- **Enclosure:** Petoi ships an official back-cover STL with a Pi cutout
  ([`Bittle_Cover_with_hole_for_Pi.stl`](https://github.com/PetoiCamp/NonCodeFiles/blob/master/stl/Bittle%20%26%20BittleX/BittleCover/Bittle_Cover_with_hole_for_Pi.stl)),
  so the cover can close over the mounted Pi.
- **BiBoard V1 MCU:** standard **ESP32-U4WDH** (Xtensa dual-core LX6, via an
  ESP32-MINI-1 module), not an S3/C3. This is why Phase 8 sends structured
  detection results over serial rather than streaming raw frames.

### Open (check when hardware arrives)

- Confirm BiBoard V2 can be wired data-only, or whether its mount ties 5 V to the
  data lines by default.
- BiBoard V1's spec lists Pi compatibility as "Pi 3A+, 4, 5" — the Pi Zero 2 WH
  isn't listed. Verify the 5-pin socket and serial wiring are compatible.
- Confirm the back cover fits once the Pi is mounted.

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
  [`docs/gait-benchmark.md`](gait-benchmark.md)): on flat ground the learned
  gaits win — `phase3-gait` covers ~4× the distance of open-loop `wkF` keyframes.
  On obstacle courses the scripted keyframes are hard to beat; `phase3-gait` does
  markedly worse (brittle, trips), `gait-v7-stumble-catch` only reaches parity.
  RL earns its place for flat efficiency, not (yet) for obstacle robustness. The
  scripted side is open-loop only here — the firmware's gyro-balance layer would
  widen its obstacle lead — so confirm on hardware.
- **Phase 3 RL is paused pending hardware.** The open question — is a learned gait
  actually better than OpenCat's scripted `wkF` for plain walking — has a sim
  answer above; the real-robot head-to-head confirms it against the *firmware*
  gait. Learned-gait work resumes if it transfers well and/or when
  perception-in-the-loop becomes active — see the
  **Phase 8 Target capability**, the near-term goal for that work.

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

### Training history

Runs are 2M steps unless noted, ~35–40 min wall time each on this machine.
Reward-shaping constants are the `FAC_*` module-level values in
`opencat_gym_env.py`.

**v1 — baseline.** Reward peaked ~900 mid-run, then collapsed in the final third
(down to ~25) with `approx_kl`/`clip_fraction` spiking. Cause: `PENALTY_STEPS =
2e6` equalled total training length, so the stability/smoothness penalty was
still ramping when the run ended, and the fixed learning rate turned the forced
late correction into a violent jump.

**v1 continuation.** Trained 2M more steps under the now-fully-ramped penalty;
reward recovered to ~331 with full-length episodes — confirming the diagnosis. A
lone `approx_kl` spike (22.8) near the very end was noted but not understood.
Visual replay: farther travel, but legs jittering/sliding rather than stepping,
and a rightward curve ending in a fall.

**v2 — anti-slip / clearance / yaw.** `FAC_SLIP` 0→0.01, `FAC_CLEARANCE` 0→0.1,
new `FAC_YAW = 0.1` (from the previously-unused yaw rate; not added to the
observation). No violent collapse this time, but reward declined from a ~900 peak
to ~490. Visual: much closer to real walking, front-right foot over-lifting late
in the episode.

**Adopted from [`bmabsout/opencat-gym`](https://github.com/bmabsout/opencat-gym)**
(an active fork that independently removed time-varying reward ramps, validating
the `PENALTY_STEPS` diagnosis):

- `FAC_JITTER = 0.2` — penalizes joints reversing direction frame-to-frame,
  targeting shuffle more directly than `FAC_SMOOTH_1/2`.
- Cyclical time/phase observation input (`TIME_PHASE_PERIOD = 100`) — a rhythmic
  clock to help the policy learn periodic gaits (observation 246 → 247).
- Periodic checkpointing — `train.py`/`continue_train.py` now save every ~200K
  steps to `trained/checkpoints/`, so an interruption costs one checkpoint, not
  the whole run.
- Not adopted (bigger redesigns): soft-min reward aggregation,
  gravity-vector observation, dropping joint history.

**v3 — jitter + phase input.** Stopped early, superseded by v4 (no checkpoint
existed yet). The pause added a diagonal-trot goal: could a gait-symmetry reward,
or bootstrapping from Bittle's built-in `wkF` walk keyframes, produce a real trot
faster than pure RL exploration? A lightweight reward term was chosen to try
first; the scripted-gait bootstrap and a CPG action-space redesign were deferred.

**Gait-symmetry reward — `FAC_GAIT_SYMMETRY = 2.0`.** Rewards `−(diagonal_a ·
diagonal_b)` where `diagonal_a` = front-right + back-left joint-angle deltas,
`diagonal_b` = front-left + back-right — positive when the diagonal pairs move
in opposition (a trot). Verified in PyBullet first: all 8 walking joints share
the same sign convention in the URDF, so "same sign of angle change" genuinely
means "in phase," no mirroring needed. Applied **unramped** (full strength from
step 1), so it shapes gait structure before the policy can lock into a different
pattern.

**v4 — + gait symmetry.** First run with anti-jitter + phase input + gait
symmetry together. Reward peaked ~1010, then hit the same collapse signature as
v1 (`approx_kl` 26.9, `clip_fraction` 0.91, reward → ~0.4) at 73% through
training. **Same failure despite a completely different reward function** — so
the cause is structural, not any one term.

**Root cause (across v1–v4).** Two issues, both unaddressed since v1:

1. `PENALTY_STEPS = 2e6` had equalled total training length every run — the
   penalty continuously reshaped the reward landscape for the whole run (v4's
   spike at 73%, not 100%, shows continuous pressure, not just an endgame
   effect).
2. Fixed learning rate (`3e-4`) and clip range (`0.2`) never decayed. Standard
   PPO practice decays them to prevent destabilizing updates once the policy has
   converged and its action noise has shrunk.

**Fixes for v5:** `PENALTY_STEPS` 2e6 → **5e5** (full strength at 25% of a 2M
run), and a linear learning-rate decay in `train.py` (`linear_schedule(3e-4)` →
~0 by the end). Clip-range decay was left as a fallback.

**v5 — the fix worked.** Reward climbed smoothly and monotonically from ~47 to
**~1100** (highest yet, stable), full-length episodes throughout, `approx_kl` and
`clip_fraction` *decreasing* toward the end. Confirms the root-cause diagnosis.
Visual: faster, but all four legs take small shuffling steps rather than real
strides. Likely a reward-shape effect — `PAW_Z_TARGET = 0.005` barely rewards a
lift, `FAC_SMOOTH_1/2` penalize movement magnitude, and a fall ends the episode,
so many small "safe" steps are locally optimal.

**v6 — bigger steps.** `PAW_Z_TARGET` 5 → **15 mm**, `FAC_SMOOTH_1/2` 1.0 → **0.5**,
plus per-term reward logging in `step()`'s `info` dict (`r_movement`,
`r_gait_symmetry`, …) so behavior changes trace to a specific term. Tagged
`gait-v6-known-good`: ep_rew ~1220, clean convergence, best gait so far —
reasonable diagonal trot — but curves slightly right by the end.

**Tooling (v6 era).** `start_run.sh <tag>` — one-command launcher with the pre-run
checklist (no stacked runs, warns about lingering viewers, starts TensorBoard,
backgrounds training). `train.py` takes `--tag` and `--steps`. Shell helpers
`g2train` / `g2watch`; the `/train` slash command.

**Automated loop 1 — fix the rightward curve.** First unattended run of the
[`docs/automated-testing-loop.md`](automated-testing-loop.md) workflow, on
`auto-gait-iteration`. Added `evaluate_policy.py` (headless metrics + frame
renders). Five 1M-step tuning iterations + one 2M confirming run. Three changes
from v6: **`FAC_HEADING = 5.0`** (penalize accumulated heading error from the
quaternion, not just yaw rate — this fixed the curve), **`PAW_Z_TARGET` 15 → 20 mm**
(stop the back feet dragging once heading control made the gait front-heavy),
**`FAC_GAIT_SYMMETRY` 2.0 → 3.5**. Result `auto_gait_final` vs v6: end-of-episode
heading drift **12.5° → 0.16°**, lateral wander **0.24 → 0.045 m**, speed held,
never falls. Known miss: `diagonal_trot_corr` −0.59 at 2M (the 1M checkpoints hit
−0.90 — the fully-converged policy walks straight but its diagonal timing
loosens). Merged to `development`; write-ups in
[`docs/auto-iteration-report-2026-08-30.md`](auto-iteration-report-2026-08-30.md)
and [`docs/auto-iteration-log.md`](auto-iteration-log.md).

**Automated loops 2–4 + a final run — set aside.** Attempts to fix a supposed
start-up "stutter" and tighten the trot. The stutter turned out to be a
measurement artifact (baseline evaluated in a mismatched env; real
`startup_speed_ratio` ≈ 0.84, fine). Every trot attempt — `FAC_GAIT_SYMMETRY`
weight tuning, a decay ramp, a phase-locked reformulation, a stride-length
reward — either dissolved the trot or regressed heading/stride at 2M
convergence. **Conclusion: `auto_gait_final` sits at a local optimum that
reward-weight tuning cannot push past.** Records:
`docs/auto-iteration-{log,report-*}-run{2,3,4}.md`,
`docs/auto-iteration-log-final.md` (reformulated terms live only on
`auto-gait-iteration`). Remaining trot-crispness levers are structural
(diagonal-pair phase in the observation, `wkF` imitation, or a CPG action space).

**Run 5 — domain randomization + `wkF` imitation** (merged to `development`).
Wired up the previously-dead DR knobs — per-episode friction, link-mass, and IMU-
noise randomization, random shoves, scattered obstacle boxes — behind a curriculum
ramp. Added a DeepMimic-style imitation reward (`FAC_IMITATION`) that matches
Bittle's built-in `wkF` walk keyframes phase by phase (`reference_gait/`,
extracted from `InstinctBittleESP.h`, open-loop verified). The imitation reward is
what finally produced a real diagonal trot that weight tuning alone could not.
Also added `evaluate_policy.py --dr-*` held-out scenario flags.

**Run 6 — fall recovery / self-righting** (6 rounds, unattended, on
`auto-gait-iteration`). **Key finding: a Bittle cannot self-right from a full
tip-over (> 1.3 rad) — it has no roll-axis actuation, a missing degree of
freedom.** An escalating recovery reward (weight 8 → 22, denser shaping, eased
criteria, pushes suspended while down, actuator torque boosted) converged at 0%
recovered every time. The loop pivoted to the learnable version — *catching a
stumble before it becomes a fall* — via `FAC_BALANCE`, an always-on reward for
driving body tilt back toward level while wobbling. Winner **`auto_rec_r5_ppo`,
tag `gait-v7-stumble-catch`**: `diagonal_trot_corr` −0.58 (crispest in the
project), max yaw drift 7.6°, no obstacle-course falls; ~7% slower forward than
`phase3-gait`. The recovery-window code stays in `opencat_gym_env.py` but dormant
(`FAC_RECOVERY = 0`). Merged to `development`. Records:
[`docs/auto-iteration-log-run6.md`](auto-iteration-log-run6.md),
[`docs/auto-iteration-report-2026-08-31.md`](auto-iteration-report-2026-08-31.md).

Note this is the *RL-policy* limit (8 walking joints only). OpenCat's **firmware**
has a separate built-in scripted self-right skill — but it only covers slow
side/forward falls, not fast ones and not a flip onto the back, and its usual
trigger (the IR remote) isn't supported on BiBoard V1. Details, sources, and the
plug-in points: [`docs/self-righting-research.md`](self-righting-research.md).
Expect frequent manual righting during real-robot RL sessions.

**Run 7 — "walk": target speed + stumble recovery** (closed, on
`auto-gait-iteration`). Added a deliberate `TARGET_SPEED` (0.11 m/s) with a
tracking-bonus reward, IMU tilt history + angular acceleration in the observation
(247 → 273), and several attempts to improve stumble recovery (a tilt-slowed
phase clock, imitation-fade while wobbling, tilt-rate damping in `FAC_BALANCE`,
concentrated impulse drills). **Outcome:** `big_stumble_recovery_rate` stayed at
0.0 across all three rounds — recovery is bounded by the control setup (reactive,
IMU-only, weak sagittal-plane legs), not by reward tuning, confirming Run 6.
`walk_r2` is the best checkpoint (tag `walk-v8-r2`): 0% falls on flat ground and
the 30 mm course, best heading of the project (4–5° max yaw drift), trot −0.50 —
but it converges slow (~0.07 m/s vs the 0.11 target) and is not merged to
`development`. **Decision:** stop reward-tuning recovery; settle the RL-vs-scripted
question on real hardware with a head-to-head once it arrives. Record:
[`docs/auto-iteration-log-run7.md`](auto-iteration-log-run7.md).

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
- Imitation-learning approaches from the UVA/Harvard Bittle research (stretch,
  optional).
- **Reactive obstacle purchase:** teach the policy that when a front foot is
  blocked it should lift higher to get on top. Learnable in sim but needs
  per-foot contact/height in the observation, which the real Bittle can't sense —
  so it wouldn't transfer. The transferable version is a taller-obstacle
  curriculum plus a loose/decaying imitation weight, for a generally higher,
  more adaptive swing. Revisit after the reactive-robustness gait is solid.

## Phase 4 — Hardware assembly

- [ ] Assemble Bittle X V2 (~40–90 min).
- [ ] Check servo calibration — pre-assembled units ship calibrated, so this is a
      check/fine-tune, not an assumed step. Only dig in if movement looks off.
- [ ] Get it moving on stock firmware first, before any custom code.
- [ ] Set up the Pi Zero 2 WH: pre-configure Wi-Fi + SSH in Raspberry Pi Imager
      (headless), confirm SSH access.
- [ ] Mount the Pi; test power and serial **independently** (power can work while
      serial doesn't). Per Petoi's Raspberry Pi serial docs:
  - Power the Pi from the PiSugar S, not the BiBoard. Wire BiBoard → Pi
    data-only (RX/TX/GND), Pi 5 V unconnected. See [`docs/pi-power.md`](pi-power.md).
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
- [ ] Test the vision module's on-device detection via the SenseCraft AI Model
      Assistant web debug GUI.

## Phase 6 — RL sim-to-real deployment

- [ ] Deploy the Phase 3 policy to the real robot. Mechanism:
      [`ger01d/opencat-gym-sim2real`](https://github.com/ger01d/opencat-gym-sim2real)
      — flash modified BiBoard firmware
      ([`ger01d/OpenCatEsp32-sim2real`](https://github.com/ger01d/OpenCatEsp32-sim2real))
      that takes joint commands over serial, then run an inference loop on a
      connected computer streaming the policy's output. The author calls this
      "still highly experimental."
  - **Open question:** the policy needs PyTorch for inference and was designed to
    run "on a computer," not the ESP32. The plan has the mounted Pi Zero 2 WH
    (512 MB RAM, weak quad-core A53) doing this. **Whether a Pi Zero 2 WH can run
    `model.predict()` fast enough for real-time joint control is untested** —
    benchmark it (load the policy, time `predict()`) once the Pi is up (Phase 4),
    before writing it into the runtime.
- [ ] Expect a real sim-to-real performance gap — normal, not failure.
- [ ] Iterate: adjust the reward and/or retrain in sim based on real-hardware
      behavior, redeploy.
- [ ] Find and test the **self-right trigger command** for BiBoard V1 (the IR
      remote path doesn't apply — likely a serial command). Add it to
      `pi_pipeline/link/opencat.py`. Falls will be frequent during RL sessions
      and the firmware skill only covers slow side/forward ones — see
      [`docs/self-righting-research.md`](self-righting-research.md).

## Phase 7 — Voice + Claude integration

**Status:** the pipeline is scaffolded and runs end-to-end on a dev machine in
text mode — `pi_pipeline/voice/` (own venv, `pi_pipeline/requirements.txt`).
`wake → STT → Claude → TTS → skill` with every hardware-specific stage behind an
interface (`MockActuator`/`SerialActuator`, `MacTTS`/`PiperTTS`,
`TextSTT`/`VoskSTT`, `AlwaysAwake`/`VoskWakeWord`). Claude replies parsed into
spoken text + `perform_skill` tool calls; a curated OpenCat skill catalogue maps
to serial commands. Offline tests cover the parse path. Remaining items below are
the audio backends (deps + models) and everything hardware.

- [x] **Config-driven Claude client** — `pi_pipeline/config.py` (env: key, model,
      max tokens, timeout, history depth, persona) + `voice/conversation.py`
      (rolling history, retry-on-timeout, memory seam for Phase 9).
- [x] **Response → spoken text + action commands** — `perform_skill` tool;
      `voice/skills.py` maps skill names to OpenCat `k<token>` serial commands;
      one reply can both talk and move.
- [x] **State-cue interface** — `voice/cues.py` (`LogCue` now; buzzer/posture
      later).
- [ ] Audio capture on the Pi (Bittle's onboard mic). `voice/stt.py` /
      `wake_word.py` use `sounddevice`; test on real mic hardware.
- [ ] Speech-to-text — Vosk small English model for both wake word and full STT
      (`requirements-audio.txt` + model download in `voice/README.md`). Confirm
      it's light enough on the Pi Zero 2 WH; from similar Pi-based LLM voice
      robots (SunFounder PiDog docs, `marceld23/Ai-Robo-Dog`,
      `rockywuest/pidog-embodiment` — all Pi 4/5 with 2 GB+, so directional):
  - Wake-word gate so full STT / network calls only fire on activation.
  - Local TTS (Piper `en_US-ryan-low`) — `PiperTTS` implemented; needs the model.
  - Health-monitor / auto-restart the audio + serial threads once they're real
    (pidog-embodiment logs worker threads dying silently).
  - Bookworm's PEP 668 blocks plain `pip install` on-device — use the venv.
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

- **Hardware constraint:** Bittle X has one module slot, taken by the AI Vision
  Camera. A separate proximity/distance sensor is not an option alongside it — so
  cliff/edge detection, if pursued, must be a camera-based visual classifier
  (SenseCraft-trained "floor" vs. "edge ahead"), not a dedicated sensor.
- [x] **Obstacle-avoidance reflex** — `vision/avoidance.py`. Local, no network;
      box `area` as the closeness proxy, bearing from `center_x`; consecutive-
      frame debounce + cooldown, with `STOP`/`BACK_UP` preempting. Thresholds
      (`AvoiderConfig`) need tuning against real detections + the robot's
      stopping distance.
- [x] **Camera→Pi serial format confirmed** (SSCMA AT protocol): JSON lines,
      921600 baud, `{"name":"INVOKE","data":{"boxes":[[x,y,w,h,score,target_id]]}}`
      — box centre + size in model-input pixels, score 0–100, numeric class id
      (labels set out-of-band via `VISION_LABELS`). `SerialDetectionFeed` parses
      it; `Detection.from_center_px()` normalises. Verify centre-vs-corner and
      the pixel frame size on a live module.
- [ ] Train a custom SenseCraft detection model (cables, small objects, table
      edges); record its label list + input size and the deploy workflow.
- [ ] Cliff/edge avoidance (don't walk off a table) — the RL walking policy
      can't learn this (no forward-looking perception), so it needs forward
      sensing + a reflexive stop, kept local. Camera-based classification will be
      less reliable than a physical sensor (lighting/surface sensitive, needs the
      right camera angle) and a failure means a fall, so approach with caution.
      Not yet scheduled.
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
- [ ] **After vision works, revisit the locomotion policy with perception in the
      loop — toward the Target capability above.** Run 5–7 terrain training is
      reactive and IMU-only, so the policy can't anticipate terrain or
      deliberately step around an obstacle. Feed forward obstacle/detection
      information into the policy's observation and retrain (or add a perception
      front-end that biases the existing gait) for anticipatory foot placement
      and step-over / go-around / stop decisions. This is what a scripted keyframe
      gait fundamentally can't do — it has no input to feed vision into — and is
      the main reason the project uses RL for locomotion. Only possible once
      perception exists; a distinct effort from the flat-ground gait.
- [ ] (Stretch, with vision + IMU in place) More robust self-righting — flip
      detection from the IMU plus a dedicated recovery policy (or the firmware
      skill for the cases it covers, a learned fallback for the rest). Ruled out
      as a pure reward-shaping target in Run 7; becomes incremental once the IMU
      is already feeding the policy. See
      [`docs/self-righting-research.md`](self-righting-research.md).

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
- [ ] Small web UI to browse / prune memory (per the plan) — a ~100-line
      single-file app over the existing `Store`: facts list with add/edit/delete,
      searchable conversation log, a `recall()` preview, a wipe button.
      **Deferred: revisit once real multi-session use has accumulated enough
      history to make browsing/pruning worthwhile.** The CLI covers every
      function meanwhile: `python -m pi_pipeline.memory
      {facts,log,search,recall,remember,forget,wipe}`.
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
