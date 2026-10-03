# Project history (moved from the README, 2026-10-02)

Dated narrative that used to be the README's "Project Status" section, kept verbatim for the record. It describes the
project as of late September 2026 and is **not current** — for the current state see [`STATUS.md`](STATUS.md); for the
roadmap and decisions, [`project-plan.md`](project-plan.md).

**2026-09-28: the Bittle X body has arrived.** Assembled, zero-point
calibrated, base stock-firmware functions tested (all normal, including
`wkF`, the gait the trained policy is layered on — one stock gait, `vtF`
("step"), stumbles toward the back-right leg but isolates cleanly to that
gait alone and isn't part of our deployment path, so it's parked), and the
Pi deployed onto it over serial. **2026-09-29:** a firmware bug (enabling
the onboard camera module permanently kills IMU streaming) required a full
erase + reflash to current official firmware — this also resolved a real
IMU-rate puzzle (the pre-reflash board was a ~10-month-stale build; the
real rate is exactly 5 Hz, matching the deployed policy's training
assumption all along). The reflash reset calibration and the voice
module's language setting, both since redone (see
[`docs/project-plan.md`](docs/project-plan.md) Phase 4). Everything else
below was built and validated software-only or with the hardware mocked,
ahead of this point.

- **RL locomotion** (`rl_training/opencat-gym/`) — a PyBullet + Stable-Baselines3
  pipeline. The gait is a learned *residual* on Bittle's scripted `wkF` walk,
  IMU-corrected every control step, conditioned on speed/heading commands and the
  mounted Pi/camera payload. **Deployed policy (2026-09-23): `hw1_20m`**, trained
  under G2's real control path — the stock firmware's 5 Hz IMU and its `i`
  joint-command timing (see [`docs/rl/hw1-log.md`](docs/rl/hw1-log.md)). Before
  that the base was `run20m_resid30_ppo`, and before that **`run20m_ppo`** (20 M
  steps from scratch: tracks speed commands to 0.007 m/s, climbs a 24° slope,
  0 % falls on the payload-on decathlon), exported to ONNX and sim-validated
  bit-for-bit against the on-robot control loop. **2026-09-05:** the training
  ground was redesigned (rubble-primary, wider slopes); a heightfield-tilt
  geometry bug then collapsed `ep_rew_mean` at ~1.1 M steps on every
  new-course finetune (fixed, commit `01cf87e`; the tilted heightfield spawned
  the robot embedded in the terrain → runaway `r_height` penalty → critic
  divergence). A fresh 20 M run (`run20m_newcourse`) on the fixed course came
  back a **negative result** — equivalent on the core ladder but clean
  regressions on bare-robot / ledges / carpet / OOD slopes — so **`run20m_ppo`
  stays the frozen base**; the new course's slope-fix and rubble variety are
  parked for a future green-lit run. Sim locomotion work is otherwise done
  pending the real-robot head-to-head. Learned vision-*conditioning the walk
  policy* was ruled out (Phases A–D, plus the `smoke_vfix3` retry) — reward-shaping
  "see it → step over it" into the trained gait just makes it plow through or
  stall. The replacement, Phase E's vision-triggered scripted skill-switching,
  showed real sim gains but is back-burnered until G2 has a real forward
  sensor (the camera is a recognition model, not an obstacle/edge detector).
  **Exception, decided 2026-09-15:** a discrete climb-a-ledge skill (B13) is
  no longer deferred — Phase F found climbing was a sim-fidelity wall, not a
  real-hardware limit, so it's scheduled once the body arrives, starting
  scripted (no sensor needed for that first step) before exploring a learned
  residual. See [`docs/rl/`](docs/rl/) and
  [`docs/rl/hardware-gated-backlog.md`](docs/rl/hardware-gated-backlog.md) H7.
- **Companion pipeline** (`pi_pipeline/`) — voice conversation, persistent
  memory, vision / obstacle-avoidance, the BiBoard serial link + fall-recovery
  state machine, the on-robot gait loop, the autonomous behaviour layer
  (explore mode, idle-REST staged descent), a servo thermal guard, a
  black-box diagnostics logger, and Pi power-management helpers — all scaffolded
  and running on a dev machine with the hardware mocked; **the test suite passing**.
- **On-device vision** — a custom 3-class detection model (household member +
  `dog` + `cat`, YOLOv8n) runs on the Grove Vision AI V2 camera. The reproducible
  build path (the camera firmware is frozen at Jan 2025, which broke every modern
  export toolchain until we pinned `ultralytics==8.2.8` + a local arm64 export)
  is in [`docs/vision/custom-model-recipe.md`](docs/vision/custom-model-recipe.md),
  with tooling in `tools/gv2/`.
- **Pre-hardware prep** — a headless Pi Zero 2 W bring-up runbook, an idempotent
  provisioning script, a model fetcher, and a voice-pipeline benchmark harness are
  ready to run the moment the SD adapter and robot arrive:
  [`docs/guides/pi-bring-up.md`](docs/guides/pi-bring-up.md).

A full inventory of what G2 can do, with per-item status, is in
[`docs/capabilities.md`](docs/capabilities.md). For a plain-language tour of how
each part works, see [`docs/how-it-works.md`](docs/how-it-works.md). The ordered
day-1 bring-up sequence is in [`docs/project-plan.md`](docs/project-plan.md)
("When the hardware arrives").
