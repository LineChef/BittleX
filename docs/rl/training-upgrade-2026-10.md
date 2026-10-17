# The 2026-10 training upgrade: what changed in the trainer and why

Reference for the training tooling built on 2026-10-08/09 (the stack behind the V4, V5 and V6 chains). Which policy is deployed: [`../STATUS.md`](../STATUS.md).
Run plans and results: [`../plan-detail/v5-training-plan.md`](../plan-detail/v5-training-plan.md), [`../plan-detail/v6-staged-training-plan.md`](../plan-detail/v6-staged-training-plan.md);
the dated decisions behind the V4 runs: [`../archive/plan-detail/decisions-log-2026-10-08.md`](../archive/plan-detail/decisions-log-2026-10-08.md). Code lives in `rl_training/opencat-gym/`.

## 1. Bugs found and fixed in the review

1. Curriculum probes mostly had no hazard in them (a ledge in 24% of ledge-probe episodes), so a policy failing every ledge still scored about 0.76 relative and the level could never be demoted. Fix: `opencat_gym_env.CATEGORY_FORCE` (probe episodes always contain the probed hazard; forced slopes are targeted side-hill / climb / descent).
2. 30% of probe episodes were stand or backward commands, which never reach a hazard (all hazards sit ahead). Fix: probes walk forward (`probe_command`, same command and seed for the clean floor and every category); the probe shove size is pinned to the training envs' mean.
3. `reset(seed=...)` ignored the seed, so probe pairs, the benchmark ladder, audits and drift/steer probes were unrepeatable. Fix: reset seeds numpy; training envs are seeded from `G2E_SEED` (+0..7), so runs are reproducible.
4. The gait checks would have compared world-2 checkpoints against the world-1 K3 envelope. Fix: `phase_v3.gate_baseline` refuses a baseline scored in another world; `phase_v3.py rebase-baseline` re-scores.
5. Step-down ledges on tilted ground were level blocks (G2 started tilted on a level block). Fix: the block lies on the tilted ground; the cap is the block height.
6. A fresh 20M would have climbed at the 3M screening pace. Fix: `g2_profile.FINAL_PACE` (+0.05 after two good probes) for fresh finals.
7. `caps_report.py` judged the raw probe score and assumed the old 14 deg tilt for descents. Fix: relative score; `nominal_for(tag)` reads the run's own course.
8. The audits and the benchmark ladder used the old staged course (no caps). Fix: `g2_profile.next_final_env()` is the single definition; ladder version 2.
9. Recorded episodes did not replay after a shove, a cap change or a mid-episode ramp update. Fix: the recorder saves `_push_curr`, the live caps and each ramp update with its step (`RecordingWrapper.set_ramp_steps`, `meta["ramp_events"]`).
10. `run_pipeline.launch` merged the hw1-era `BASE` under V3 launches. Fix: `base=False` from `phase_v3`.
11. `benchmark_decathlon._apply` never zeroed `ROUGH_TERRAIN`, so about 30% of the episodes of nearly every cell (including calm walk and every ledge cell, which then had no ledge) ran on a ±1.1 cm rough floor. Comparisons stayed fair (all policies met the same mix), but absolute numbers before the fix carry it. Fix: `ROUGH_TERRAIN` in `_ZERO`; test `test_upgrade.py::test_benchmark_cells_have_no_stray_training_hazards`.
12. The slip and clearance penalties read the paw's x position instead of its velocity (inherited from upstream; both under 0.1% of the reward). Flag `FIX_PAW_VEL`, on in the recipe.
13. The benchmark's N2 / L1 "speed decay" is progress along the start direction, not a slowdown: a walk that curves looks slow. A path-speed metric was added to `benchmark_v4.v4_metrics`.

## 2. Decisions that bind training work (user, 2026-10-08)

- Human review is never part of the training process. The user reviews reports on their own schedule; no step waits on a person. The only human step is the go for a 20M.
- No backward walking in training (G2 walks backward with the firmware `bk` skill; the Pi never sends the policy a negative command). No stopping in the sim.
- Plateau stop for long runs: compress the learning rate to a 1M-step cool-down, then stop (never stop cold). "Plateau" means the gait/eval score and every hazard's frontier flat for 3M steps; never before 10M; keep the best checkpoint as well as the last.
- Native arm64 Python: a self-contained Python in `~/.local/share/g2/python-3.11-arm64` (no installer, PATH, Homebrew or shell-profile changes); the old Intel venv is `.venv-x86_64` (floats differ, so old recordings do not replay bit for bit).
- Hazard shares for a full course: rubble 50%, box obstacles 30%, slopes of 5 deg or more 20%, rough floor 20%, snags 20%, ledges 20%. The surface step and carpet-like physics stay out of training (benchmark cells T4.1 and T4.2 still test them).
- A report's "reality gap" stress was approved only as the 12.5 ms command-delay evaluation; a speed-tracking item was not approved.

