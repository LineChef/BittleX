# V3 retrain plan: calibrate the sim to G2, bake every tuning lesson into one fresh gait (approved 2026-10-06)

**Status: APPROVED by the user 2026-10-06** (incl. the turning gate, mirror symmetry and speed optimizations 1-5). This is the working plan
and the hand-off: a new session should be able to resume from this page alone. Background: [`v22-handoff.md`](v22-handoff.md) (the drift
campaign this replaces), [`hw1-log.md`](hw1-log.md) (how V2 / V2.1 were trained), [`real-walk-log.md`](real-walk-log.md) (real data).

**Principle (user):** everything learned from tuning goes into the base training; **no tuning runs after the 20M consolidation run.** Each
new lever is screened alone, the ones that pass are combined and built into a staged chain, and the 20M run is the last training run.
Tuning runs stay possible later if the result needs them, but none are planned.

## 0. Where to resume (state at ~9:10 PM ET, 2026-10-06: queue running C0 done, S1 at 3M, then C0b, S2 ...; G2 charging)

### Update, 2026-10-07 (queue order changed; benchmark v5; read this before the hand-off below)

- **Queue order now:** S3 (running), then the seed replicates (`kind: replicate`, `G2E_SEED` 43 and 44: control, S1, S2 at each), then the combined S1+S2 recipe at seeds 42, 43 and 44, then S4-S10, K3 and the stage chain (no pause after the replicates: the user asked to run straight through; decisions made along the way are in [`v3-decisions-log.md`](v3-decisions-log.md)), then the `report` job, then the `hardware_checkin` pause, then the 20M. Replicate runs are not screens: they never feed K3's lever list, and they are read by hand (the runner prints no verdict). `train.py` takes the PPO seed from `G2E_SEED` (default 42).
- **Benchmark version 5** (`benchmark_v4.py`, module name unchanged): adds the difficulty-level ladder (`--ladder`). Training's per-category levels (terrain, ledge, slope, fault) are scored on the finished policy at levels 0.25 / 0.5 / 0.75 / 1.0 plus a +10% hard rung, in the final stage's world (`g2_profile.env_for(..., stage="s6_full_strength")`), with the training probe's own score, relative score and 0.80 threshold. The T and N cells are unchanged, so version 4 results compare cell for cell.
- **The `report` job** (`phase_v3.do_report`, `v3_report.py`) runs right before the hardware check-in: V2.1, the control (`v3_c0b`), K3 and the last finished stage are scored on all cells plus the ladder (about 10 min each), then `trained/v3_report/pre20m_report.html` is written (promotion check against V2.1, ladder charts, every cell, straightness, seed replicates, training history, caveats). Publish it as an Artifact for review before deciding on the 20M. Test it without the real policies: `python v3_report.py --demo --out /tmp/x.html`.

### Hand-off, evening of 2026-10-06 (read this first in a new session)

