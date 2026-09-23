# hw1 — training under G2's real control path

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
- **Found, not changed:** the shaping-penalty ramp is uncapped
  (`penalty_scale = steps / PENALTY_STEPS`, per env) — ~5× by the end of a 20M
  run with 8 envs, though the comment intends full strength and hold. It's the
  cause of the late reward decline in 20M runs. Left as-is so `hw2` changes one
  thing at a time; decide after.

### hw2_20m (launched 2026-09-23)

`hw1` config + `SLOPE_TARGET_PROB=0.3` (half side-hills 3–15°, either side
down; half 12–24° climbs; never on rough/carpet) + `FAC_LEG_BALANCE=1.5`
(penalty when the least-used paw's contact over the last 2 s falls below 30 %;
~0 for scripted, large for `hw1_20m`'s limp). Gated at its own 3M checkpoint
vs `hw1_20m`@3M: `paw_balance.py`, `slope_sweep.py`, v2 benchmark. Split into
separate runs only if the gate is mixed.

Going forward: no separate 3M pilots — launch the full run and gate on its own
3M checkpoint against the previous full run's 3M checkpoint.

## Deploying a policy

`export_onnx.py --model trained/<run>_ppo` → `<run>_ppo.onnx` + `.onnx.json`;
`validate_deploy.py --onnx trained/<run>_ppo.onnx` must print
`residual scale: 30 deg` and `ALL OK`; set `DEFAULT_POLICY` in
`pi_pipeline/gait/residual_policy.py`; rsync the `.onnx` and `.onnx.json`
together (bring-up step 12a, `guides/pi-bring-up.md` §7).