## 3. Measurements behind the design

- The RL stack ran under Rosetta before the arm64 build (Pure Python about 1.7x slower). After: collection with 6 envs 4,869 steps/s (was 2,284); PPO update 4.8 s at batch 64 (was 13.3 s), 0.6 s at 4,096 x 5. Six envs beat eight on the M1 Pro (the two efficiency cores gate a synchronous vec env). SB3's default minibatch of 64 made the update about 60% of wall time.
- Reward in the V3 20M: imitation 68% of |reward|, speed bonus +3, speed-track −1.6 to −2.3. In residual mode `r_imitation` compares the commanded joints (wkF + action) to wkF, so it equals `16 x exp(-0.15 x sum(action^2))`: an alive bonus plus a residual-size penalty about 7x stronger than `FAC_RESIDUAL_COST`. The stumble shaping is effectively off; the accumulated-heading penalty is about 0.05% of the reward.
- Speed versus command (V3 20M, clean floor): 0.045 → 0.047 m/s, 0.10 → 0.087, 0.15 → 0.095. The gait tops out near 0.095 m/s in the sim; commands above about 0.10 were unreachable.
- Physical bounds (sim geometry, 389 g, CoM 77 mm above the paws): static tip-over 24 deg side-hill, 37 deg climb/descent; slip at friction 0.7 / 1.0: 35 / 45 deg. Paw lift: scripted wkF 9-10 mm, with the ±30 deg residual 57-61 mm kinematic.
- A blind policy can learn robust gait choices and IMU-driven reactions (V3 vs V2.1: uphill 12 deg falls 0.93 → 0.00, cross-slope 10 deg 0.65 → 0.10) but cannot anticipate; the frontier should stall on step-ups below the kinematic limit, and that stall is the real ceiling. Real sway frequency matches the sim (0.78-0.79 Hz); sim roll is 10-13% low. The 12.5 ms command delay lowers V3's calm-walk speed in the sim (0.086 → 0.079 m/s at 30 ms).
- The hardware limit outside the recipe: 5 Hz IMU, no gyro, no joint or foot feedback.

## 4. What was built (all behind settings that default OFF; with them off the env is bit-identical to the pre-upgrade env)

