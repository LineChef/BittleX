# Gait deployment: from a trained policy to a walk on G2

How a policy trained in simulation reaches the real robot, how the on-Pi loop runs it, and how to switch, roll back and troubleshoot. Which policy is deployed and how it has done on G2: [`../STATUS.md`](../STATUS.md). What the learned gait does and its limits: [`../rl/walking-policy.md`](../rl/walking-policy.md). The Pi's OS setup comes first: [`pi-bring-up.md`](pi-bring-up.md). Safety rules before G2 moves: [`operating-g2.md`](operating-g2.md).

## What runs where

| Where | What | Code |
|---|---|---|
| Mac | Trains the policy, exports it, validates the export, deploys | `rl_training/opencat-gym/`, `tools/` |
| Pi | The 80 Hz control loop that runs the exported policy | `pi_pipeline/gait/` |
| BiBoard | Receives joint commands (`i` command, all joints at once), streams the IMU at 5 Hz | OpenCat firmware |

Only two things travel to the Pi: `pi_pipeline/` and the exported policy, a `.onnx` file (under 1 MB) with its `.onnx.json` sidecar. `rl_training/` and `docs/` never do.

## 1. The exported policy

The trained network is a *residual*: its output, bounded to ±30° per joint, is added to the scripted `wkF` walk. Export keeps only the deterministic action path (observation of 278 values in, 8 joint offsets out; the value network and the exploration noise are dropped), so the file runs under `onnxruntime` on the Pi in under a millisecond per step.

The **sidecar** (`<name>.onnx.json`) travels with every policy and is read by both the validator and the Pi:

| Field | Meaning |
|---|---|
| `residual_scale_deg` | The residual bound the policy was trained with (30) |
| `cmd_send_every_n` | Send a joint command every n-th control tick; the Pi follows it by default |
| `heading_blind` | If true, the Pi feeds the policy a yaw of 0 (steering is done outside the policy) |
| `checkpoint`, `exported`, `levers` | Provenance |
| `modes` | Optional. The gaits the policy was trained for; without it, `normal` only |

Export with `rl_training/opencat-gym/export_onnx.py` (writes the sidecar), and check parity with `verify_onnx.py` (ONNX versus the torch policy) and `validate_deploy.py` (drives the Pi-side `residual_policy.py` in lockstep with the sim: observation, action and rounded joint targets must match). Score a policy through G2's real control path with `benchmark_decathlon.py --hw i`. Training and promotion rules: [`../rl/training-upgrade-2026-10.md`](../rl/training-upgrade-2026-10.md).

## 2. Promote and deploy

The deployed policy is named by `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py`; every previous release stays on the Pi as a fallback.

1. **Promote.** `tools/g2_promote_policy.sh TAG NAME` exports a checkpoint under a release name, points `DEFAULT_POLICY` at it, runs the test suite, commits and pushes on the current branch, then arms the deploy. For an already-exported candidate use `rl_training/opencat-gym/promote_release.py --candidate … --name …` (it never overwrites an existing release). Promotion is the user's decision.
2. **Deploy.** `tools/g2_deploy_when_online.sh` waits for the Pi to answer, `rsync`s `pi_pipeline/` and the policy files (never a `git clone`), and restarts the voice service. `--once` deploys now, `--cancel` disarms a waiting watcher. It never touches the Pi's `.env`, `.venv` or memory data, and it **refuses to run during an exploration, a baseline run or a walk**.
3. **Check.** Before assuming the Pi matches the repo, dry-run the sync: `rsync -an --itemize-changes pi_pipeline/ $G2_PI:bittleX/pi_pipeline/`. The deployed commit is written to `pi_pipeline/.deployed_commit`.

**Roll back** by setting `DEFAULT_POLICY` to the previous release file and running `tools/g2_deploy_when_online.sh --once`.

## 3. The on-Pi loop

`pi_pipeline/gait/run_gait.py` runs the loop; `policy_walker.py` wraps the same loop as a background thread, which the voice service and exploration use as G2's default forward gait.

Each tick, about 80 times a second:

