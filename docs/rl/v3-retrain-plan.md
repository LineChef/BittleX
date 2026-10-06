# V3 retrain plan: calibrate the sim to G2, bake every tuning lesson into one fresh gait (approved 2026-10-06)

**Status: APPROVED by the user 2026-10-06** (incl. the turning gate, mirror symmetry and speed optimizations 1-5). This is the working plan
and the hand-off: a new session should be able to resume from this page alone. Background: [`v22-handoff.md`](v22-handoff.md) (the drift
campaign this replaces), [`hw1-log.md`](hw1-log.md) (how V2 / V2.1 were trained), [`real-walk-log.md`](real-walk-log.md) (real data).

**Principle (user):** everything learned from tuning goes into the base training; **no tuning runs after the 20M consolidation run.** Each
new lever is screened alone, the ones that pass are combined and built into a staged chain, and the 20M run is the last training run.
Tuning runs stay possible later if the result needs them, but none are planned.

## 0. Where to resume (state at the end of 2026-10-06)

**Done:**
- Investigation and plan (this page).
- **Ramp fix** (§2.1) in `opencat_gym_env.py` + `train.py`, smoke-tested.
- **4 torch threads** in `train.py` (§4 optimization 1).
- Probe tools: `drift_probe.py` levers `yawflip` / `yawzero`, `replay_real_obs.py`, `train_throughput.py`.
- v2.2 closed: its runner exited by itself at 12:45 PM after no round passed; stale log watchers were killed. Nothing is training.

- **Yaw-sign fix (Phase 0 step 1, code DONE 2026-10-06, NOT yet rsynced to the Pi):**
  - `POLICY_YAW_SIGN = -1.0` and `policy_quat()` in `pi_pipeline/gait/run_gait.py`, used for the policy's input in `run()` (reset and every
    tick). The CSV / ring-buffer `yaw` column stays in the firmware convention (+ = right); `imu_parse.py` is unchanged.
  - `dry_run()` feeds random synthetic yaw, so the sign doesn't matter there.
  - Tests in `pi_pipeline/tests/test_run_gait_imu.py`: the sign unit test, plus a loop test that a real 20-deg right turn reaches the policy
    as -20 deg while the log keeps +20. Full `pi_pipeline` suite passes.
  - No behaviour change for V2.1, which ignores heading. **To do:** rsync to the Pi when G2 is online.