**What is running (Mac, `rl_training/opencat-gym/`).** The V3 queue (`python phase_v3.py run`, log `trained/phase_v3.log`, queue `trained/v3_queue.json`): `v3_c0` (control) is DONE and passed
the flat bar; `v3_s1_mirror` is training (about 9:25 PM ET done, 9:30 PM scored); `v3_c0b` (a second control with the 12-episode probe) is queued right after it, then S2 ... S10, K3, the
stage chain, the `hardware_checkin` pause, the 20M. S5 (turning) is skipped because the turning gate failed. Rough schedule: C0b done about 10:40 PM, hardware check-in about 2:20 PM Wednesday,
20M done about 10:20 PM Wednesday. **Restarting the runner is safe** (a job already training is resumed, not relaunched): kill the runner by its exact pid (`ps aux | grep "[p]hase_v3.py run"`), relaunch
with `(nohup ../../.venv/bin/python phase_v3.py run >> trained/phase_v3.stdout 2>&1 &)`. Never `pkill -f`, never put `train.py --tag` text in a shell command line (the runner's guard matches it), and never
`ps | head -1 | kill` in the same command that launches things (it killed its own shell once). Screens are auto-judged against `v3_c0`; compare S2 onward against `v3_c0b` by hand (the probe differs: 6 vs 12 episodes).
Watchers (Monitor) expire after 30 min: re-arm one on `trained/phase_v3.log`. Probe results per run are in `trained/<tag>_console.log` (`[probe]` lines); `phase_v3.py status` summarizes finished jobs.

**What the real-G2 testing found today** (details, tables and raw logs: [`real-walk-log.md`](real-walk-log.md), data in `v3-data/`):
1. V2.1's right drift is mostly hardware: the replaced FL shoulder servo cut it from about +142 to about +36 deg per 12.5 s; the Pi yaw sign made no difference. A scripted firmware turn gait (`kwkL` / `kwkR`, no policy) shows the same bias (-12.1 / +18.6 deg/s, so a steady +3.3 deg/s rightward push).
2. The sim cannot turn the firmware turn gaits (7% / 3% of the real rate), so the turning gate FAILED: Y4 / Y6 / S5 are off, turns stay firmware tokens.
3. **The Pi-side heading hold's lever has the OPPOSITE sign on G2 from the sim: longer RIGHT strides turn G2 LEFT.** The first A/B (hold on +82 deg vs off +65) steered into the drift. Fixed-stride-difference walks (old sign: u = -0.2 / 0 / +0.2 gave +115 / +90 / -29 deg) and a sweep near the cancel point (new sign: u = -0.10 / -0.15 / -0.20 gave +64 / +11 / +1 deg) measured it. The code now defines u > 0 as longer LEFT strides = a right turn (`heading_hold.py`, tests pin it). Never take a stride-steering direction from the sim (the sim's own sign is still unexplained).
4. Large stride differences are unsafe: at u of -0.25 to -0.38 the back-right leg lands flat on the floor (near a fall). `heading_hold.JOINT_RANGE_DEG` now clamps the scaled shoulders / hips to the reach the unscaled walk uses plus 6 deg. Keep |u| <= 0.25-0.30 and watch.
5. The drift GREW through the evening (+44 -> +65 -> +90 -> +178 deg per 12.5 s at u = 0) while the resting pack fell from 8.20 V to 7.93 V, so every closed-loop iteration chased a moving target. Closed-loop runs (feed-forward -0.17..-0.29, kp 0.01, ki 0.001, limit 0.25-0.38) never settled: the output sat at its limit, and the user saw hard left turns late in several runs. The integral term wound up (now clamped, `i_lim`), and the controller's gains were designed for a lever 4x weaker than the real one. The yaw log agreed with what the user saw at fixed u = 0 (right) and u = -0.28 (straight, then left from the 6th step), but not in iterations 3-4; the log's final yaw also jumps when G2 is picked up at the end of a run (ask what was seen; the fall guard only trips at 60 deg of tilt).
6. Other changes: G2 now rests after every run (`run_gait` restores balance first and sends the rest last; the old order left him standing); logs are line-buffered; both low-battery alarms are set to about 50% on the Pi only (`G2_BATTERY_LOW_V=8.0`, `G2_PI_WARN_FRACTION=0.50`) and were heard; the BiBoard's onboard voice module reacts to spoken commands during tests (one stray command made G2 fall).