**Env (`opencat_gym_env.py`):** `CMD_BANDS`, `IMU_NOISE_PER_FRAME`, `HAZARD_EP_LEN` (obstacle x-ranges scale with it), `IMITATION_ACTUAL`, `PRIV_OBS` (22 privileged values), `FIX_PAW_VEL`, `_last_contact`, and the frontier (`FR_*`, `_frontier_plan`, `_fr_report` into the final `info`).
**Trainer (`train.py`):** `G2E_N_ENVS` (`n_steps = 16384 // n`), `BoundaryCheckpoint` (names checkpoints by the 200k boundary so 3M/5M/10M exist with 6 envs), `LeanInfo`, `G2E_PPO_BATCH/EPOCHS`, `G2E_NORM_REWARD` (reward-only VecNormalize), `G2E_LOG_STD_INIT`, `G2E_LR_FLOOR`, `FrontierCurriculum` (writes `trained/<tag>_frontier.json`, `[frontier]` lines), `RunMonitor` (`G2E_RUN_MONITOR`: fixed-difficulty eval every 1M, `trained/<tag>_best_ppo.zip`, `[health]` lines, auto-stop on NaN / explained variance under 0.2 twice after 2M / anchor success under 0.35 twice after 3M, exit 3; `G2E_PLATEAU_STOP`).
**Privileged critic:** `priv_policy.py` (`PrivCriticPolicy`: the actor's extractor zeroes the privileged tail), `mirror.py` maps the privileged values, `export_onnx.py` exports the usual 278 inputs and pads zeros. Only the training-time critic sees true state; the exported actor is unchanged.
**Profile and levers (`g2_profile.py`):** RECIPE sets N_ENVS 6, LEAN_INFO, RUN_MONITOR, IMU_NOISE_PER_FRAME, FIX_PAW_VEL; levers `big_batch`, `frontier`, `cmd_forward`, `opt_bundle`, `hazard_contact`, `imitation_actual`, `privileged_critic`, later `mirror_strong`, `lr_half`, `hazard_long`, `slope_floor`, `cmd_capped`, and for V5 `v5_course`, `cross_bonus`, `haz_speed`, `haz_posture`, `heading_blind`, `kl_limit`. The ladder strips trainer-only settings and caps so one fixed ladder scores every policy.
**Runners and tools:** `phase_v4.py` (run / status / final; ends with `compare_v3_v4`), `tools/v4_watchdog.sh`, `frontier_report.py`, `preflight.py`, `test_upgrade.py`, `checkpoint_tracker.py` (calm walk + crossing per 1M checkpoint), `paired_compare.py` and `final_exam.py` (V3 comparisons; do not trust single 40-episode comparisons on edge cells), `exposure_probe.py` (how far a policy gets through hazards on a fixed course), `episode_recorder.py` + `watch_training.py` (exact episode replay), `passability_audit.py`. The V3 vs V4 report carries paired per-cell verdicts (McNemar exact test on falls, paired speed difference with a 95% interval), a "What to expect on G2" section, side-by-side replays, how each trained and how each falls.

## 5. Frontier curriculum design

- Ten hazards, each its own ladder of 12 size bins from 0 to a physical bound: side-hill 0-22 deg, climb 0-30, descent 0-30, step-up 0-5.5 cm, step-down 0-6 cm, rubble / boxes / rough floor / snags severity 0-2.0, overheat cutback 0-2.0.
- Presence keeps the user's shares (section 2), converted to per-episode chances after the 10% hazard-free anchors and the exclusions (a rough floor cannot carry a slope or ledge).
- Episode roles: 10% anchors (no hazards: the success baseline); 25% combo (all present hazards, not counted); 65% focus (one present hazard at a frontier-weighted bin, counted). The focus hazard is drawn inversely to its share so rare hazards gather evidence as fast as common ones. Stand episodes do not report (they never reach a hazard).
- A focus episode reports (hazard, bin, success = survived and covered at least 50% of the commanded distance). A callback keeps the last 300 outcomes per bin and the last 400 anchors; relative success = bin success / max(anchor success, 0.3).
- Frontier F = the last bin, counting up from 0, with at least 30 outcomes and relative success of at least 0.5. At most +1 bin per update; no advance while anchor success is under 0.5; drop one bin under 0.35; F ≤ 12 × steps / `RAMP_TOTAL_STEPS`.
- Sampling: 15% over bins 0..F-2, 55% on F-1 and F, 20% on F+1, 10% on F+2. A bin past F with 300 outcomes and relative success under 0.05 is blocked (2% floor, nothing past it: the automatic ceiling).
- The caps file stays as a manual override. Probes, benchmarks and audits use the old level path so ladders stay comparable across policies.

## 6. What the overnight V4 screens found (2026-10-09)

The recipe that followed: `frontier` + `cmd_forward` + `opt_bundle` + `privileged_critic` + `mirror_strong` + `lr_half` + `hazard_long` (600-step episodes, obstacles unmoved) + frontier gates 0.25 / 0.12 + `slope_floor`.

1. The frontier never advanced in the first 20M and in 7 of 8 screens (gate 0.5 on hazard-free success, which sat at 0.07-0.47), so those screens had almost no real hazards.
2. Training episodes of 3.1 s never let G2 cross an obstacle field (0 of 41 got past it); long hazard episodes fix that.
3. With the original mirror weight and learning rate the calm walk flipped between clean and 40-70 deg one-sided drift from checkpoint to checkpoint; the health eval cannot see it, the 12.5 s walk can.
4. The 10 deg cross-slope (T3.2) still fails against V3 at most checkpoints and was the main open problem.
5. Result: no clear win over V3; Candidate A became V4 on the user's instruction. Later: V5 (about equal to the scripted walk) and V6 (deployed) in the plan docs above. The old static caps had silently capped every V4 run's curriculum (side-hills 8 deg, ledges 20 mm); the side-hill is lopsided (10 deg left-side-down falls 0.49, right 0.26), and the benchmark's 3.1 s cells could not see crossing. Neither V3 nor V4 steers on its yaw input.
6. Unused ideas: a continuation that trains hard on the cross-slope and small obstacles (conflicts with the no-training-on-a-consolidated-20M rule), checkpoint averaging, a pinned frontier floor for rubble and snags.

## 7. Pitfalls

- Never put the trainer's `--tag` text, or a runner's process text (`phase_v5.py run`, a run tag), in any shell command: `run_pipeline.any_training()` and the watchdogs' `pgrep -f` match your own shell and think a run is active.
- Any script that calls the benchmark needs an `if __name__ == "__main__"` guard (it spawns workers). Never edit `benchmark_v4.py` / `benchmark_decathlon.py` while a runner is scoring (its process caches the module while spawned workers reload it).
- `git add` explicit file paths, never `trained/` or a folder (an accidental add pushed 2,074 training outputs; they stay in history by the user's decision). Keep the Mac awake for long runs: `caffeinate -ims -w <pid>`. Kill a runner by exact pid, never `pkill -f`.
- Each progress line is 40 episodes and swings a lot (heading 12-34 deg, asymmetry 0.8-5.3 within a few lines): read trends over several lines.
