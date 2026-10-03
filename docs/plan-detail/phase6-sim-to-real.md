# Phase 6 — RL sim-to-real deployment (detail)

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> Phase 6. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

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
      hooks), `run_gait.py` (80 Hz loop: BiBoard `gP` IMU stream, 5 Hz, held between
      frames → policy → `i` command). `validate_deploy.py` confirms **0 joint-degree cells differ**
      from `model.predict` across 5 commands × 251 steps.
- [x] **Deployment-safety infrastructure (2026-09-05), built + unit-tested,
      hardware-validation pending:**
  - `pi_pipeline/gait/thermal_guard.py` — servo thermal guard on `run_gait.py`.
    Estimates per-joint heat from commanded motion (no P1S sensor).
    **Layer 1+2 done 2026-09-10:** 3-tier per-joint indicator (`ThermalTier`
    GREEN/AMBER/RED at 50/85 % of trip) + per-joint spoken warning; new
    `behavior/thermal_governor.py` (`ThermalGovernor`) — AMBER throttles
    speed + softens gait, RED holds a folded cooldown pose. All constants
    placeholders; [`hardware/servo-thermal.md`](../hardware/servo-thermal.md).
  - `pi_pipeline/diag/` — **Phase 1 + the non-hardware parts of Phase 2 done
    (2026-09-10).** JSONL event log + black-box ring + manifest +
    `summarize/replay/tail/sync`; taxonomy events from `run_gait` / `serial_link`
    / the behaviour driver. Phase 2: `diag/watchdog.py` (heartbeat +
    stall→black-box-flush→safe-stop, wired into `run_gait`),
    `diag.incident()` + expanded auto-flush names, `install_excepthook()`,
    manifest finalize on close, `diag/sysmon.py` (`# HARDWARE` battery /
    Pi-thermal stubs). Left: validating the black box on a real fall / link drop.
    [`hardware/diagnostics.md`](../hardware/diagnostics.md).
  - `pi_pipeline/power/` — zero-risk power levers (CPU governor, Wi-Fi
    power-save, disable-unused peripherals). idle-REST built; **sleep-mode FSM
    built 2026-09-10** (`behavior/sleep_mode.py` — curl + vision off +
    power-save, wakes on IMU/wake-word/sound). Driver-side wiring of both
    pending. [`hardware/pi-power.md`](../hardware/pi-power.md).
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
  stock OpenCat `i` command + `gP` IMU stream carry the loop; no firmware flash.
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
      [`docs/hardware/self-righting.md`](../hardware/self-righting.md).