**Next steps, in order.**
1. User charges the pack (full is about 8.3-8.4 V; check with `check_serial send P` after stopping `g2-voice`) and reboots the Pi (its battery count restarts at boot).
2. **Charged-pack recheck** (the TODO box below): `bash tools/g2_baseline.sh start 12 recheck --const-u=0,-0.20,-0.28 --hold-umax 0.30 --reset-s 10 --lead-s 5`; the user calls left / right / straight per run; compare with the logs.
3. **Dial the correction in, one run at a time with an adjustment between runs:** `python3 tools/g2_dial_iter.py hold N FF KP KI UMAX` (or `const N U`) prints the result of one run; start from the measured cancel point (about u = -0.19 on a charged pack, to be re-measured), keep UMAX <= 0.30, KP about 0.01, KI small, and ask what the user saw. Goal: a straight path every time (final heading within about +-10 deg, small spread), at one battery level. Only then decide whether the hold goes into the sim (the user is unsure it should).
4. Remaining Phase 0 items: six scripted `wkF` walks (`run_gait.py --openloop --cycles 10 --log ...`), the full-charge V2.1 baseline repeat (`g2_baseline.sh start 6 <label>`), distance taped; the servo step / static tests need the Pi off the lid (USB).
5. Parked: FL shoulder still stops about 44 deg going up (new servo, not mechanical), BR knee reading, FL knee short going up, the sim's steering sign, carpet (own session).
6. Training: read S1 against C0 (both 6-episode probe), then C0b, then the screens against C0b; re-arm watchers; the hardware check-in pause waits for `trained/v3_go_hardware_checkin`.

**Standing rules** are in `CLAUDE.md` and the memory notes (no attribution trailers, never echo `.env`, G2 not "the robot", times in 12-hour ET with a timing estimate for every launch, defer to the user on hardware, work on `development`). Tools added today: `tools/g2_turns.sh`, `tools/g2_dial_iter.py`, `pi_pipeline/gait/turn_runs.py`, `rl_training/opencat-gym/turn_gate_probe.py`; `g2_baseline.sh` takes `--hold on|off|abba`, `--const-u`, `--hold-ff/-kp/-ki/-umax`, `--reset-s`, `--lead-s`.

> **TODO next time G2 is online after charging (2026-10-06 evening):** redo the three-point steering check on a FULL pack before any more heading-hold tuning: fixed stride difference u = 0, -0.20, -0.28 (corrected sign, joints clamped by `heading_hold.JOINT_RANGE_DEG`), `g2_baseline.sh start 12 recheck --const-u=0,-0.20,-0.28 --hold-umax 0.30` (without `--hold-umax` a fixed u beyond 0.20 is clipped to 0.20), user watches and reports left / right / straight per run. The right drift at u = 0 grew from +44 to +178 deg per 12.5 s as the resting pack voltage fell from 8.20 to 7.93 V, so everything tuned below about 8.0 V is suspect. Also confirm the yaw log matches what is seen (the end-of-run yaw jumps if G2 is picked up).

**New result (2:55 PM): the replaced FL shoulder servo removed most of the drift** (about +142 -> +40 deg per 12.7 s; the interleaved yaw-sign test showed the sign
fix is not the cause: NEW +42 vs OLD +37). Record: [`real-walk-log.md`](real-walk-log.md) "After replacing the front-left shoulder servo". Consequences: (1) the real
post-swap baseline (heading +40 +- 27 deg, roll std ~5.0, pitch ~2.5, distance ~4 ft 10 in) is now the calibration target, not the broken-servo walks; (2) a stuck servo is a
confirmed real failure mode, which supports the N3 cell and the faults lever (Y5); (3) the rest of the plan stands (robustness, smoothness, heading hold, sim calibration).
The direct servo readings on the new servo (USB to the Mac) are next; then the rest of Phase 0.

**Phase 2 code is DONE and committed** (details §6); nothing is training; the Mac is idle. The user replaced and recalibrated the FL shoulder servo
(servo 8) at about 2:15 PM and is about to do the Phase 0 hardware steps. G2's Pi was not yet reachable at 2:25 PM (still powering up).

**Done:**
- Investigation, plan, ramp fix, 4 torch threads, the yaw-sign fix (deployed to the Pi, `g2-voice` restarted).
- Servo step-test tool (`tools/servo_step_test.py`); the Phase 2 code: `g2_profile.py`, `benchmark_v4.py`, `phase_v3.py` (rehearsed end to end on
  tiny jobs: training, parallel scoring, pass/fail, combo, stage chain, resume), `mirror.py`, and all levers behind flags (inert when off, checked).
