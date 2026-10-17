# RL training code

Simulation training for G2's walking gait: PyBullet, Stable-Baselines3 (PPO) and Gymnasium. The gait is a learned *residual* (bounded to ±30°) on Bittle's scripted `wkF` walk, corrected from the IMU every control step. How a trained policy reaches the robot: [`../docs/guides/gait-deployment.md`](../docs/guides/gait-deployment.md). The training pipeline end to end: [`../docs/rl/training-pipeline.md`](../docs/rl/training-pipeline.md). Which policy is deployed: [`../docs/STATUS.md`](../docs/STATUS.md).

Everything is in `opencat-gym/`, a curated copy of [ger01d/opencat-gym](https://github.com/ger01d/opencat-gym) (MIT, commit `12b39ff`, see `opencat-gym/LICENSE`) that already targeted this hardware (`models/bittle_esp32.urdf`, Bittle/BiBoard ESP32), extended heavily since. Run everything from inside `rl_training/opencat-gym/`, because the scripts import `opencat_gym_env` as a local module.

## Setup

The RL environment is the **repo-root `.venv`** (native arm64 Python 3.11), not a venv in this folder. Rebuilding it, from the repo root: `pybullet` has no macOS wheel and builds from source, which needs a workaround:

```bash
CPPFLAGS="-Dfdopen=fdopen" .venv/bin/pip install -r requirements.txt
```

Commands in this folder use `../../.venv/bin/python`. Tests: `../../.venv/bin/python -m pytest -q test_*.py` (the `pi_pipeline` suite is separate and runs from the repo root).

## Rules that apply to every run

- Every new run is a fresh candidate, not a continuation or fine-tune; nothing trains on top of a consolidated 20M run (a chain that starts fresh at S0 is fine).
- Never launch a 20M-step run unless the user asks. Screening runs are capped at 3M steps.
- Difficulty never ramps above what a capable policy can pass (`passability_audit.py`).
- Do not overwrite `run20m_resid30_ppo` (the fallback base) or `run20m_ppo` (the reference).
- Give a timing estimate with a completion clock time when launching anything (`tools/eta.py`).
- Intermediate checkpoints are not kept (user, 2026-10-17); a new run writes its own. Never put a run's `--tag` text in a shell command: it trips `any_training()`.

## The scripts

| Role | Scripts |
|---|---|
| **Environment and training** | `opencat_gym_env.py` (the Gym env; every new mechanic is a flag that defaults off), `train.py` (PPO, curriculum and frontier callbacks, health checks), `g2_profile.py` (one definition of "G2 as the sim models it" plus the recipe and the levers), `curriculum.py`, `mirror.py` (left-right symmetry), `priv_policy.py` (privileged critic), `episode_recorder.py`, `continue_train.py`, `smoke_train.py`, `train_throughput.py`, `training_steps.py` |
| **Chain runners** (unattended; each has a plan doc) | `phase_v3.py` (queue runner and scoring, reused by the others), `phase_v4.py` (screens, then the 20M), `phase_v5.py`, `phase_v6.py` (done and deployed), `phase_hs.py` (high-step creep, stopped), `run_pipeline.py` (process helpers: launch, stop, `any_training()`), `phase_b_orchestrator.py` (used by `run_pipeline.py`), `preflight.py` (must print ALL PASS before a 20M is offered), `start_run.sh` |
| **Benchmarks and comparison** | `benchmark_decathlon.py` (the graded cells), `benchmark_v4.py`, `benchmark_v5.py` (hills, ledges, size ladder), `benchmark_commanded.py`, `benchmark_gaits.py`, `benchmark_recovery.py`, `evaluate_policy.py`, `multi_ckpt_eval.py`, `paired_compare.py`, `final_exam.py`, `checkpoint_tracker.py`, `exposure_probe.py`, `frontier_report.py`, `caps_report.py`, `passability_audit.py` |
| **Reports** | `report_v5.py`, `report_summary.py`, `v3_report.py`, `hs_report.py` |
| **Gait and steering probes** | `gait_probe.py`, `hs_probe.py`, `creep_sweep.py`, `steer_probe.py`, `drift_probe.py`, `turn_gate_probe.py`, `turn_gate_curve.py`, `servo_saturation_check.py` |
| **Real-to-sim** | `real2sim.py`, `sysid_replay.py`, `sim_vs_real_walk.py`, `replay_real_obs.py`, `replay_control_path.py`, `resilience_imu_rate.py`, `resilience_joint_cmd.py`, `firmware_model.py` |
| **Export and deploy** | `export_onnx.py` (writes the `.onnx` and its `.onnx.json` sidecar), `verify_onnx.py`, `validate_deploy.py`, `promote_release.py` |
| **Viewers** | `watch.py` (a policy on a chosen challenge), `watch_live.py` (the training run happening now), `watch_training.py` (recorded training episodes), `watch_trained.py`, `watch_env.py` with `watch_v3.sh`, `watch_slopes.py`, `view_sim.py`, `enjoy.py`, `render_gif.py`, `render_showcase.py`, `leg_tint.py` |
| **Tests** | `test_*.py`: caps, difficulty, episode replay, the V3, V5 and V6 levers, probe presence, the surface-transition junction, the training upgrade, high-step creep, eta, viewer sync |

`opencat-gym/reference_gait/` holds the decoded firmware skills (`wkf_ref.npy` and about forty others) and their builders: [`opencat-gym/reference_gait/README.md`](opencat-gym/reference_gait/README.md). `opencat-gym/models/bittle_esp32.urdf` is the simulated robot.

## `trained/`

Gitignored, except the small result files that back decisions (benchmark JSON, reports, the exported release policies) which are force-added: [`../docs/rl/results-index.md`](../docs/rl/results-index.md). Final policies are `trained/<tag>_ppo.zip`; the released ones are `Release_Candidate<name>_ppo.onnx` with their sidecars. Never put a wildcard delete over this folder: the code reads switches from it (for example `v3_world2`).

## Removed campaign scripts

Scripts for closed campaigns (the vision goal and vision-in-gait work, climbing and foot probing, the resilience, friction and slope sweeps, and the old hardware-IMU retrain chains) were removed from the working tree on 2026-10-17. Their results are in [`../docs/archive/`](../docs/archive/README.md). To recover one: `git show archive/rl-campaign-scripts-2026-10-17:rl_training/opencat-gym/<name>.py`.
