# Automated Iteration Log — Run 5 (domain randomization / robustness)

Branch: `auto-gait-iteration` (synced from `development`). Started 2026-08-30 ~22:20.
Caps: 3.5 h OR 5 iterations. Stop early: `rl_training/opencat-gym/STOP`, or interrupt.

## Goal

Harden `phase3-gait` (`auto_gait_final`) for sim-to-real: walk over small
obstacles and shrug off pushes / friction / mass / IMU-noise variation without
falling, and recover balance from a stumble. Not in scope: self-righting from a
full fall (own effort later).

## Method

Per-episode randomization in `opencat_gym_env.py`, each ramped in over training
(`dr = min(1, step_counter_session/DR_RAMP_STEPS)`, `DR_RAMP_STEPS = 5e5`) so the
clean gait is preserved early and difficulty grows. **Finetune from
`auto_gait_final_ppo`** (`train.py --from`), not fresh — the policy already walks,
we only need robustness. One randomization dimension added per iteration for
attribution; a final 2M run with everything on.

Held-out eval (`evaluate_policy.py --dr-*`, which forces `dr=1`): each scenario
graded on fall rate + distance, none of them in the training mix at that setting.

## Iteration 0 — baseline (`auto_gait_final`, per-scenario, 6 ep)

```
scenario            fell   fwd_dist   trot_corr   roll_var
flat (regression)   0.00   1.28       -0.58       0.015
friction +/-0.5     0.00   1.27       -0.62       0.015
mass +/-0.15        0.00   1.28       -0.63       0.014
IMU noise 0.03      0.00   1.28       -0.61       0.014
push 0.35 m/s       0.00   1.23       -0.52       0.017
obstacles 12 mm     0.00   0.87       -0.43       0.011   <- the real hit (-32% distance)
```

Read: already more robust than expected — 0 falls everywhere at these magnitudes.
Dynamics variation (friction/mass/noise) barely registers. Pushes cost a little.
**Small obstacles are the one clear weak spot** (slows / hangs up, distance
1.28 -> 0.87), and the training-distribution coverage itself is the sim-to-real
value even where the mild tests already pass.

## Targets (vs. baseline, at the final 2M confirm with everything on)

| Metric | want |
|---|---|
| `fell_fraction` on every scenario | ≤ 0.05 |
| `forward_distance_m` on obstacles 12–15 mm | ≥ 1.1 (from 0.87) |
| `forward_distance_m` on flat | ≥ 1.2 (regression gate) |
| `diagonal_trot_corr` flat | ≤ −0.5 (don't lose the gait) |
| push 0.5 m/s: `fell_fraction` | ≤ 0.10 |

## Levers (one per iteration; 1.5M finetune runs, 2M confirm)

1. **Dynamics bundle** — `RANDOM_FRICTION = 0.5`, `RANDOM_MASS = 0.15`,
   `RANDOM_GYRO = 0.04`. (Grouped: they're the "make the physics uncertain"
   set and individually near-invisible at baseline.)
2. Add `RANDOM_PUSH = 0.5` (+ `RANDOM_PUSH_PROB` if needed).
3. Add `RANDOM_TERRAIN = 0.015` (scattered obstacles).
4. Tune magnitudes / `DR_RAMP_STEPS` toward the weakest held-out scenario.
5. (reserve) reward tweak — small bonus for returning toward level orientation
   after a disturbance, if push/terrain recovery is still poor.

---

## Iteration 1 — dynamics bundle (friction + mass + IMU noise)

**Change:** `RANDOM_FRICTION = 0.5`, `RANDOM_MASS = 0.15`, `RANDOM_GYRO = 0.04`,
curriculum-ramped. Finetune from `auto_gait_final_ppo`, 1.5M steps.

**Run:** `auto_dr_iter1`, 1.5M steps. _Result pending._
