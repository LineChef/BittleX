# Phase 3 — RL training in simulation (detail)

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> Phase 3 (RL training in simulation). Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

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
  [`docs/rl/gait-benchmark.md`](../rl/gait-benchmark.md)): on flat ground the learned
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
  [`docs/rl/refinement-regimen.md`](../rl/refinement-regimen.md),
  [`docs/rl/phase4-decision-log.md`](../rl/phase4-decision-log.md).
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
  live in [`docs/rl/hardware-gated-backlog.md`](../rl/hardware-gated-backlog.md),
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
    asymmetry, …): [`docs/rl/robustness-backlog.md`](../rl/robustness-backlog.md).

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

  **Update 2026-09-18 — frozen base promoted to `run20m_resid30_ppo`; three
  campaigns running.** (Note: the detailed day-to-day between 2026-09-05 and
  this entry lives in the dated `docs/rl/*.md` logs, not backfilled here —
  this is a rollup of today specifically.)
  - **`RESIDUAL_SCALE_DEG` widened 22 -> 30** (fresh 20M run, `run20m_resid30_ppo`),
    full Stage 3 benchmark suite run against the prior `run20m_ppo` base
    (decathlon, gaits-vs-scripted, recovery probe, action-trace, leg-tinting
    replays — published report). Close overall, but resid30 wins decisively
    within the trained envelope (tighter trot symmetry, comparable-or-better
    speed everywhere, wider margin over scripted) while using *less* residual
    budget doing it; the one real cost is a new failure at steep descents
    beyond the training slope ceiling (T9.2, mirrors and was traded for fixing
    the prior T9.1 up-slope failure). **User's call: promoted to the new
    frozen base** — `CLAUDE.md`'s RL-training section and
    [`docs/rl/resid30-log.md`](../rl/resid30-log.md) have the full report and
    reasoning; `run20m_ppo` kept in `trained/` as the prior-base reference
    point, not deleted.
  - **Gait-friction campaign** (why the residual spends ~4-8deg even on calm
    flat ground): amplitude-scaling the reference pose by commanded speed
    tried and **reverted after two rounds**, both clear regressions (residual
    usage roughly doubled, then still ~1.5x worse even with a much narrower
    clip range) — full diagnosis in
    [`docs/rl/gait-friction-log.md`](../rl/gait-friction-log.md). Investigated
    and downgraded a cadence-recalibration alternative before writing any
    code (the open-loop speed gap turned out to depend heavily on
    per-episode randomized friction/payload, not fixable by a static
    correction curve). Current primary fix, training now: `FAC_RESID_CALM_BONUS`,
    a tilt-gated (continuous ramp, not a hard threshold — an earlier hard
    cutoff on this same signal already caused PPO divergence once,
    `IMITATION_FADE_FACTOR`'s Phase 4b history) extra residual-cost weight
    specifically while the robot is stable, designed to avoid punishing
    reactions to genuine stumbles.
  - **Resiliency campaign**: reframed around the R-series backlog's finding
    that *stalling*, not falling, is this gait's dominant real-world failure
    mode. Built and smoke-tested four new probe scripts (IMU bias, within-
    episode latency/thermal ramp, aggressive command transitions, a
    RUBBLE/LEDGE/STUCK_FOOT/JOINT_OFFSET dose-response sweep) — full detail
    in [`docs/rl/resiliency-log.md`](../rl/resiliency-log.md). Ledge step-down
    investigated in depth (confirmed via direct contact-point check and
    visual replay it's a real destabilization, not a "foot finds nothing"
    pit; found the recoverable band, ~24-27mm, vs. saturated failure at
    30mm+) and gated: ledge-recovery training only proceeds *after*
    `FAC_NOSTALL` (the designed anti-stalling fix, still unlaunched) shows a
    real, measured reduction in stalling — Phase 4a already showed training
    ledge exposure without that fix in place makes things worse ("backs
    away from steps").
  - **Researched, deliberately not pursued:** continuous proprioceptive
    "feel the ground" blind climbing — the successful literature (ANYmal
    and others) depends on real-time joint-torque sensing G2 doesn't have;
    the confirmed servo position-feedback on the ordered hardware is too
    slow and PWM-disruptive for control-rate use. A narrower, genuinely
    buildable version — slow, deliberate probe-before-committing (not
    continuous locomotion) — logged as a real backlog item under
    [B13](../behavior-ideas.md) instead, sim-testable now without hardware.

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
BiBoard-V1 IR trigger — [`docs/hardware/self-righting.md`](../hardware/self-righting.md).

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
  [`docs/hardware/specs.md`](../hardware/specs.md).
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