- **Two findings that changed the plan** (§1.3, §2.3): (1) the sim's 137 deg/s servo-speed limit is the dominant sim-vs-G2 gap: at ~250 deg/s the
  sim's roll swing matches G2's and V2.1 turns RIGHT; (2) `drift_probe.py` did not force the command, so its speeds were wrong (now fixed; the old
  JSONs are marked superseded). Also: the trot-symmetry term and the joint-smoothness terms are inert, so R5 was revised.
- Mirror-loss cost measured: 757 steps/s vs 892 plain (+18% time) after restructuring to one forward pass; a test checks the single pass equals SB3's.

**Next, in order:**
1. **User, Phase 0 hardware (about 2-2.5 h; commands in §4 Phase 0):** roll/pitch sign check, `servo_static_test.py` on the new servo, **`servo_step_test.py`**
   (shoulder and knee), six V2.1 baseline walks with distance taped, six scripted `wkF` walks, `kwkL` / `kwkR` turn rates. Then record the results in
   `real-walk-log.md` and copy the raw logs into `real-walk-data/2026-10-0X/`.
2. **Me, Phase 1 (about 4 h after the data):** calibrate the sim (servo speed first, then foot contact, motor strength vs voltage), decide the turning
   gate and the roll-match flag, write the calibrated values into `g2_profile.CALIBRATION`, re-score V2.1 (`phase_v3.py` does it: `ref`).
3. **Me, start the screening runner:** `cd rl_training/opencat-gym && ../../.venv/bin/python phase_v3.py init && nohup ../../.venv/bin/python phase_v3.py run &`
   (create `trained/v3_turning_gate_pass` / `trained/v3_roll_matched` first if Phase 1 earned them), and arm a watcher on `trained/phase_v3.log`.
4. Hardware check-in (the runner pauses: `touch trained/v3_go_hardware_checkin` continues it), then the 20M, then Phase 7.

## 1. Findings (2026-10-06)

**The evidence (tests, numbers, commands) is recorded in [`real-walk-log.md`](real-walk-log.md) "Why V2.1 drifts right (investigation,
2026-10-06)"; raw results in [`v3-data/`](v3-data/README.md).** Summary:

### 1.1 The yaw-sign mismatch is real but doesn't explain the drift
- The Pi fed the policy yaw with the opposite sign to the sim's (firmware + = right, PyBullet + = left). V2.1 doesn't use heading
  (yawflip / yawzero sim tests: +9.4 / +8.4 / +9.1 deg, identical joints), so this didn't cause the turn.
- **Fixed anyway** (`run_gait.POLICY_YAW_SIGN`, `c292431`), because a heading-aware policy would steer the wrong way. Offline replay of
  the six 10-06 walks reproduces 100% of the logged commands, so the Pi ran V2.1 exactly.

### 1.2 What the drift is, as far as the data goes
- **Leading hypothesis (not yet confirmed):**
  - The scripted walk is left/right symmetric, but it curves left in the sim and on G2.
  - V2.1 learned a constant counter-steer: BL hip ~60 vs BR ~53 deg, in the sim and on G2.
  - That correction nets +9 deg (left) in the sim, but about 140 deg right on G2's real floor.
- Phase 1 checks it: a calibrated sim should turn V2.1 right too. The structural fix is mirror symmetry (R1).
- **Servo 8 is NOT confirmed bad;** the user is replacing it, then the walks are repeated.
- v2.2's last round (R3, 3M control, case payload): calm falls 0.08, speed 0.040, heading error under the reference disturbance 39.8 deg.
  All three v2.2 rounds failed (`v22-data/`).

