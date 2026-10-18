# Gait

Everything that makes G2 walk on the real robot: the 80 Hz loop that runs the exported policy, the steering trim, the eased stand-up, the guards, the IMU speed and stall estimates, and the bench and logging tools. Deployment, sidecars and rollback: [`../../docs/guides/gait-deployment.md`](../../docs/guides/gait-deployment.md). What the learned gait does: [`../../docs/rl/walking-policy.md`](../../docs/rl/walking-policy.md). Which policy is deployed: [`../../docs/STATUS.md`](../../docs/STATUS.md).

## The loop

| Module | Role |
|---|---|
| `run_gait.py` | The on-Pi control loop and its command line (`--cmd`, `--seconds`, `--log`, `--probe-imu`, `--openloop`, `--dry-run`, …). Sends `d` (rest) on any exit |
| `walk_start.py` | Checks before a policy walk: settle into a still stand after a firmware gait or skill, never start tilted past 30°, the opt-in speed ramp-in |
| `walk_tools.py` | The bench walks behind `run_gait.py`'s `--probe-imu`, `--openloop` and `--dry-run` |
| `walk_vision.py` | The Phase E vision-skill pieces of the walk loop (skill layer, background camera reader, edge hand-off, feed factory) |
| `walk_common.py` | The IMU-to-policy quaternion, loop constants and the fire-and-forget send shared by the above (`run_gait.py` re-exports all of these) |
| `policy_walker.py` | The same loop as a background thread (`PolicyWalker`): G2's default forward gait for the voice service and exploration |
| `residual_policy.py` | `ResidualGaitPolicy`: builds the 278-value observation, runs the ONNX policy, adds its residual to the scripted `wkF` walk. `DEFAULT_POLICY` names the deployed file |
| `deploy_map.py` | Maps the policy's joint order to OpenCat servo indices, with per-servo sign and offset hooks, and clamps commands |
| `imu_parse.py` | The shared parser for the BiBoard's IMU line (also used by `app/sensors.py`) |
| `wkf_ref.npy`, `creep_ref.npy`, `hsF_ref.npy` | Reference gait cycles: the scripted walk, the creep base and the high-step base |

## Steering, stand-up and gait modes

| Module | Role |
|---|---|
| `heading_hold.py` | Steers with the front feet outside the policy: a fixed per-policy trim (`DEFAULT_TRIMS`), and an optional closed-loop hold (`G2_FOOT_HOLD=fl`) |
| `standup.py` | The eased 0.8 s stand-up ramp used before every walk |
| `gait_mode.py` | The shared "which gait" state (`normal`, `hi step`), switched by voice from any mode |
| `skill_switch.py`, `skill_layer.py` | Vision picks a scripted keyframe skill on top of the frozen walk (`--skills`); no training involved |

## Guards and estimates

| Module | Role |
|---|---|
| `thermal_guard.py` | I²t servo heat estimate with GREEN, AMBER and RED tiers |
| `carpet.py`, `speed_estimate.py` | Carpet detection from a zero-velocity-update speed estimate |
| `imu_stall.py` | A stall or wall-contact signal from heading jitter; it starts the hit sequence |
| `stand_guard.py` | Keeps the firmware's gyro balance off while idle and trips it if a standing wobble starts |
| `stillness.py` | Waits until G2 has stopped swaying before a picture |
| `jam_guard.py` | Vision-free jam reflex from servo strain. **Built and tested, not wired in** (see the package README) |

## Teaching, benchmarking and logging tools

Each is a command-line module; run with `python -m pi_pipeline.gait.<name>` or `python pi_pipeline/gait/<name>.py` from the repo root.

| Module | What it does |
|---|---|
| `bench_real.py` | Times the deployed policy per step on this machine |
| `teach.py` | Teaches a leg movement by hand or by jogging; saves a skill file (`rl_training/opencat-gym/reference_gait/build_taught_step.py` builds a gait from it) |
| `baseline_runs.py`, `turn_runs.py` | Series of logged walks and firmware turns (`tools/g2_baseline.sh`, `tools/g2_turns.sh`) |
| `fw_skill_log.py` | Runs a firmware gait for N seconds while logging the IMU |
| `imu_capture.py`, `stand_log.py`, `yaw_drift_check.py`, `standup_test.py` | Rest and stand IMU captures, a stand-still log, a yaw-drift check and a stand-up test |
| `sysid_collect.py`, `servo_step.py` | System-identification sequence and servo-speed fitting |
| `h1_score.py` | Scores the learned-vs-scripted head-to-head from measured numbers (the comparison itself is not being run on G2) |

Logs: every policy walk without `--log` is written automatically to `~/g2_runs/auto/` by [`../telemetry/`](../telemetry/README.md).
