# Final Gait Run — stride-length reward

Branch: `auto-gait-iteration` (reset to `development` @ `a276e48`). One run, not a
loop. If the result beats `auto_gait_final`, adopt it; otherwise `development`
stays as-is.

## Rationale

`auto_gait_final` walks straight, never falls, ~0.256 m/s — but strides are short
(0.103 m) and the gait reads a bit shuffly; the diagonal trot is loose (−0.59).
Reward-shaping the `gait_symmetry` term is exhausted (Runs 3–4). Different lever:
**nothing in the reward rewards stride *length*.** `FAC_MOVEMENT` rewards body
x-velocity regardless of whether it comes from many short steps or fewer long
ones. A stride reward breaks that tie toward deliberate stepping, which usually
also reads as a cleaner trot.

## Change

New term `FAC_STRIDE = 0.5`, added to the reward:

```
swing_fwd_vel = Σ max(0, world-x velocity of each paw that is OFF the ground)
reward += FAC_STRIDE · swing_fwd_vel
```

Rewards committed forward leg swings. Additive; does not touch `gait_symmetry`.
Raw term ~0.2/step with random actions (higher for a walking policy). Broken out
as `r_stride` in the per-term info. `check_env` + smoke clean.

## Targets (vs. `auto_gait_final` @ 2M)

| Metric | baseline | want |
|---|---|---|
| `stride_length_m` | 0.103 | **↑ (≥ 0.13)** |
| `diagonal_trot_corr` | −0.59 | ≤ −0.59 (not worse; ideally better) |
| `forward_speed_mps` | 0.256 | ≥ 0.24 |
| `fell_fraction` | 0.00 | 0.00 |
| `yaw_final_deg` (abs) | 0.16 | ≤ 4 |
| `roll_var` | 0.014 | ≤ 0.025 |

**Adopt if:** strides clearly longer and the gait reads better (visually + trot
corr no worse), with nothing else regressed. Otherwise keep `auto_gait_final`.

## Run

`auto_stride_final`, 2M steps (RSI off). _Result pending._

## Result — backfired, do not adopt

`auto_stride_final` @ 2M vs `auto_gait_final`:

```
                       auto_gait_final   auto_stride_final
stride_length_m        0.103             0.075   <- SHORTER (the term's own target)
diagonal_trot_corr     -0.59             -0.09   <- trot destroyed
yaw_final_deg (abs)    0.16              8.8     <- curving
lateral_drift_final_m  0.045             0.142   <- wanders 14 cm
forward_speed_mps      0.256             0.255   held
roll_var / pitch_var   .014/.0009        .0077/.0007  steadier
fell_fraction          0.00              0.00
ep_rew_mean (train)    ~1180             1330    (stride term inflates it)
```

**Gamed.** "Forward velocity of airborne feet" is not "long strides" — the policy
maximized it with fast short foot-flicks, which shortened the actual stride,
flattened the trot, and induced yaw. Same failure class as Runs 3–4: optimizing a
reward proxy hard, and it diverges from the goal.

**Decision: do not adopt.** `development` stays at `a276e48` (`auto_gait_final`).
This log stays on `auto-gait-iteration` as a record; nothing merges.

## Bottom line after 4 reward-shaping attempts (Runs 3, 4, + this)

Weight tuning, a phase-locked reformulation, a decay ramp, and a stride term —
every one either dissolved the trot / shortened strides at 2M convergence or
regressed heading. `auto_gait_final` sits at a local optimum that reward-shaping
tweaks can't productively push past. Further sim iteration has negative expected
value. The real levers left are structural (phase in the observation, `wkF`
imitation, CPG) and the real validation is the physical robot.