### 1.3 Gaps between the sim and G2 (corrected 2026-10-06 afternoon)
- **Correction:** the first gap numbers (speed 0.053, "slows down past 3.1 s", servo-limit comparison) came from `drift_probe.py`, which did not
  force the commanded speed, so the env redrew the command ~9 times per 1000 steps. Re-measured with a forced command: V2.1 walks 0.089 m/s over
  12.5 s with no slow-down (G2 ~0.118, so ~25% short, not half). `drift_probe.py` now forces the command; the old JSONs are marked superseded.
- **The sim's servo-speed limit is the dominant gap.** Sweep of `SERVO_RATE_LIMIT_DEG_S` (N1, 20 episodes, [table in the log](real-walk-log.md)):
  at 137 (assumed) roll std 2.6 deg and a +9 deg LEFT drift; at 250 (the firmware's own easing) roll 5.9 (G2 5.7-6.2) and a -11 deg RIGHT turn;
  with no limit roll 6.5 and -23 deg. 137 was borrowed from another project and never measured on G2. Pitch overshoots at 250 (4.0 vs 1.9-2.7),
  falls are 10% (G2 0 / 6) and the turn is still far short of -142: more parameters to calibrate (foot contact, motor strength).
- **Phase 0 step 4 (the servo step test) is therefore the most valuable measurement.** If G2's servos keep up with the firmware's 250 deg/s, the
  limit goes to ~250 or off and V2.1's drift appears in the sim, so the sim can then be used to fix it.
- Episode length: training episodes AND every benchmark cell were 250 steps (3.1 s); G2 walks 12.5 s to minutes (benchmark v4 adds long cells).
- Payload: the 422 g profile matters little in the sim (377 g gives the same speed and roll); it is in the profile now.
- Carpet: the sim's T10.1 passes; every gait fails on G2's carpet (guessed model, H10). Not gated.
- Battery sag: 0.3-0.45 V under load; the sim has a motor-strength knob for it now (N4 cell, `MOTOR_SCALE_*`).

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
Measured reward budget of a calm V2.1 walk (per step, penalty ramp full; 1500 steps): imitation +15.3, speed +4.3, speed-track -0.72, foot-phase
-0.69, jitter -0.36, progress +0.30, arm contact -0.11, residual smoothing -0.10, residual cost -0.09, body stability -0.06, power -0.016, upright
-0.011, **heading -0.006**, paw slip -0.002, joint smoothness -0.001, trot symmetry +0.001. About 95% of the signal is imitation of `wkF` and
speed tracking, which is why V2.1 stays close to the scripted walk and why small terms (like the smoothing term) still steer it. Lever weights
below were calibrated to these magnitudes on V2.1's walk (R3 5.0 -> -0.31, R6 25 -> -0.12, R2 3.0 -> -0.11 per step).

| # | Change | Why |
|---|---|---|
| R1 | **Left/right mirror symmetry** as a mirror-consistency loss (APPROVED; spec §2.5) | Removes the learned constant bias (V2.1's BL hip +7 deg); a bias can then only be corrected through feedback |
| R2 | **Heading reward shape:** replace `FAC_HEADING·err²` with a bounded tracking reward `exp(-(err/10°)²)` | A real gradient near straight |
| R3 | **Servo-feasibility penalty:** soft penalty on commanded joint speed above the measured servo ceiling (H13: 26% of `base1_20m`'s commands exceeded 137 deg/s) | Commands the servos can follow; smaller sim/real gap |
| R4 | **Potential-based balance reward** γΦ(s') - Φ(s) with Φ = -(tilt + k·tilt rate); review `FAC_SURVIVE_BONUS` (scales with peak tilt) | `FAC_BALANCE` pays every drop in tilt and never charges the rise (code: `max(0, prev_tilt - tilt)`), so a wobble is paid on each down-swing. Only active above 0.5 rad |
| R5 (revised) | **Activate the inert joint-smoothness terms:** `FAC_SMOOTH_1/2` 0.3 -> 15 | Measured 2026-10-06: they contribute -0.0013 per step in a calm walk (the trot term +0.0012 is inert too, so the premise of the first R5 was wrong); the V2 -> V2.1 lever `FAC_RESID_SMOOTH` sits at -0.10 per step and measurably cut yaw wobble, so a smoothness term of that size on the commanded joints is the same kind of lever |
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
1. Yaw-sign fix + tests (**code done**, `c292431`; rsync to the Pi pending); roll/pitch sign check: hand-tilt G2 (nose down, then right side down, G2 upright, never on its
   back) under `python -m pi_pipeline.gait.run_gait --probe-imu`, compare with PyBullet's conventions (roll + = right side down about +x;
   check in PyBullet first).
2. Six V2.1 walks (`bash tools/g2_baseline.sh start 6 <label>`, needs `G2_PI`) **with distance taped**, plus six scripted `wkF` walks
   (`python pi_pipeline/gait/run_gait.py --openloop --cycles 10 --log ~/g2_runs/<x>.csv`). The 10-06 walks already cover V2.1 except
   distance.
3. Real turn rate of the firmware turns: `python pi_pipeline/gait/fw_skill_log.py kwkL --seconds 10 --log ...` and the same for `kwkR`.
4. **Servo speed (H13), the most valuable measurement (§1.3):** `pi_pipeline/.venv/bin/python tools/servo_step_test.py --joint FL-sh` (and a knee, e.g. `--joint FL-kn`; the RL `.venv` has no pyserial) over the
   Mac USB cable, G2 held upright in the air, charged pack; phone slow-motion video as a cross-check. Built 2026-10-06 (`pi_pipeline/gait/servo_step.py` fits it).
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

## 4b. Schedule and timing estimates (written 2026-10-06 2:30 PM ET; times are Eastern)

Per-run costs on the Mac (measured): plain PPO 892 steps/s -> a 3M run 56 min + 4 min parallel scoring = **60 min**; with the mirror loss 757
steps/s -> 66 + 4 = **70 min**; the 20M with the mirror loss 7.3 h (+ the three gait checks, ~7.5 h). A full v4 scoring of one policy takes 5 min on 8
workers (the 60 s endurance cell is the long pole); 2 workers while a training is running.

| Step | Duration | Case A: Phase 0 data in by ~4:45 PM today | Case B: Phase 0 tomorrow, done by ~11 AM Wed |
|---|---|---|---|
| Phase 0 hardware (user) | ~2-2.5 h | Tue 2:30 - 4:45 PM | Wed 8:30 - 11:00 AM |
| Phase 1 sim calibration (me; sweeps run in the background) | ~4 h | Tue 4:45 - 9:00 PM | Wed 11:00 AM - 3:00 PM |
| V2.1 reference + C0 control | 65 min | Tue 9:00 - 10:05 PM | Wed 3:00 - 4:05 PM |
| S1 mirror | 70 min | to 11:15 PM | to 5:15 PM |
| S2, S3, S4, S6, S7, S8, S9, S10 (S5 turn only if its gate passes: +1 h) | 8 x 60 min | to Wed 7:15 AM | to Thu 1:15 AM |
| K3 (all passing levers; also stage s0) | 70 min | to 8:25 AM | to 2:25 AM |
| Stages s1-s4 (+ s5 turn range if kept) + s6 full strength | 5-6 x 70 min | to Wed ~2:15 PM (3:25 PM with turn) | to Thu ~8:15 AM (9:25 AM) |
| Hardware check-in (runner pauses; user ~1 h, me ~20 min) | ~1.3 h | Wed ~2:30 - 4:00 PM | Thu ~9:30 - 11:00 AM |
| 20M consolidation (gait checks at 3M, 5M, 10M) | ~7.5 h | Wed 4:00 - 11:30 PM | Thu 11:00 AM - 6:30 PM |
| Final scoring (both ladders), `validate_deploy`, export | ~30 min | Wed ~midnight | Thu ~7:00 PM |
| Deploy + six real walks (user) | ~1.5 h | Thu 9:00 - 10:30 AM | Fri 9:00 - 10:30 AM |
| **Estimated completion** | | **Thu Oct 8, ~10:30 AM** | **Fri Oct 9, ~10:30 AM** |

Training/scoring wall time, unattended: about **25 h** (S5 skipped) to **27 h** (every lever). **Contingencies** (not in the table): the K3
combination fails and the runner splits it (+2 h20); a stage needs the one retry (+70 min each); a screening round must be repeated or a lever
re-tuned (+60-70 min each); the 20M stops at a gait check and a fallback is taken. Realistic upper bound: add 4-6 h, i.e. Thu Oct 8 afternoon
(Case A) or Fri Oct 9 afternoon (Case B). The human steps (Phase 0, check-in, final walks) set the calendar: unattended work is continuous from the
moment calibration ends. A phase that overruns moves everything after it by the same amount.

## 5b. Decisions and status, evening of 2026-10-06 (user)
- **Pi-side heading hold** (`pi_pipeline/gait/heading_hold.py`, `--heading-hold`, off by default): the first 16-run A/B on G2 (hold on drifted +82 deg, off +65) steered the
  wrong way: the stride-difference lever has the OPPOSITE sign on the real G2 from the sim (fixed-u walks, `real-walk-log.md` "The stride-difference lever has the
  opposite sign..."). Sign fixed in the code; next is a round that dials the correction in (feed-forward near the measured cancel point plus the feedback) until the
  walk is a straight line, then it can go into the sim for **scoring only** (the sim's own steering sign must be understood first).
- **Turning screen (S5):** measure the real `kwkL` / `kwkR` turn rates when the Pi is back on G2, before S5 comes up in the queue; the result sets `trained/v3_turning_gate_pass`.
- **Difficulty curriculum (built, tested and running in the V3 queue since 6:59 PM on 2026-10-06):** the base recipe trains on per-category difficulty levels
  (terrain, ledge, slope, fault) driven by a deterministic probe every 98k steps (6 episodes per category for C0 and S1, **12 from S2 on**; the clean-floor reading was noisy,
  0.23 to 0.90 in C0). A category rises after good probes (relative score >= 0.80), drops at <= 0.50; focus episodes stretch 0.1 above the level, 10% anchor episodes stay at
  level 0, 25% combos use every level. Two paces: +0.10 per good probe for the 3M screens, +0.05 after two good probes for the stages and the 20M (stages start at 0.8, the
  last at 1.0). **Guards** (added after three failed C0 attempts, see below), pure function `curriculum.update_levels`, tested in `test_v3_levers.py`: no level exceeds
  steps / 4M (a time cap); no promotion while the clean-floor score is below 0.5; every category backs off one step if it falls below 0.35.
  Randomization is separate from the levels (time ramp over 4M steps) and the smoothing penalty ramps over 4M with weight 8.2.
  **Failed C0 attempts** (kept in `trained/failed_c0_run1|2|3`, data in `v3-data/c0_failed_run1`): run 1 reward -1000 and 45% falls on flat ground (smoothing penalty with a 1M ramp and
  weight 10.5, randomization tied to the levels); run 2 survived 56% clean (randomization full by 1M) and the probe misread slow walking; run 3 relative scoring hid a declining
  baseline so the levels outran the policy. **Result so far:** C0 (3M steps) passed the flat bar (T1.1 0% falls) with levels ending at 0.74 / 0.74 / 0.47 / 0.69 (terrain / ledge /
  slope / fault; slope was held back), but N2 (60 s) falls 38%. In S1 the levels sit on the time cap in nearly every probe, so the schedule is effectively a linear ramp with the adaptive
  part acting as a brake. Evidence that it beats the old fixed ramp: the 600k-step comparison (mean fall rate 21% against 38% at full difficulty, `v3-data/curriculum_vs_fixed_ramp/`);
  at 3M, S1 against C0. **A second control `v3_c0b` (the same recipe, 12-episode probe) is queued right after S1 so S2 onward compare cleanly;** the runner's automatic verdicts still use `v3_c0`.
  Code: `opencat_gym_env.py` (CATEGORY_LEVELS, LEVEL_EXTERNAL, ...), `train.py` (Curriculum), `curriculum.py`, checks `difficulty_check.py` / `difficulty_audit.py`. The earlier "no ramp for ledges /
  rubble" statement was wrong: most hazards already scaled with a step-count ramp; the changes are the per-category, competence-driven levels and the three severities that ignored the ramp.

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

## 6. Files and tools built 2026-10-06 (all under `rl_training/opencat-gym/` unless noted)
- `opencat_gym_env.py`: the ramp fix; probe-only `_obs_yaw_sign`; every V3 lever behind a default-off flag (`HEADING_OBS`, `LONG_EP_*`, `FAULT_*`,
  `MOTOR_SCALE_*`, `FAC_HEADING_B`, `FAC_SERVO_FEAS`, `FAC_BALANCE_PBRS`, `FAC_SMOOTH_1/2` overrides, `FAC_TOUCHDOWN`) and the Phase 1 calibration
  knobs (`GROUND_FRICTION`, `FOOT_FRICTION`, `MOTOR_FORCE`, `SERVO_KP`, `SERVO_KD`). Checked inert with every flag off (identical rewards and
  observations to the committed version over 753 steps).
- `train.py`: `RampSync`, `--re-ramp`, 4 torch threads, `--mirror-loss` / `G2E_MIRROR_LOSS`.
- `mirror.py`: mirror maps (observation, action), `mirror_gap()`, and `MirrorPPO` (SB3's PPO plus the mirror loss).
- `g2_profile.py`: the one G2 setup (RECIPE, CALIBRATION, LEVERS, STAGES, `env_for`, `scoring_env`).
- `benchmark_v4.py`: the v4 ladder, parallel (`--jobs`), `--env` overrides, `--hard-scale`; ~5 min for all 28 cells on 8 workers.
- `phase_v3.py`: the unattended runner (`init`, `run`, `status`, `run --test` rehearsal).
- `test_v3_levers.py`: mirror-map tests (run with the RL venv). `drift_probe.py` (forced command; `yawflip` / `yawzero`), `replay_real_obs.py`,
  `train_throughput.py`.
- `tools/servo_step_test.py` + `pi_pipeline/gait/servo_step.py` + `pi_pipeline/tests/test_servo_step.py`: the servo speed measurement.
- `pi_pipeline/gait/run_gait.py`: `POLICY_YAW_SIGN` (deployed to the Pi 2026-10-06).

## 7. Gotchas
- **The heading lever's sign:** on the real G2 LONGER RIGHT strides turn him LEFT (measured 2026-10-06); `steer_probe.py` / the sim say the opposite. Never take the direction of a stride-length steering effect from the sim; measure it with fixed-u walks first.
- Scripts that start `SubprocVecEnv` workers must run from a file, not stdin (workers re-import `__main__`).
- `G2E_` env vars set training knobs (`_g2e` in the env). `DR_EVAL_FULL` is a module attribute, not an env var.
- `G2E_CMD_PATH=` (empty) means the default `""` (ideal path); `drift_probe.py` only sets defaults it doesn't find in the environment.
- The env redraws the commanded speed ~9 times per 1000 steps unless `env.set_command()` forces it; every probe and benchmark must force it.
- `evaluate_policy.run_episode` calls any episode that ends after 250 steps "not fell" (`EPISODE_CAP`); benchmark_v4 lifts the cap in its workers.
- Kill runners by pid, never `pkill -f <name>` (it also kills watchers whose command line contains the name).
- Closing the Mac's lid pauses training; a Monitor expires after 30 min (re-arm it).
- `trained/` is gitignored; snapshot result JSONs into `docs/rl/` when they back a decision. Never commit GIFs.
- Never put G2 on its back (Pi/BiBoard exposed); unloaded tests = G2 held upright in the air.