**Next, in order** (Phase 0 code work is mine; the user's hardware steps can run in parallel):
1. **rsync the yaw-sign fix to the Pi** when G2 is online (`docs/guides/pi-bring-up.md` §7).
2. **Servo step-test mode** (Phase 0 step 4): command a 40-60 deg step on one joint while reading servo feedback (feedback works, mean
   112 ms / ~9 Hz per read; see `real-walk-log.md` "Servo feedback tests" and `tools/servo_static_test.py`). Logs to CSV.
3. Then Phase 2 code (it doesn't need the hardware data), while the user does Phase 0's hardware steps.

**What the user is doing in parallel:** replacing servo 8 (front-left shoulder). That it is bad is **not confirmed**; after the swap the six
V2.1 baseline walks are repeated to see whether anything changed. The user will report when it's done.

## 1. Findings (2026-10-06)

### 1.1 The yaw-sign mismatch is real but doesn't explain V2.1's drift
- G2's IMU (via `imu_parse.py`) reports + yaw for a RIGHT turn (confirmed 10-02 with `kvtF`, `real-walk-log.md`). PyBullet reports + yaw
  for a LEFT turn (z up). `run_gait.py:591-592` passes the rebased yaw straight into `euler_to_quat` → the policy, so the policy's heading
  input on G2 has the wrong sign.
- **Sim test**: `G2E_PAYLOAD_PROFILE=case python drift_probe.py trained/Release_CandidateV2.1_ppo --episodes 24 --lever yawflip` (and
  `yawzero`, and none). T1.1 environment, 12.5 s. Mean heading change: normal +9.4 deg, negated +8.4, zero +9.1, all 0/24 falls, joint means
  equal to 0.1 deg. The hook was verified to change what the policy sees (+27 / -25 / 0 deg). **V2.1 ignores heading.**
- **Offline replay** of the six 10-06 walks (`python replay_real_obs.py`, defaults to `docs/rl/real-walk-data/2026-10-06/*.csv`):
  - The logged IMU through the ONNX policy reproduces **100%** of the logged joint commands, so the Pi runs V2.1 exactly.
  - Negating yaw moves the commands 1-4 deg, growing with heading: shoulder L-R difference shift 0.7 deg at 5-30 deg off course, ~3.7 deg past
    100 deg.
  - At large headings the quaternion's x/y parts mix roll and pitch (out of training distribution).
- **The fix is still required**: any policy that learns to use heading would steer the wrong way on G2.
- Out-of-date line found: `real-walk-log.md` (10-01 section) says "the loop discards the IMU yaw". The loop has fed yaw since `79da931`
  (2026-09-23).

### 1.2 What the drift is, as far as the data goes
- `wkF` is left/right symmetric: mean URDF deg `[46.9 6.0 46.9 6.0 53.0 8.2 53.0 8.2]` (FLsh FLel FRsh FRel BRhip BRkn BLhip BLkn).
  Mirrored (swap L/R) and shifted half a cycle (50 of 100 frames) it matches itself to within 4.2 deg max.
- **V2.1 has learned a fixed asymmetry:**
  - Sim joint means `[49.1 2.4 48.0 1.3 53.8 2.6 60.2 3.8]`; G2 `[47.2 5.3 49.2 3.1 52.9 1.0 60.1 4.8]`.
  - BL hip about 60 vs BR about 53, in both.
- Scripted `wkF` curves LEFT in the sim (the 2026-09-26 "solver artifact", `hw1-log.md` Round 4) and also curved left on G2 (10-01, open
  loop, `real-walk-log.md` hard-floor table). V2.1 learned a constant counter-steer: it nets +9 deg (left) in the sim, but about -140 deg
  (right) on G2.
- Supporting evidence:
  - G2 turns ~11 deg/s from the first second (yaw at 25/50/75/100%: +35 +72 +111 +150 in run 2), so it isn't heading feedback.
  - An open-loop sim replay of G2's commands turns the sim right too (-30..-37 deg, `sim_vs_real_walk.py`).
  - The sim travels ~16% short on the same commands (contact differs).
  - `hw1-log.md` Round 4 warned that counter-steering a sim bias could produce the opposite bias on real hardware.
- **Main hypothesis:** a constant L/R asymmetry learned against the sim's left bias, which over-steers on G2's real contact. Phase 1 tests
  it (a calibrated sim should turn V2.1 right). The cure is structural: mirror symmetry (R1), so a bias can only be corrected through
  feedback.
- **Servo 8 is NOT confirmed bad.** It reads stuck near 42 deg in `servo_static_test.py` (`real-walk-log.md` "Servo troubleshooting"), but
  the scripted walk drives it above 42 deg 63% of each cycle and still curved left. The user is replacing it; the walks get repeated
  afterwards.
- v2.2's last round (R3, 3M control, case payload, nothing else): calm falls 0.08, speed 0.040, heading error under the reference
  disturbance 39.8 deg, yaw rms 0.178. All three v2.2 rounds failed. Results: `trained/v22_results.json`, snapshot in `v22-data/`.

### 1.3 Gaps between the sim and G2 (V2.1, calm hard floor, case payload; `drift_probe.py`, 8-24 episodes of 12.5 s)

| Measure | G2 | Sim as trained | `G2E_SERVO_RATE_LIMIT_DEG_S=0` | `G2E_CMD_PATH=` + no rate limit | `G2E_CMD_SEND_EVERY_N=1` |
|---|---|---|---|---|---|
| Roll std (deg) | 5.7-6.2 | 3.05-3.3 | **5.56** | 7.36 | 3.34 |
| Pitch std (deg) | 1.9-2.7 | 2.4-2.6 | 5.06 | 5.13 | 2.48 |
| Speed (m/s) | ~0.118 (10-01 taped) | 0.053 (12.5 s) | 0.051 | 0.057 | 0.052 |
| Heading change, 12.5 s | +142 deg right | +9 left | +6 | -17 | +10.5 |
| Falls | 0 / 6 | 0 / 24 | 1 / 8 | 2 / 8 | 0 / 8 |

More measurements:
- Old 377 g payload (`estimate`): speed 0.058, heading +2.9, roll 3.08.
- Case payload with 250-step episodes: speed 0.074 (vs 0.053 over 1000 steps). **V2.1 slows past the 3.1 s it was trained on; G2
  doesn't.**

What follows:
- **Servo speed** (`SERVO_RATE_LIMIT_DEG_S` 137, from BittleJuice, never measured on G2, backlog H13): without it the sim matches G2's roll,
  but pitch overshoots. Measure it (Phase 0).
- **Speed:** the sim is ~half of G2. The command path doesn't explain it; contact (16% short on replay) and the long-walk slowdown do.
- **Episode length:** training episodes AND every benchmark cell are 250 steps (3.1 s); G2 walks 12.5 s to minutes.
- **Payload:** the 422 g profile (`G2E_PAYLOAD_PROFILE=case`, spine 86 g / camera 15 g front / speaker 20 g rear) isn't in
  `run_pipeline.BASE` or the benchmark.
- **Carpet:** the sim's T10.1 passes; every gait fails on G2's carpet (guessed model, H10).
- **Battery sag:** 0.3-0.45 V under load; not modeled.

### 1.4 Why V2.1 ignores heading
1. Episodes are 3.1 s, so heading error barely builds up.
2. Nothing pushes it off course in training.
3. Heading is only inside the quaternion, mixed with roll/pitch.
4. `FAC_HEADING·err²` is flat near zero: 10 deg costs 0.15 per step against roughly +20 per step of positive reward.
5. `TRAIN_YAW` = 0: the turn command was never trained (it's in the observation, always 0), so the Pi can't steer the learned gait.

### 1.5 Turning history (why turning is gated, not assumed)
- `phase2` (2026-09-02, `refinement-regimen.md`): the yaw command had ~zero effect (actual yaw rate ~-0.006 rad/s whatever was
  commanded). Turning was dropped from the curriculum in G4.
- Phase D/E (`plan-detail/phase8-perception.md`): firmware `wkL`/`wkR` played open-loop produce ~0 deg of yaw in PyBullet with this
  URDF; the real Bittle turns with them (foot slip and gyro turn-assist the sim doesn't model).
- Why it might work now: the same contact gap seems to be why a 7-deg rear-hip asymmetry turns G2 ~140 deg but the sim ~9 deg. G2 has
  the turning authority (V2.1 turns it 11 deg/s by accident). If Phase 1's contact calibration makes the sim turn, a turn curriculum
  becomes learnable. **Approved as a measured gate** (Phase 1).

### 1.6 Training throughput (M1 Pro, 6P + 2E cores; `train_throughput.py`)
- One env alone: 841 steps/s (profile: `pybullet.stepSimulation` ~40%, Python env step ~35%).
- `train.py` (8 `SubprocVecEnv` envs, batch 64, 10 epochs): 686-711 steps/s overall. Per 16,384-step rollout, collection ~9.4 s and the
  PPO update 14.4 s (60% of the time).
- Torch threads for the update (same math): 8 (old default) 686 steps/s; 1: 692; 2: 803; **4: 862 (update 9.6 s)**. `train.py` now sets
  4 (`G2E_TORCH_THREADS` overrides). The cores are saturated, so two trainings in parallel don't help.
- **Times at ~860 steps/s:** 3M ≈ 58 min, 20M ≈ 6.4 h.

## 2. Reward and training-loop review

### 2.1 Bugs fixed in the base (not levers)
- **Ramp bug (FIXED 2026-10-06):**
  - `PENALTY_STEPS` and `DR_RAMP_STEPS` (5e5) counted one env's own steps, with 8 envs. Every ramped penalty (smoothness, heading,
    height, power, ...) and all domain randomization therefore reached full strength only at **4M total steps**, and
    `step_counter_session` restarted at 0 in every new env, so **every `--from` continuation re-ramped from zero**.
  - Consequences: every 3M screening round so far trained and was judged at ~0.75 strength; every 3M stage of V2's chain re-ramped. The
    misleading 3M screen in V2.1's yaw round is consistent with this.
  - Fix:
    - `opencat_gym_env.RAMP_MODE` "total" (default; `G2E_RAMP_MODE`) with `RAMP_TOTAL_STEPS` 1e6 (`G2E_RAMP_TOTAL_STEPS`).
    - Env methods `set_ramp_steps()` / `_ramp()`.
    - `train.py`'s `RampSync` callback calls `set_ramp_steps(total)` at training start and before each rollout.
    - `--from` continuations start at full strength; `--re-ramp` restores the old restart.
    - Envs no trainer reports to (probes, benchmarks, `run_pipeline` scoring, other trainers like `train_climb.py`) keep the old per-env
      ramp, so their behaviour is unchanged. `G2E_RAMP_MODE=legacy` forces the old ramp everywhere.
  - Checked: through `SubprocVecEnv` + Monitor wrappers the ramp reads 0.0, then 0.5 after `set_ramp_steps(5e5)`. 20k-step smoke runs
    (fresh and `--from` V2.1) both train; their outputs were deleted.
  - Effect: fresh runs now reach full penalties/DR ~3M steps earlier than any past run. C0 shows whether that hurts learning.
- **Inconsistent evaluation setup (to fix in Phase 2).** The G2 setup lives in four places that disagree:
  - `run_pipeline.BASE` (env vars, incl. `CMD_SEND_EVERY_N` 3, `BODY_MASS_SCALE` 1.12, `IMU_BIAS_DEG` 2, `JOINT_OFFSET_DEG` 2,
    `SLOPE_TARGET_PROB` 0.3, `SERVO_RATE_LIMIT` 137, `FAC_YAW_TRACK` 9).
  - `run_pipeline._score_checkpoint` and `phase_c_report.py` hard-code hold 16 / rate-zero / path "i" / send-every 3 / episode 250.
  - `benchmark_decathlon.py --hw i` sets only hold / rate-zero / path. Send-every, mass, bias, offset and payload come from the shell's env
    vars, otherwise module defaults (send-every 1, mass 1.0).
  - `drift_probe.BASE_ENV`.
  - Fix: one `g2_profile.py` that training and every scorer import.

### 2.2 Validated tuning baked straight into the base recipe (no later tuning run)
- `FAC_RESID_SMOOTH` 8.2 → **10.5** (the V2 → V2.1 lever: T1.1 yaw RMS 5.24 → 4.02 deg, drift 3.10 → 1.75 deg, T5.2 improved).
- `FAC_YAW_TRACK` **9.0**, `CMD_SEND_EVERY_N` **3**, ledge ceiling **35 mm** (`LEDGE_RANDOMIZE`), `SLOPE_TARGET_PROB` **0.3** (V2 / V2.1 recipe).
- Carpet: the V2 recipe's light 10% carpet exposure stays only if C0 shows it costs nothing; carpet is never a gate (user).
- 422 g `case` payload; servo speed / contact / battery from Phase 1; `HARD_SCALE` 1.10 (hardest levels +10%: shoves, slope range,
  overheat cutback, obstacle/rubble heights; nominal walk unchanged) in the final stage and the 20M.

### 2.3 Reward levers (each screened alone)

| # | Change | Why |
|---|---|---|
| R1 | **Left/right mirror symmetry** as a mirror-consistency loss (APPROVED; spec §2.5) | Removes the learned constant bias (V2.1's BL hip +7 deg); a bias can then only be corrected through feedback |
| R2 | **Heading reward shape:** replace `FAC_HEADING·err²` with a bounded tracking reward `exp(-(err/10°)²)` | A real gradient near straight |
| R3 | **Servo-feasibility penalty:** soft penalty on commanded joint speed above the measured servo ceiling (H13: 26% of `base1_20m`'s commands exceeded 137 deg/s) | Commands the servos can follow; smaller sim/real gap |
| R4 | **Potential-based balance reward** γΦ(s') - Φ(s) with Φ = -(tilt + k·tilt rate); review `FAC_SURVIVE_BONUS` (scales with peak tilt) | `FAC_BALANCE` pays every drop in tilt and never charges the rise (code: `max(0, prev_tilt - tilt)`), so a wobble is paid on each down-swing. Only active above 0.5 rad |
| R5 | **Bounded trot term:** `FAC_GAIT_SYMMETRY` = `-Δdiag_a·Δdiag_b` (raw product of joint velocities, unramped); use a bounded correlation, or rely on the contact-based `FAC_FOOT_PHASE` | Bigger, faster swings earn more, against every smoothness term |
| R6 | **Softer footfalls:** small penalty on foot vertical speed at touchdown | Impacts drive roll swing. Only if Phase 1 reproduced G2's roll swing |
| R7 | Discount γ 0.99 → 0.995 (horizon 1.25 → 2.5 s) | Low priority; only if K3 still drifts on long walks |

Not proposed again (failed before): raising `FAC_STABILITY` / `FAC_YAW` (over-damped, rtune_r2); a fall penalty (`-15` collapsed entropy);
the phase slow-down and imitation fade (PPO diverged); a stride reward (gamed).

### 2.4 Yaw levers

| # | Lever | Notes |
|---|---|---|
| Y1 | Yaw-sign fix on the Pi | Required; code (§0 next step 1) |
| Y2 | Explicit heading-error input (sin, cos of heading - commanded heading) + a yaw-free tilt input instead of the raw quaternion | Changes the observation size, so fresh runs only (fine: V3 is fresh). The Pi's `residual_policy.py` must build the same inputs, behind the policy's `.onnx.json` sidecar |
| Y3 | Mixed episode lengths (25% of episodes at 1000 steps) | v2.2 R2 (all 1000) hurt at 3M, so mix rather than replace |
| Y4 | Turn-command curriculum `G2E_TRAIN_YAW` ±0.15 rad/s, widened to ±0.45 in the chain | **Only if Phase 1's turning gate passes.** `TURN_BLEND` (wkF → wkL/wkR base) exists, dormant |
| Y5 | Persistent asymmetry randomization per episode: a stuck servo (promote `_motor_max` / drift_probe's `clip:J:DEG` to a training knob), a weak joint, a zero offset, a mild yaw torque (`G2E_DRIFT_TORQUE` ≤ 0.25; 0.5 was too harsh in v2.2 R1) | Practice steering back against real causes |
| Y6 | Heading hold on the Pi: turn command = -k × heading error | Pi code only; needs Y4 |

### 2.5 Mirror symmetry (R1) spec (approved: a loss, not data augmentation)
- **Loss:** a small PPO subclass (flag-gated, e.g. `G2E_MIRROR_LOSS=<weight>`) adds `w · ||μ(M_s(s)) - M_a(μ(s))||²` on the policy mean,
  plus `w_v · (V(M_s(s)) - V(s))²`, to the PPO loss. Data augmentation was rejected: it needs probabilities for samples the policy never
  took, which can destabilize PPO. The exported ONNX keeps the same inputs/outputs; the Pi is untouched.
- **Joint permutation** (URDF order 0 FLsh 1 FLel 2 FRsh 3 FRel 4 BRhip 5 BRkn 6 BLhip 7 BLkn): `[2,3,0,1,6,7,4,5]`, no sign flips (all
  joints share one sign convention; the `wkF` mirror check above used no sign change).
- **Observation mirror** (layout: `state_robot` = quat(4) [x,y,z,w], roll/pitch rate(2), proj_grav(3), time phase(1), tilt history(12×2
  roll,pitch), ang_acc(2), cmd(2) [fwd, yaw]; then `angle_history` 30 frames × 8 joints):
  - quat → (-x, y, -z, w) (mirror across the body's x-z plane: roll and yaw flip, pitch stays)
  - rates (r, p) → (-r, p)
  - proj_grav (gx, gy, gz) → (gx, -gy, gz)
  - phase t → (t + 0.5) mod 1
  - tilt pairs (r, p) → (-r, p)
  - ang_acc → (-, +)
  - cmd (fwd, yaw) → (fwd, -yaw)
  - each 8-joint history frame → permuted
  - Y2's heading inputs: sin → -sin, cos unchanged.
- **Check before use:** a unit test that mirroring twice is the identity, and that `M_s` of a real sim state at phase φ is close to the
  sim state of the mirrored motion at φ+50 (wkF matches to 4.2 deg).
- The action is a residual on `wkF[phase]`; since `M(wkF[φ]) ≈ wkF[φ+50]`, permuting the residual is consistent.

## 3. Benchmark v4
- One `g2_profile.py` for every scorer; `BENCH_VERSION` 4; V2.1 re-scored on it as the reference.
- **Tier 0 real-match cells:** the 12.5 s calm walk as G2 is tested (heading change, speed, speed decay, roll/pitch std, each compared with
  the latest real baseline), and a 60 s endurance walk.
- **Fault cells:** FL shoulder capped at 42 deg (servo 8 model); motor force -10% (battery sag); a constant yaw disturbance (heading hold).
- **New measures:** L/R asymmetry of the mean commanded joints (catches a learned bias); share of commands above the servo ceiling.
- 40 episodes per decision cell (20-24 is about ±15 points of noise); same seeds for both gaits.
- The +10% hard ladder (`--hard-scale`: T2.2 12 → 13.2 deg, T3.2 10 → 11, T5.3 40 → 44 mm, T8.1 shoves 1.00 → 1.10, T9.1 cutback 0.60 → 0.66,
  T11.2); labeled not comparable with older runs.
- A turn-tracking cell if Y4 is trained (`resilience_command_dynamics.py`'s sustained-arc has the logic).
- Carpet (T10.1) reported, never gated.
- **Parallel scoring (optimization 2):** run cells in parallel processes between trainings (same seeds and episode counts). Target: ~15 min
  → ~3-4 min per round.

## 4. The plan

**Rules:**
- Screening runs are fresh, 3M, one lever each, judged against the 3M control C0 on the same setup.
- Continuations happen only inside the new lineage (V2's staged method).
- The 20M run is the last training run, starts only on the user's go, and has gait checks at 3M / 5M / 10M (no separate dress rehearsal).
- Hardware check-in before the 20M.
- Give timing estimates with 12-hour ET clock times when launching anything; arm a watcher on every run.

**Approved speed optimizations** (no effect on test or training quality):
1. 4 torch threads in `train.py` (done): +26% throughput.
2. Parallel benchmark scoring (§3).
3. Run the full combination K3 first; run K1/K2 only if K3 fails, to find which group caused it.
4. Reuse K3 as stage s0 (it's a fresh 3M run on the same flat starting course V2's s0 used), so one stage disappears from the chain.
5. Overlap work: I code Phase 2 while the user does Phase 0 hardware; Phase 1 starts on the 10-06 walk data and waits only for the servo
   speed and turn-rate numbers.

Not adopted: early-stopping collapsed screens at 2M (optimization 6, left out by the user); bigger PPO batches or fewer epochs, shorter
screens, fewer scoring episodes (all change quality).

### Phase 0: real measurements (user on G2, about 2 h total; me: code)
1. Yaw-sign fix + unit test (§0 next step 1); roll/pitch sign check: hand-tilt G2 (nose down, then right side down, G2 upright, never on its
   back) under `python -m pi_pipeline.gait.run_gait --probe-imu`, compare with PyBullet's conventions (roll + = right side down about +x;
   check in PyBullet first).
2. Six V2.1 walks (`bash tools/g2_baseline.sh start 6 <label>`, needs `G2_PI`) **with distance taped**, plus six scripted `wkF` walks
   (`python pi_pipeline/gait/run_gait.py --openloop --cycles 10 --log ~/g2_runs/<x>.csv`). The 10-06 walks already cover V2.1 except
   distance.
3. Real turn rate of the firmware turns: `python pi_pipeline/gait/fw_skill_log.py kwkL --seconds 10 --log ...` and the same for `kwkR`.
4. Servo speed (H13): the step-test mode (§0 next step 2); phone slow-motion video if feedback is too coarse.
5. Servo 8 replacement (user, in parallel, not blocking training); then repeat the six V2.1 walks.

### Phase 1: calibrate the sim (me, ~half a day, no training)
- Change one parameter at a time: payload `case` → servo speed (step 4) → foot friction/contact → motor strength vs pack voltage.
- Score V2.1 and scripted `wkF` against the Phase 0 walks with the real-match probe (12.5 s, `drift_probe.py` style).
- Targets: roll std, pitch std and speed within ~20%; scripted `wkF` curving the same way as on G2; **V2.1 turning right**, which would confirm
  §1.2.
- **Turning gate:** the calibrated sim turns `wkL`/`wkR` open-loop at ≥ 50% of their real rate (Phase 0 step 3) → Y4/Y6 stay. Otherwise
  drop them: turns stay firmware tokens, and straightness rests on R1 plus heading feedback.
- Output: `g2_profile.py`. **If the sim can't be matched: stop and report before any training.**

### Phase 2: code (me, ~1 day, overlaps Phase 0)
- `g2_profile.py`; the base-recipe values (§2.2); benchmark v4 + parallel scoring (§3).
- Levers, each behind a flag that is inert when off: Y2, Y3, Y5, R1 (PPO subclass + mirror maps + tests), R2, R3, R4, R5, R6.
- A round runner like `phase_v22.py` (queue file, scoring vs C0, pass bars below, watcher-friendly log lines).
- Re-score V2.1 on v4 (~10 min with parallel scoring); inertness smoke checks; commit.

### Phase 3: screening (unattended, ~12 h; +2 h if K3 fails)
- **C0 control:** calibrated profile, sign-correct, ramp fix, base recipe. Gate: T1.1 falls ≤ 0.15 at 3M.
- Single-lever rounds (fresh 3M each, vs C0):

| Round | Lever | Pass needs (plus no regression) |
|---|---|---|
| S1 | R1 mirror symmetry | Joint L/R asymmetry near 0; 12.5 s heading ≤ C0 |
| S2 | Y2 heading inputs | Heading in the real-match and yaw-disturbance cells ≥ 30% better |
| S3 | R2 heading reward shape | Same as S2 |
| S4 | Y3 mixed episode lengths | Speed decay and 60 s survival better |
| S5 | Y4 turn curriculum *(only if the turning gate passed)* | Turn tracking works; straight walk unchanged |
| S6 | Y5 asymmetry randomization | Servo-fault and yaw-disturbance cells better |
| S7 | R3 servo-feasibility penalty | Over-ceiling commands down; real-match roll/pitch no worse |
| S8 | R4 potential-based balance | Shove / gauntlet falls no worse; calm wobble lower |
| S9 | R5 trot-term normalization | Smoothness (yaw RMS, jitter) better; trot correlation kept |
| S10 | R6 softer footfalls *(only if Phase 1 reproduced the roll swing)* | Real-match roll std lower |

- **Calm-walk bar for every round:** calm falls ≤ min(0.15, C0 + 0.05); speed ≥ 90% of C0. 24-episode fall rates carry about ±15 points of
  noise; don't chase small differences.
- **K3 = every passing lever together** (fresh 3M). It must beat C0 on the levers' targets with no regression. If it fails, run K1 (passing
  yaw levers S1-S6) and K2 (passing smoothness levers S7-S10) to find the group, then drop the lever whose removal recovers it (one 3M run
  per suspect). R7 only if K3 still drifts on long walks.

### Phase 4: staged chain on the K3 recipe (~6 h, unattended)
- **K3 is stage s0 (flat).** Each later stage is a 3M continuation at full ramp (`--from`, default finetune LR 3e-5, target KL 0.05, as
  V2). Each gate re-scores every earlier stage's cells, with one retry (as `phase_r_sequential.py`).
- Stages:
  1. s1 transitions (`SURFACE_TRANSITION_PROB` 0.25)
  2. s2 step (`SURFACE_TRANSITION_STEP_M` 0.012)
  3. s3 snag (`SNAG_OBSTACLE_PROB` 0.20)
  4. s4 ledges (`LEDGE_HEIGHT` 0.035, `LEDGE_PROB` 0.20, `LEDGE_RANDOMIZE`)
  5. s5 turn range ±0.45 rad/s (if Y4)
  6. s6 full-strength asymmetry + payload variation + `HARD_SCALE` 1.10
- No carpet stage (carpet gets its own session).

### Phase 5: hardware check-in (user, ~1 h)
- The final stage's policy goes on the Pi via `export_onnx.py` + sidecar, NOT as the default (`run_gait.py --policy <onnx>`).
- Six walks next to the latest V2.1 baseline (after the servo swap if done); with Y4, also the Pi heading hold (Y6).
- If it's worse on G2 than V2.1: stop and decide with the user.

### Phase 6: 20M consolidation (on the user's go, ~6.4 h) — the last training run
- One 20M continuation of s6 with the full recipe.
- **Gait checks at 3M, 5M and 10M** against the end of the chain: T1.1, the real-match cells and every stage's cells. They score in
  parallel without pausing training; a regression stops the run.
- No tuning run is planned after it.

### Phase 7: score, promote, deploy
- Benchmark v4 on both ladders vs V2.1; `validate_deploy.py --onnx`; six real walks.
- **Promote if:** calm falls ≤ 0.15; real 12.5 s heading change ≤ 30 deg; no category worse than V2.1 by more than 0.10 in falls; speed
  ≥ 95% of V2.1.
- Then name it `Release_CandidateV3`, set `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py`, rsync the `.onnx` + `.onnx.json`
  (and the Y2 input code if used), and update STATUS, this page and the memory notes.

**Totals:** ~25 h of training wall time (was ~38 h before the optimizations), ~3-4 days elapsed. The user's hands-on time is Phase 0
(~2 h) and Phase 5 (~1 h).

## 5. Decisions (user, 2026-10-06)
- Everything learned from tuning goes into the base training; no planned tuning runs after the 20M.
- No separate dress rehearsal: one 20M run with gait checks at 3M / 5M / 10M.
- Carpet out of every gate; a carpet skill gets its own focused session later.
- Fix the ramp bug (done).
- Turning: measured gate in Phase 1 (approved).
- Mirror symmetry: build it as a loss (approved).
- Speed optimizations 1-5 approved; 6 (early stop) not adopted.
- Servo 8: unconfirmed; the user replaces it during training; re-test afterwards.
- v2.2 closed (no round passed); its tools carry over (drift probe, `case` payload, `HARD_SCALE`, `DRIFT_TORQUE`).

## 6. Files and tools from this session (2026-10-06)
- `rl_training/opencat-gym/opencat_gym_env.py`:
  - ramp fix (`RAMP_MODE`, `RAMP_TOTAL_STEPS`, `set_ramp_steps`, `_ramp`)
  - probe-only `_obs_yaw_sign` hook (default 1.0)
- `rl_training/opencat-gym/train.py`: `RampSync` callback, `--re-ramp`, 4 torch threads (`G2E_TORCH_THREADS`).
- `rl_training/opencat-gym/drift_probe.py`: levers `yawflip`, `yawzero`.
- `rl_training/opencat-gym/replay_real_obs.py`: real walk logs → policy, offline (as logged / yaw negated).
- `rl_training/opencat-gym/train_throughput.py`: collection vs update timing.

## 7. Gotchas
- Scripts that start `SubprocVecEnv` workers must run from a file, not stdin (workers re-import `__main__`).
- `G2E_` env vars set training knobs (`_g2e` in the env). `DR_EVAL_FULL` is a module attribute, not an env var.
- `G2E_CMD_PATH=` (empty) means the default `""` (ideal path); `drift_probe.py` only sets defaults it doesn't find in the environment.
- Kill runners by pid, never `pkill -f <name>` (it also kills watchers whose command line contains the name).
- Closing the Mac's lid pauses training; a Monitor expires after 30 min (re-arm it).
- `trained/` is gitignored; snapshot result JSONs into `docs/rl/` when they back a decision. Never commit GIFs.
- Never put G2 on its back (Pi/BiBoard exposed); unloaded tests = G2 held upright in the air.
