# hw1 — training under G2's real control path

> **2026-10-01:** the deployed policy (`DEFAULT_POLICY`) is now `Release_CandidateV2.1` (see Round 4 below), exported with a `cmd_send_every_n: 3` sidecar. `hw1_20m` remains on the Pi as a baseline.

**2026-09-22 → 23.** Started as the "IMU feedback rate" priority (stock firmware
prints orientation at 5 Hz, the policy runs at 80 Hz). Tracing it through the
firmware turned up a bigger gap in the joint-command path, two benchmark bugs,
and several smaller sim-vs-hardware mismatches. Outcome: a gait trained under a
model of the real control path, `hw1_20m`, is the release candidate.

## What the hardware actually does (traced from OpenCatEsp32 source, 2026-09-08)

- **IMU:** `imu.h` `print6Axis()` returns early unless 200 ms have passed
  (`PRINT6AXIS_MIN_INTERVAL`) — a **5 Hz** ceiling on every call site. The
  `MCU:`/`ICM:` line carries accel + yaw/pitch/roll, **no angular rate**.
  Details: [`hardware/petoi-firmware-reference.md`](../hardware/petoi-firmware-reference.md).
- **Joint commands:** `m` (`T_INDEXED_SEQUENTIAL_ASC`) moves the listed joints
  **one at a time** (1° per 8 ms each, +10 ms per joint) — ≥144 ms per 8-joint
  command against the 12.5 ms control tick. `i` (`T_INDEXED_SIMULTANEOUS_ASC`)
  moves them together, eased at 2° per 8 ms (~250°/s cap; the walk needs up to
  ~420°/s). No serial command changes that easing (`transformSpeed`).
- **Backlog:** `read_serial()` slurps every waiting byte and the newline strip
  keeps only the **oldest** command — a slow command format means lag plus
  skipped targets.
- **Balance mode:** bare `g` *toggles* gyro balance; with balance on, the
  firmware also runs its own lifted / fall / push reflex skills over whatever the
  Pi commands. Use `gb` (off) / `gB` (on).

## Sim measurements

| Probe | Result |
|---|---|
| `resilience_imu_rate.py` — 5 Hz held orientation, no rate, vs the 80 Hz training condition (7 hard cells × 40 eps) | No measurable cost: 107 vs 111 falls / 280 |
| `resilience_joint_cmd.py` — `firmware_model.py` timing between policy and servos (8 cells × 20 eps) | `m`: G2 doesn't walk (~0 m/s, 2 % of commands run, ~650 ms lag). `i`: ~96 % of ideal speed, ~55 ms lag, ~9° joint error. `i` with `transformSpeed` 0 (firmware change): ≈ ideal |

The run20m checkpoints need `G2E_RESIDUAL_SCALE_DEG=22` (env default 30 since
resid30); both probes and `validate_deploy.py` now take the scale from the
policy's sidecar (below).

## Code fixes (pi_pipeline)

1. `run_gait.py` blocked on `readline` every tick → the whole loop (policy,
   phase, joint commands) ran at the 5 Hz IMU print rate. Now polls
   (`SerialLink.poll_imu()`, non-blocking; IMU lines split out of command
   replies) and steps on the held frame; stops if no frame for 0.6 s.
2. `SensorHub` read the parser's always-zero gyro → `imu_stable` always True,
   `held` could never fire. Rate now from frame-to-frame differences
   (`imu_parse.ImuFeed`).
3. Nothing sent `gP` in app mode → `SensorHub` sat on its "level and stable"
   fallback forever. The app now starts/stops the stream.
4. `LockedLink.read_line()` held the shared serial lock for up to 1 s per
   `SensorHub` tick — could delay an emergency stop.
5. Gait sends `i`, not `m`. Balance off is `gb` (restored with `gB` on exit).
   Yaw rebased to 0 at gait start (no magnetometer; sim shows the policy
   ignores yaw anyway).