1. Read every IMU line that arrived since the last tick (never block on the 5 Hz stream; the last roll, pitch and yaw are held between prints).
2. Build the observation: orientation, recent joint history and a rhythm clock (`residual_policy.py`, an exact mirror of the sim's observation).
3. Run the policy, add its residual to the scripted `wkF` joint targets.
4. Map the joints to OpenCat servo indices with sign and offset calibration (`deploy_map.py`) and clamp to ±120°.
5. Send one `i` command with all joints.

A stand-up before any walk uses the eased 0.8 s ramp (`standup.py`). Any exit rests G2 with `d`. An end of walk slower than 2 s (the rest or balance blend and its sends) logs `walk.slow_end`; a walk that does not stop within 5 s of `stop()` logs the stack its thread is stuck in (`policy_walker.py`).

**Steering.** The front feet steer G2. Each policy has a fixed front-left foot trim (`DEFAULT_TRIMS` in `heading_hold.py`, overridden with `G2_FOOT_TRIM`); the closed-loop heading hold is off unless `G2_FOOT_HOLD=fl`. Trims were measured on hardwood only. A trim measured on one floor can be saved per policy (`python -m pi_pipeline.attachments floor-trim tile fl=-0.1`); it applies when the floor label (`g2floor`, always set by a person) is under 12 h old (`G2_FLOOR_TRIM_MAX_AGE_H`). Order: `G2_FOOT_TRIM`, the per-floor trim, the attachment's saved trim, `DEFAULT_TRIMS`. Each walk prints the floor it used.

**Guards on every walk:** servo heat estimate and cutback (`thermal_guard.py`), jam reflex from joint strain (`jam_guard.py`), carpet detection from IMU speed (`carpet.py`, `speed_estimate.py`), fall guard, an IMU stall detector for wall contact, and a battery read every few seconds with a rest on a critical reading. The loop also stops if no IMU frame arrives for a set time or the loop overruns.

**Gait switching.** "Hi step" and "walk normally" (voice, from any mode) set a shared gait mode (`gait_mode.py`). A policy that lists the mode in its sidecar plays it with its learned correction; any other plays the gait's scripted base without a correction and says so.

## 4. Running a walk

From the Pi, in `pi_pipeline/.venv`, with G2 on his feet and your hands near:

```bash
python pi_pipeline/gait/run_gait.py --cmd 0.10 --seconds 12.5 --log ~/g2_runs/x.csv   # the deployed policy, about 10 gait cycles; fall guard on
python pi_pipeline/gait/run_gait.py --cmd 0.0 --seconds 5                             # stand and hold
python pi_pipeline/gait/run_gait.py --dry-run --seconds 5                             # full 80 Hz loop with a synthetic IMU, no serial
python pi_pipeline/gait/run_gait.py --probe-imu                                       # what the BiBoard streams on an idle bus
python pi_pipeline/gait/run_gait.py --openloop --cycles 6                             # the scripted walk, no policy
```

`--help` lists the rest (foot trim and hold, `--send-every`, carpet and skill switching, battery and lift options). Every policy walk without `--log` is written automatically to `~/g2_runs/auto/<date>/` with a JSON sidecar (floor, policy, why it ended); set the floor with `g2floor <label>` first. Summaries: `python tools/walk_log_summary.py <log.csv>`. Bench-time speed of the step: `python pi_pipeline/gait/bench_real.py` (expect well under 12.5 ms, the 80 Hz budget).

## 5. First time on new or repaired hardware

The mapping and signs were verified on G2, but repeat these steps after a servo replacement, a firmware reflash or a different body:

1. Check the link and IMU: `python -m pi_pipeline.link.check_serial ping`, then `run_gait.py --probe-imu` (the IMU line format and the yaw sign).
2. Calibrate the servos and verify with `kbalance` ([`../../blueprints/calibration.md`](../../blueprints/calibration.md)).
3. Play the scripted walk open-loop (`--openloop`). If a leg kicks backward or the gait looks mirrored, correct that servo's sign in `deploy_map.SERVO_SIGN`.
4. Walk the policy at `--cmd 0.10` on a floor, and compare the logged joint traces with the policy output.
5. Guided versions of these steps: `python -m pi_pipeline.bringup` and `python -m pi_pipeline.link.check_serial firstmove`.

## Troubleshooting

| Symptom | Look at |
|---|---|
| The walk never starts or no IMU frames | The raw IMU lines; the yaw field once overflowed and made every line unparseable (fixed in `imu_parse.py`). [`operating-lessons.md`](operating-lessons.md) |
| Heading drifts | The foot trim for this policy and floor; [`../rl/real-walk-log.md`](../rl/real-walk-log.md) |
| A leg moves the wrong way | `deploy_map.SERVO_SIGN` and step 3 above |
| The loop overruns or lags | Whether something else is using the Pi (exploration, speech); [`../hardware/diagnostics.md`](../hardware/diagnostics.md) |
| The Mac cannot reach the Pi but another machine can | An MDM or endpoint-security agent on the Mac blocking the local subnet was the cause once; check it before the router. `ping` the Pi's raw IP, then `ssh -vvv` |
| Deploy refused | An exploration, baseline run or walk is active; `bash tools/g2_explore.sh status` |

*The original bring-up used a self-contained script, `scripts/pi_setup.sh`, that built a synthetic policy stub and uploaded its report to a public paste service. It was removed on 2026-10-17 in favor of `pi_pipeline/setup_pi.sh`; it is in git history.*