6. `JamGuard` judges each front joint against the range its recent commands
   swept (the `i` lag isn't a jam), accepts sparse feedback reads, and decides
   per joint over a window. Sim: 0 false fires in 18 episodes; a wall did not
   produce a strain signal (legs keep tracking, body slides) — bench question.
7. The residual scale travels with the policy: `export_onnx.py` writes
   `<policy>.onnx.json`; `residual_policy.py` reads it (legacy 22 without one).

## Benchmark bugs (`benchmark_decathlon.py` / `benchmark_gaits.py`)

- **Scripted baseline wasn't the scripted walk.** In residual mode,
  `ScriptedGait`'s absolute-mode action was applied as a residual — ~7.5° mean,
  22° max off `wkF`. Now a zero residual = exactly `wkF`.
- **Cell knobs leaked.** The bare-robot cells' `PAYLOAD_PROB=0` carried into
  every later cell (T7.x–T9.x ran without the payload). The old "learned falls
  62 % on the 18° climb" was that artifact (0 % with the payload). `_apply`
  now restores every cell knob's default first.
- Earlier learned-vs-scripted verdicts from these benchmarks
  ([`gait-benchmark.md`](gait-benchmark.md), [`resid30-log.md`](resid30-log.md))
  used the distorted baseline. Rescored with both fixes: falls within noise of
  pure scripted, learned clearly faster on hard terrain — the verdict survives,
  for the right cells.
- New: `--hw i` (score the learned gait through the real control path; scripted
  runs natively) and `--scripted-from <json>` (reuse the deterministic scripted
  scores, ~half the runtime).

## Sim-vs-hardware audit

| Item | Status |
|---|---|
| IMU 5 Hz / no rate | `IMU_HOLD_STEPS`, `IMU_RATE_ZERO` (obs only; the Pi feeds an exact 0 rate, so no noise on it) |
| Command path | `CMD_PATH="i"` via `firmware_model.py` + `CMD_PATH_EXTRA_MS_MAX` (0–4 ms unmodelled firmware work) |
| Body mass | URDF 269 g = bottom of Petoi's 269–353 g; G2 has alloy servos → `BODY_MASS_SCALE=1.12` (~301 g). Re-set from the bring-up weigh-in |
| IMU mount tilt / servo zero error | `IMU_BIAS_DEG=2`, `JOINT_OFFSET_DEG=2` |
| Servo torque / speed | Fine: 0.2 N·m vs 0.29 peak; `i` easing (250°/s) is below the P1S (~800°/s) |
| Payload, joint obs, int-degree commands | Already matched |
| Hardware-only | Firmware version vs the traced source (bring-up 8a), roll/pitch sign (13a), low-battery cutoff 7.0 V → `rest` |

All knobs default off (older checkpoints replay unchanged) and are exposed as
`G2E_*` environment variables.

## Runs

| Run | Config | Result |
|---|---|---|
| `hw1_i` (3M pilot) | 5 Hz IMU + `i` + 0–4 ms | Real-path decathlon: fastest policy so far (0.073 m/s avg; 0.115 vs scripted 0.101 on flat); falls 162/1048, in line with the ideal-trained 3M `resid30_r1` (149); residual p95 21° of 30 |
| `hw1_20m` | pilot + `BODY_MASS_SCALE=1.12`, `IMU_BIAS_DEG=2`, `JOINT_OFFSET_DEG=2`, ±30° | **Promoted — deployed policy (`DEFAULT_POLICY`).** See results below |

### `hw1_20m` results (2026-09-23)

20.0M steps, finished 03:42 ET. Reward peaked ~1,970 at 8M and ended ~1,680 —
the same late decline as the previous 20M run (−31 % from its peak), which
comes from penalties/randomization ramping up over training, not the policy
degrading. Final KL 0.002. Residual rms 5.0°, p95 14.8° of 30°, 0 % of steps
near the limit. Replay reviewed frame by frame: level, full-extension trot.

Real-path decathlon (`--hw i`, 30 cells, 1,048 eps; scripted reused):

| | Falls | Avg speed |
|---|---|---|
| Scripted (pure `wkF`) | 77 | 0.0625 |
| **`hw1_20m`** | 161 | 0.0707 |
| `run20m_resid30_ppo` (previous base) | 94 | 0.0720 |

- 25 of 30 cells: 0 % falls and faster than scripted in every one — flat
  0.108 vs 0.101, 18° climb 0.104 vs 0.087, 20° descent 0.069 vs 0.022, rough
  ground 0.038 vs 0.015, 20 mm obstacles 0.050 vs 0.015.
- All falls are in the 5 bare-robot (no payload) stress cells. The outlier is
  **T6.5b** (60 % torque cutback + 12° descent, bare): 68 % falls and backward
  drift vs 0 % for scripted and the previous base. The same cell with the
  payload (T6.5) is 0 % falls and faster than scripted. G2 always carries its
  payload; note also the benchmark robot is 269 g, lighter than the ~301 g
  `hw1_20m` trained for. Flagged, not blocking.
- Verdict (user's bar: promote unless a large regression): **promoted.**
  Exported with its sidecar; `validate_deploy.py` ALL OK at 30° (0 joint-degree
  cells differ, 5 commands × 251 steps); `DEFAULT_POLICY = "hw1_20m_ppo.onnx"`.

## Slopes (2026-09-23)

`slope_sweep.py` (payload on, mass 1.12, ±2° calibration error, learned gait
through the real path, pure slopes — no rough-terrain episodes, no torque cut),
`hw1_20m`, 20 eps per condition, 0 % falls everywhere:

| Terrain | hw1_20m m/s | scripted m/s |
|---|---|---|
| Downhill 4–28° | 0.103–0.120 | 0.079–0.106 |
| Uphill 4 / 12 / 16 / 20 / 24 / 28° | 0.104 / 0.087 / 0.069 / 0.037 / 0.009 / −0.034 | 0.087 / 0.061 / 0.041 / 0.001 / −0.001 / −0.054 |
| Side-hill 5 / 6 / 7 / 8 / 12–20° | 0.088 / 0.073 / 0.048 / 0.020 / ~0.02 | 0.084 / 0.052 / 0.019 / 0.021 / ~0.005 |

- **Side-hills stall by ~8°.** The gait levels its body (roll 8° → 0° within a
  second); with the body level on tilted ground the downhill legs can't reach it
  (FR paw 8 % contact, BR 19 %) and G2 pushes on ~two legs. Bittle has no
  hip-roll joint — only lengthening the downhill legs fixes it.
- **Climbs stall ~24°** (scripted ~20°). Downhill is fine at any tested angle.
- **Every learned gait limps**: flat-ground paw contact — scripted wkF 41–61 %
  per paw; `hw1_20m` FR 13–16 %; `run20m_resid30` BL 17 %; `run20m_ppo` mildest.
  The model is symmetric (identical paw shapes, friction, heights).
- **Benchmark fixes (BENCH_VERSION 2):** slope labels corrected (pitch > 0 is
  downhill — "T6.1 −24° descent" was a 24° climb, T9.1/T9.2 swapped); slope
  cells no longer get rough-terrain episodes (they reset the grade to 0, ~35 %
  of each slope cell). `--scripted-from` refuses to mix versions.
- **Shaping-penalty ramp capped (`PENALTY_RAMP_CAP = 1.0`).** It was uncapped
  (`penalty_scale = steps / PENALTY_STEPS`, per env) — ~5× by the end of a 20M
  run with 8 envs, though the comment intends full strength and hold, and every
  reward weight was tuned in 2–3M runs that never passed ~0.75×. It caused the
  late reward decline in both 20M runs. The cap only acts past ~4M total steps,
  so it doesn't affect the 3M gate. `PENALTY_RAMP_CAP=0` reproduces the old
  behaviour (every checkpoint before `hw2`).

### hw2_20m (launched 2026-09-23; restarted ~30 min in to add the ramp cap)

`hw1` config + ramp cap + `SLOPE_TARGET_PROB=0.3` (half side-hills 3–15°, either side
down; half 12–24° climbs; never on rough/carpet) + `FAC_LEG_BALANCE=1.5`
(penalty when the least-used paw's contact over the last 2 s falls below 30 %;
~0 for scripted, large for `hw1_20m`'s limp). Gated at its own 3M checkpoint
vs `hw1_20m`@3M: `paw_balance.py`, `slope_sweep.py`, v2 benchmark. Split into
separate runs only if the gate is mixed.

**3M gate (2026-09-23): mixed → stopped at 3.7M, split.** vs `hw1_20m`@3M:
limp not fixed (least-used paw 17 % vs 22 % — it moved to another leg);
side-hills 12–15° ~2× faster (0.036/0.033 vs 0.017/0.015 m/s) but side-hills
5–8° and climbs 8–20° 20–45 % slower, flat −10 %, sills/rough/rubble slower;
bare-robot falls down (164 vs 223 / 1,048) and downhill faster. Two changes in
one run couldn't say which caused the regressions.

### hw3_20m (launched 2026-09-23)

`hw1` config + ramp cap + `SLOPE_TARGET_PROB=0.3` only (no leg-balance term).
Same 3M gate vs `hw1_20m`@3M. The limp needs its own look: the leg-balance
penalty moved it rather than removing it.

### The limp: root cause and fix (2026-09-23)

- **Cause: the diagonal partner, not the limping leg.** In `hw1_20m` (FR paw
  down 16 % of steps), zeroing the FR leg's own correction only brings it to
  21 %; zeroing the **BL** correction brings FR to 40 % (scripted 48 %). FR and
  BL are a trot diagonal — the learned BL correction extends that leg so it
  props the body alone and FR never quite lands.
- **Why training allows it:** the reward is ~blind to it — planting FR changes
  the total by +0.03/step (~0.2 %). The existing diagonal trot term
  (`FAC_FOOT_PHASE`) is ~0.5/step against ~15 for joint imitation. hw2's
  `FAC_LEG_BALANCE` only pushed on the least-used paw, so the policy satisfied
  it by moving the limp to another leg.
- **Fix candidate: footfall imitation (`FAC_CONTACT_IMITATION`).** Petoi's
  scripted walk has a clean diagonal schedule (FR+BL down together, then
  FL+BR). `reference_gait/build_contact_ref.py` records it per stride phase
  (through the `i` timing, using the env's own contact readings) into
  `wkf_contact_ref.npy`; the term penalizes each paw's mismatch against it.
  Per-paw targets can't be met by shifting the limp. Mismatch: scripted 0.06,
  `hw1_20m` 0.28 (4.5×); at weight 8 the limp costs ~1.7/step (~10 % of the
  total). Unramped, like joint imitation. Not yet trained.

**Removed (2026-09-23), after the payload fix.** `FAC_LEG_BALANCE`,
`FAC_STANCE_HOVER`, `FAC_RESID_BIAS` and `FAC_CONTACT_IMITATION` (hw2/hw5/hw7/hw4)
were all built to fight this limp. With the payload bug found and fixed, the limp
is understood to be substantially that artifact, not something reward shaping
needed to solve — and none of the four candidates actually worked (hover and
contact imitation cost 37–46 % of flat speed; resid-bias made the limp worse).
All four are removed from `opencat_gym_env.py`; `limp_queue.py` is retired
(kept only as a record — its `G2E_*` overrides are now no-ops).

### Gates were too noisy; averaged re-evaluation (2026-09-23)

`hw3` (slopes only) and `hw4` (footfall imitation 8 only) were each stopped at
3M and gated. Every run appeared to regress on uphill walking and sills vs
`hw1_20m`@3M — including `hw4`, which had no slope training. `hw1`'s own
neighbouring checkpoints explained it: 20 mm sill 0.048 / **0.100** / 0.040 m/s
at 2.6 / 3.0 / 3.4M. The @3M baseline was a lucky snapshot, so single-checkpoint
gates manufactured regressions — **stopping `hw2` as "mixed" was a wrong call on
that evidence.** `multi_ckpt_eval.py` now scores 5 checkpoints (2.2–3.0M) per run
and reports mean ± spread; this is the standard gate from here.

| mean ± spread over 2.2–3.0M | hw1 | hw2 slopes+leg-balance | hw3 slopes | hw4 footfalls |
|---|---|---|---|---|
| least-used paw (scripted 0.41) | 0.20 ±0.03 | 0.22 ±0.03 | 0.17 ±0.01 | 0.16 ±0.08 |
| footfall mismatch (scripted 0.06) | 0.41 | **0.29** | 0.45 | **0.33** |
| uphill 16° m/s | 0.030 ±0.036 | **0.065** ±0.004 | 0.049 | 0.014 |
| side-hill 12° m/s | 0.011 | **0.029** | 0.024 | **0.056** |
| flat m/s | 0.102 | 0.091 | 0.100 | 0.076 |
| rough ground m/s | 0.044 | 0.031 | 0.034 | 0.024 |
| bare gauntlet falls | 74 % | **37 %** | 63 % | 75 % |

`hw2` is the best overall; no run fixed the limp; footfall imitation at 8 is
too strong (slows everything).

### Limp diagnosis, round 2

- The limping paw hovers **2–4 mm** above the surface while the scripted walk
  has it down, carrying ~0.2 N vs ~2.5 N. The model is balanced (CoM 0.5 mm
  off-centre sideways).
- Part of it is a constant lopsided correction: subtracting `hw1_20m`'s mean
  per-joint correction brings FR from 10 % to 32 % contact at unchanged speed.
  But `hw2`'s larger offsets are a lean its gait depends on (subtracting them
  halves its speed) — it has to be trained out, not removed afterwards.
- Binary contact terms can't see "almost down". **`FAC_STANCE_HOVER`** penalizes
  the hover distance itself (downward ray from each paw; paws the scripted walk
  has firmly down at this phase; beyond the 6.5 mm resting height, per 5 mm).
  Full strength: scripted −0.08/step, `hw1_20m` −1.3, `hw2`@3M −2.1.
- **`hw5`** = `hw2` config + `FAC_STANCE_HOVER=3`, running to a 3M averaged gate.
  Bar: least-used paw ≥ ~0.35 while keeping `hw2`'s slope/fall gains.

### The limp was a sim artifact: the payload locked the body's rotation (2026-09-23)

The limp appears only with the payload on (bare robot: least-used paw 45–50 %, no
limp) and doesn't depend on the payload's mass or position — a 1 g + 1 g welded
payload limps exactly like the full one, and the same mass added into the torso
doesn't. Cause: the welded payload bodies had zero rotational inertia, which Bullet
treats as "cannot rotate"; welded to the torso, they locked G2's orientation
(scripted walk: roll ±0.06° with the welded payload vs ±4° with the mass in the
torso). Fixed with `PAYLOAD_INERTIA="box"` (real inertia, collisions off): roll
back to ±4°, yaw drifts again. Every run since 2026-09-02 trained on the locked
body; the limp-fix queue (`hw5`–`hw8`: stance hover, average-correction penalty,
footfall imitation) was chasing this artifact — none passed, and none needs
pursuing. `BENCH_VERSION` 3. Re-baseline on the corrected sim in progress; see the
top of `project-plan.md` for the audit of what else this affected.

Going forward: no separate 3M pilots — launch the full run and gate on its own
3M checkpoint against the previous full run's 3M checkpoint.

### Reward audit + fresh-start redesign (2026-09-23)

Removed four reward terms that were reactive patches for the payload-lock
bug: `FAC_LEG_BALANCE`, `FAC_STANCE_HOVER`, `FAC_RESID_BIAS`,
`FAC_CONTACT_IMITATION`. `limp_queue.py`/`hw5`-`hw8` retired.

Goal reset: beat scripted in *most* categories ("scripted+", not literal
every-cell), see [[feedback_training_capability_bar]]. Regression bar:
<10% speed loss = pass, 10-15% = tie, not a fail.

### Training-ground redesign: staged curriculum + course mechanics (2026-09-23)

Lesson from the earlier failed ledge attempt: it was bolted onto an
already-consolidated policy instead of trained in from step 0 -- every new
mechanic below goes into a fresh run's curriculum from the start.

Four new `opencat_gym_env.py` mechanics:
- `SURFACE_TRANSITION_STEP_M` -- material transition now also carries an
  optional height step (real doorway thresholds are usually both at once).
- `RUG_SLIDE_PROB`/`RUG_SLIDE_FRICTION` (0.35) -- flat, low-friction floor,
  distinct from the bumpy `CARPET` heightfield / high-friction `CARPET_SOFT`.
  Verified in isolation: friction reads 0.35 consistently across 8 seeds.
- `SNAG_OBSTACLE_PROB`/`_scatter_snags()` -- thin, lane-spanning boxes (a
  cable/cord analog), can't be stepped around, only over.
- `TORQUE_SLOPE_CORRELATE` -- raises the overheat-cutback trigger probability
  on slope episodes.

`validate_deploy.py` confirms `hw1_20m_ppo.onnx` unaffected (all four default off).

### Benchmark rebuilt to 21 cells / 11 categories (2026-09-23)

Bare-robot variants removed (was 30% of every run's time). 24 cells/8 tiers
-> 21 cells/11 categories mapping one-to-one onto the staged course: Flat/
calm, Flat+push, Incline/decline, Cross-slope, Transitions, Ledges (3
heights), Terrain/rubble, Obstacles (box+snag), Brutal shove, Overheat+
slope, Rug (carpet+slide), Combined gauntlet. Old cell IDs no longer exist.

Smoke-tested: **5m00.7s** for the full 21-cell run (20 eps/cell), down from
8m26s for the old 30-cell ladder.

**Finding: `hw1_20m` is not a valid Phase B comparator.** Trained *before*
the `PAYLOAD_INERTIA="box"` fix, so it never learned to handle a body that
can tilt. Re-scored on the new ladder: 15% fell on T1.1 (flat, calm), 30% on
T1.2 -- fails the flat-ground bar on its own
([[feedback_phase_b_learnability_gate]]). **Decision:** need a fresh Phase A
baseline under corrected physics before any Phase B round.

### Phase A baseline (`base1_20m`) trained, Phase B launched (2026-09-23 -> 24)

`base1_20m` launched 8:20 PM 9/23, same config as `hw1_20m` plus
`SLOPE_TARGET_PROB=0.3`. Finished 3:48 AM 9/24 -- real sustained rate
~750-760 fps (not the ~1000 fps early-burst reading; a 20M run takes ~7.5h,
not ~5.5h). Scored clean: **0% falls, 0.088 m/s** on T1.1.

Found and fixed a real gap: `CARPET`/`CARPET_SOFT`/etc had no `G2E_`
override, so a training subprocess could never actually turn carpet on.

**`b1_ledge` gate (3M/20M steps):** T1.1 fell 1.3% (clean), ledges fell
35.8% (partial-training trend). Contradicts the pre-payload-fix "ledges made
it worse" finding -- with a body that can actually tilt, ledge training
doesn't cost the flat gait the way it did before.

**Round 1 stopped and superseded (2026-09-24).** Added
`SERVO_RATE_LIMIT_DEG_S` (137°/s, a comparable project's measured Bittle X
V2/BiBoard V1 ceiling, same servo class as G2 per `docs/hardware/specs.md`,
not G2's own measurement yet -- H13) as a real training-time constraint.
Impact-tested against `base1_20m`: T5.2 ledge fell 0%->15%, T7.1 speed -42%
-- real, non-negligible. Same call as the payload-inertia bug: stopped
rather than finish on physics already known unrealistic. `base1_20m` +
`b1_ledge`-`b5_slide_rug` results kept as a labeled pre-servo-limit
reference, not deleted. Round 2 (`base2_20m` onward) runs under corrected
dynamics.

**Naming correction pending: "slide-rug" is really "tile"/low-friction hard
floor.** It's mechanically just reduced friction on a flat plane -- no
rug-specific bump/compliance/looseness modeled, so tile or polished
hardwood is the more accurate real-world analog. Updated human-readable
labels in `opencat_gym_env.py`, `phase_b_orchestrator.py`,
`benchmark_decathlon.py` (cosmetic only). Did NOT rename the underlying
`RUG_SLIDE_PROB`/`RUG_SLIDE_FRICTION` vars or the `r2_b5_slide_rug` tag --
`phase_b_orchestrator.py` was a live process with the old names already
loaded; renaming mid-run would silently deactivate that round when reached.
Full rename queued for the next clean restart -- target names `TILE_PROB`/
`TILE_FRICTION`, tag `r2_b5_tile`.

**Policy correction: nothing runs to 20M except the real final
consolidation run.** `base2_20m` was mistakenly running to full 20M, same
mistake as round 1's `base1_20m`. Rule, stated explicitly by the user: any
"is this viable" run gets a 3M cap (learnability + no-regression); only the
real final run goes to 20M, with a 10M dress rehearsal immediately before
it. Stopped `base2_20m` at 10.16M; evaluated its existing 2.2M-3.0M
checkpoints directly: **0% fell, 0.072 m/s** -- clean. `run_pipeline.py`'s
`phase_a()` rewritten to enforce the 3M cap going forward (launch, gate at
3M, stop, halt the pipeline if the baseline itself isn't clean).
`PHASE_C_STEPS` corrected 6e6 -> 10e6 (dress rehearsal was always meant to
be 10M).

**Measurement methodology corrected: single checkpoint at the end of the 3M
run, no averaging.** Was a 5-checkpoint average (2.2M-3.0M) for the gate, 3
for the early check. Dropped per user instruction after finding a real case
in our own data where averaging hid the signal: `b1_ledge`'s ledge cell had
a clean improving trend 2.2M->2.8M (43.8%->25.0% fell) then jumped to 50%
at 3.0M -- the average (35.8%) represented neither the trend nor the actual
end state cleanly. `phase_b_orchestrator.py`/`run_pipeline.py` now both
score `GATE_STEP=3000000` and `EARLY_STEP=2000000` directly.
`compose_phase_c()`'s trend check (comparing gate-window first vs last)
replaced with a simple absolute bar (`skill_fell <= 0.85`) since there's
only one gate point now.

**URDF joint limits widened, applied live without a restart.** Second fix
from the same community-project review (`docs/research/community-projects.md`
Finding 1b): shoulder/hip/knee limits were too narrow for `rc`'s real
self-right range. Widened only the 5 values `rc_ref.npy` actually violates.
Smoke-tested first (old vs new URDF, same checkpoint, same seeds): identical
to 4 decimal places on every metric -- confirmed inert for walking (residual
targets never approach even the old limits), so applied directly to the live
file rather than stopping/restarting (`p.loadURDF()` reloads every episode
reset). Different call from the servo-speed fix, which had a real measured
effect and got a full restart -- this one was verified inert first.

**`b4_carpet` never actually ran the first time (infrastructure bug).**
`start_run.sh` can raise two separate y/N prompts; `launch()` only piped a
single `echo y`, so a stray `g2watch-checkpoint` viewer window ate the
prompt and the launch silently failed, logged as an indistinguishable
"stopped before 2.0M." Fixed: `yes y` (answers any number of prompts) in
both `phase_b_orchestrator.py` and `run_pipeline.py`. Also fixed the summary
writer overwriting `trained/phase_b_summary.json` wholesale instead of
merging by tag.

**Tag-collision bug found and fixed.** Stopping a run mid-training for a
methodology fix leaves stale checkpoints/console.log on disk;
`start_run.sh`'s collision guard then silently refuses a relaunch under the
same tag (not a y/N prompt, a hard failure) -- cost `r2_b1_ledge` and
`r2_b2_transition` their first attempts. Fixed with `_clean_stale()` in both
scripts (removes a tag's leftover files if it never produced a finished
`_ppo.zip`) plus a post-launch check that fails loudly instead of silently.

**`b2_transition` gate: FAILED, excluded.** T1.1 fell 48.7% (up from 17% at
the early check -- got worse, not better), speed 0.039 m/s (vs `base1_20m`'s
0.088). Not hazard-specific -- the whole gait destabilized. Material-only
transitions at `SURFACE_TRANSITION_PROB=0.25` broke the gait by 3M steps;
worth a lower-probability retry later, not a final verdict on one attempt.

`run_pipeline.py` built as the unattended supervisor per "make sure testing
does not stop until it is complete": Phase A (3M gate) -> Phase B (7
fresh-run candidates, 3M gate each) -> Phase C (combines whatever passes
into one 10M dress rehearsal) -> report and stop, never auto-launching the
real 20M run.

### Round 2 Phase B results (single-checkpoint gate, corrected physics)

**`r2_b1_ledge`: PASSED, included.** T1.1 fell 6.2%, speed 0.042 m/s (vs
`base2_20m`'s 0.072 m/s baseline -- a real cost). Ledge cells fell 62.5% at
3M/20M steps -- higher than round 1's 35.8% (measured under the old,
unrealistically-fast physics), consistent with the servo-speed impact test
finding that ledges specifically get harder under a realistic speed limit.
`flat_clean=True`, `skill_fell` under the 0.85 inclusion bar -- included as
a Phase C candidate. Reward-tweak note (observation only, not implemented):
worth considering a reward term that rewards early foot-lift/anticipation
near a ledge if this number doesn't improve with more training -- nothing
in the current reward set anticipates a ledge before contact.

**`r2_b2_transition`: PASSED, included -- complete reversal from round 1.**
T1.1 fell 0%, speed 0.072 m/s (matches `base2_20m`'s baseline exactly).
Transition cells fell 0%. Round 1's same mechanic (material-only transition)
FAILED catastrophically under the old physics (flat_fell 48.7%, skill_fell
46.3%). Strong signal that round 1's failure was itself an artifact of the
servo-speed bug -- the old unconstrained joint speed likely let the policy
attempt violent, unrealistic corrections at the transition point that
destabilized the gait; that failure mode isn't reachable anymore under the
realistic speed limit. Directly validates redoing the whole campaign rather
than trusting round 1's data. No reward-tweak note needed -- this one is
already clean.

**`r2_b3_transition_step`: PASSED, included.** T1.1 fell 6.2%, speed 0.048
m/s (below `base2_20m`'s 0.072 baseline). Transition+step cells fell 0%.
Consistent with round 1's version of this mechanic, which also passed
cleanly -- transitions-with-a-step continues to look like the more
learnable variant of the two transition mechanics under both physics
regimes.

**`r2_b4_carpet`: PASSED, included.** T1.1 fell 0%, speed 0.062 m/s. Carpet
cells fell 0%. Fourth consecutive round-2 pass -- no mechanic has failed
yet under the corrected physics.

**`r2_b5_slide_rug`: FAILED, excluded -- first round-2 failure.** T1.1 fell
87.5%, speed 0.059 m/s, tile/slide cells also fell 87.5%. Dramatic reversal
from the early check (2M steps: T1.1 fell 50%, skill cells fell 0% -- the
skill looked fully mastered). By 3M both flat ground and the skill itself
collapsed. `flat_clean=False`, correctly excluded. Reward-tweak note: the
early-to-gate reversal (skill 0%->87.5%) suggests the policy found an
unstable strategy that worked briefly then broke, rather than steadily
degrading -- possibly worth a smoothness/stability penalty specific to
low-friction footing if this mechanic gets a second attempt at a lower
training-time probability (it's currently 15% of episodes).

**`r2_b6_snag`: PASSED, included.** T1.1 fell 0%, speed 0.057 m/s. Snag
cells fell 0%. Fifth pass out of six rounds so far -- only `r2_b5_slide_rug`
has failed.

## Round 3: sequential single-skill staging beats parallel-combined (2026-09-25/26)

Deployment_CandidateV1 (parallel-combined, all 5 mechanics trained simultaneously
from scratch) showed ledges regressing over training (5%→30%→40% fell,
3M→10M→20M) while everything else stayed clean, and was slower than scripted
on every category but one. Round 3 tested training each mechanic individually
in increasing difficulty (flat → transitions → carpet → step → snag → ledges,
ledges last since it's unambiguously the hardest in every measurement), each
stage continuing from the last, before the same 20M consolidation. All 6
stages passed on the first try, zero retries needed.

**Result: promoted to Release_CandidateV2.** Beats V1 on ledges (36.7%→13.3%
fell) with zero regression anywhere, and faster on every category (+15.6% to
+54.1%). Beats scripted outright on ledges (13.3% vs 26.7% fell) — the first
round this campaign where the learned policy wins a category on falls, not
just ties. Full report + GIFs: [Release Candidate V2 artifact](https://claude.ai/artifact/Q7xnC52VA8HwerpDMsqEw3).

Changes this round, alongside the staging: carpet exposure cut 50%→10% (R0
above found 50% cost 8-10% flat speed for zero capability gain — an automated
gate would have stripped it entirely if it cost >5% here; never triggered,
no measurable cost at 10%), ledge height ceiling raised 30mm→35mm, command
cadence changed to send every 3rd tick instead of every tick (i@27 — reduces
how often the firmware's oldest-wins serial backlog has a stale command
queued), `FAC_YAW_TRACK` 6.0→9.0 (V1's yaw-rate wobble ran 1.3-2.4x
scripted's; this brought flat-ground wobble to ~1.56x, improved but not
resolved). Also found and fixed: every gate-scoring function set
`IMU_HOLD_STEPS`/`CMD_PATH` to match training but never set
`CMD_SEND_EVERY_N`, silently scoring every gate this campaign under different
command timing than training used.

Open items, not yet acted on: T5.3 (40mm, beyond the trained ceiling) shows a
large heading-drift outlier (31.5° vs scripted's 3.0°) alongside its 40% fall
rate — a qualitatively different failure mode there, worth a closer look
before pushing the ledge ceiling further. Yaw wobble still elevated vs
scripted despite the FAC_YAW_TRACK bump.

## Round 4: yaw-tuning a consolidated gait, R2 vs R3 (2026-09-26)

Round 3 left two open items: elevated yaw wobble vs scripted, and a
directional left-turn bias. The left-turn bias was investigated first and
ruled out as a reward-tuning target: the zero-learned-policy *scripted* gait
showed the same directional bias, meaning it's a sim/solver-substrate
artifact, not something the policy learned. Squared-penalty reward terms
(`FAC_YAW_TRACK`, `FAC_HEADING`) are direction-agnostic by construction and
can't fix a one-directional bias regardless — tuning against it risked
teaching the policy to counter-steer a sim-only bug, which could introduce
the opposite bias on real hardware. Skipped.
*(2026-10-06: the policy appears to have learned such a counter-steer anyway, a fixed BL-hip offset of about 7 deg, which turns G2 about
140 deg right on the real floor. See [`real-walk-log.md`](real-walk-log.md) "Why V2.1 drifts right"; V3 adds a mirror-symmetry loss
against it.)*

Yaw wobble was tested with three 3M-step continuations from
Release_CandidateV2, each isolating one lever: R1 (`FAC_YAW_TRACK` 9→12
alone), R2 (`FAC_YAW_TRACK` 9→11 + `FAC_RESID_SMOOTH` 8.2→10, paired), R3
(`FAC_RESID_SMOOTH` 8.2→10.5 alone). R2 screened best (T1.1 yaw RMS 4.56 vs
R3's 4.94, both vs V2's 5.24) and was launched on the full 10M schedule
first. Its own 3M sanity check showed T5.2 (25mm ledges) fell-rate at 30%,
a live regression — R3 was picked instead and launched on the same 10M
schedule; R2 was finished anyway afterward, purely for a clean head-to-head
at equal (13M cumulative) budget.

**Result: R3 beat R2 on every metric once both were trained to the same
budget** — T1.1 yaw RMS 4.02 vs 4.49, speed 0.0891 vs 0.0862, T5.2 fell 5%
vs 10% — reversing what the 3M screening suggested. The screening signal
was misleading here: R2's paired levers may have front-loaded gains that
didn't hold up over the full schedule as cleanly as R3's single, larger
smoothing-only push.

R3's own checkpoint progression (3M/5M/10M = 6M/8M/13M cumulative from V2)
showed T5.2's fell rate improving through the full schedule (20%→10%→5%)
while T1.1 yaw RMS flattened out by 5M (3.93→4.10→4.03, no clear further
descent) — the case for the full 10M was the ledge cell still improving and
speed still climbing, not the yaw metric itself still trending down. A
longer (20M) tuning run wasn't attempted, but the flattened yaw trend plus
this being a gentle constant-LR fine-tune (not a fresh `linear_schedule` run)
both point toward diminishing returns past 10M for this lever.

**Promoted to Release_CandidateV2.1** ("2.1" — same base/architecture as V2,
a reward-tuning refinement, not a new generation). Beats scripted on speed
in every cell and on T5.2 falls (10% vs scripted's 40%); beats V2 on yaw/
drift on flat ground and both transition cells (T1.1 yaw 5.24°→4.02°, drift
3.10°→1.75°) plus a small speed gain everywhere. Two open caveats, both
already out of scope for this round: T5.2 heading drift roughly doubled
(5.44°→12.20°, small 20-episode sample) alongside its 0%→10% fell-rate
uptick; T5.3 (40mm, already known as the ledge-height capability ceiling)
got worse on yaw RMS (15.61°→22.84°) though tied on fell rate. Full report +
GIFs: [Yaw-Tuning Round artifact](https://claude.ai/artifact/WM5k6QG7p3vT9p6bzStt9p).

## Round 5: real-hardware-IMU retrain, abandoned after a firmware reflash changed the premise (2026-09-29)

G2's body arrived 2026-09-28. That night's hardware bring-up measured the
real BiBoard's IMU stream at ~93-249 Hz, contradicting the 5 Hz cap
(`IMU_HOLD_STEPS=16`) every real-path run since `hw1_20m` had assumed. Ran
a full retrain campaign on that measurement: `phase_r5_hw_sequential.py`
(V2.1's staged-mechanic recipe, `IMU_HOLD_STEPS` 16→1 to match the real
rate) → `phase_r7_holdsteps_probe.py` (a 3M diagnostic after r5_hw showed
elevated yaw/drift, testing whether tick-to-tick observation noise was the
cause — confirmed: `IMU_HOLD_STEPS=4` recovered most of it) →
`phase_r8_holdsteps4_consolidate.py` (10M consolidation of that fix,
running when the next finding landed).

**2026-09-29: the 93-249 Hz measurement turned out to be a stale-firmware
artifact, not real hardware's actual behavior.** A separate bug that same
night (BiBoard's onboard camera-enable command permanently kills the IMU
task, persisted to EEPROM, surviving power cycles — see
`docs/hardware/petoi-firmware-reference.md`) forced a full flash erase +
reflash to Petoi's current official firmware. Read BiBoard's version
banner before the reflash: `B10_251121` — a 2025-11-21 build, ~10 months
stale. **After reflashing to current firmware, the IMU rate measured
exactly 5.0 Hz** — matching the *original* `hw1_20m`/`Release_CandidateV2`/
`V2.1` assumption all along, not the stale board's anomalous fast rate.

**Decision: abandoned the r5_hw/r7/r8 lineage, keeping `Release_CandidateV2.1`
as the release candidate.** The premise motivating this whole retrain —
"the sim's IMU assumption doesn't match real hardware" — was itself an
artifact of running stale firmware; on current official firmware, V2.1's
original `IMU_HOLD_STEPS=16` is correct. `run_pipeline.py`'s `BASE` was
reverted back to `G2E_IMU_HOLD_STEPS=16`. No checkpoints from this round
were promoted; `r5_hw_candidate`'s benchmark numbers (tied with V2.1 on
4/5 categories, lost on ledges, worse yaw/drift) are moot against a
premise that no longer holds, not a real regression to chase.

**Worth a future check, not urgent:** `hw1_20m` (the currently deployed
policy) has never been re-benchmarked against G2's *current* firmware —
it was trained and validated under the same 5 Hz assumption, so it's
very likely still fine, but hasn't been directly reconfirmed since the
reflash.

**Post-mortem transparency note on the sim/benchmark config, checked
2026-09-29 after the abandon decision:** confirmed every training/scoring
script for full consistency. `run_pipeline.py` needed reverting (its
`BASE` dict plus three hardcoded `E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO,
E.CMD_PATH` eval-matching lines, all now back to `16, True, "i"`).
`phase_c_report.py` and `benchmark_decathlon.py` were never touched
during this round — both were already hardcoded to `16` throughout, so
no revert was needed there. That also means one thing is worth flagging
honestly: `r5_hw_candidate`'s benchmark comparison above (the "tied on
4/5, lost on ledges" numbers) was scored via `phase_c_report.py`'s
unchanged `16`, while that checkpoint was actually trained under
`IMU_HOLD_STEPS=1`/`4` — an internal train/eval mismatch in that one
comparison, on top of the whole lineage's premise not holding up. Doesn't
change the decision (the lineage is abandoned either way) but the
specific numbers reported for `r5_hw_candidate` shouldn't be read as a
clean apples-to-apples benchmark.

## Deploying a policy

`export_onnx.py --model trained/<run>_ppo` → `<run>_ppo.onnx` + `.onnx.json`;
`validate_deploy.py --onnx trained/<run>_ppo.onnx` must print
`residual scale: 30 deg` and `ALL OK`; set `DEFAULT_POLICY` in
`pi_pipeline/gait/residual_policy.py`; rsync the `.onnx` and `.onnx.json`
together (bring-up step 12a, `guides/pi-bring-up.md` §7).
