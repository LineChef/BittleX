# Automated Iteration Log — Run 4 (trot mechanics)

Branch: `auto-gait-iteration` (reset to `development` @ `d3aef55`). Started
2026-08-30 ~17:55. Caps: 3 h OR 4 iterations. RSI is **not** in use (set aside
after Runs 2–3). Stop early: `rl_training/opencat-gym/STOP`, or interrupt.

## Why

Keeper policy `auto_gait_final` ("curve fixed") walks straight, never falls, mild
start-up ramp (`startup_speed_ratio` 0.84) — but the diagonal trot is only
`diagonal_trot_corr` **−0.59**. Run 3 established that **weight-tuning the old
`gait_symmetry` term can't fix this**: it rewarded an *instantaneous*
`-diagonal_a*diagonal_b` product, and turning it up made the policy game it while
turning it down dissolved the trot.

## Change (term redesign — in this run's baseline)

`gait_symmetry` reformulated to be **phase-locked** to the `TIME_PHASE` clock:

```
trot_clock    = sin(2π · time_obs)
gait_symmetry = (diagonal_a − diagonal_b) · trot_clock
```

Diagonal A (front-right + back-left) leads while the clock is positive, diagonal B
(front-left + back-right) leads while it's negative — a rhythmic antiphase gait,
which is what `diagonal_trot_corr` measures. New term is ~1000× the old one's raw
scale, so `FAC_GAIT_SYMMETRY` drops 3.5 → **1.0** (~8% of a walking policy's
forward reward). Smoke test clean.

## Targets (vs. `auto_gait_final` @ 2M, native env)

| Metric | baseline | Target |
|---|---|---|
| `diagonal_trot_corr_mean` | −0.59 | **≤ −0.75** |
| `fell_fraction` | 0.00 | 0.00 |
| `yaw_final_deg` (abs) | 0.16 | ≤ 4 |
| `forward_speed_mps` | 0.256 | ≥ 0.23 |
| `startup_speed_ratio` | 0.84 | ≥ 0.78 |
| `stride_length_m` | 0.103 | ≥ 0.09 |
| `roll_var` | 0.014 | ≤ 0.025 |

**Success** = `diagonal_trot_corr` ≤ −0.75 at the 2M confirming run with nothing
else regressed.

## Levers (one per iteration, 1M each, 2M confirm at end)

1. Phase-locked term + `FAC_GAIT_SYMMETRY = 1.0` — does the reformulation produce
   a crisp trot at all?
2. Tune `FAC_GAIT_SYMMETRY` (0.5 / 2 / 3) based on iter1 — too weak → looser trot;
   too strong → fights forward speed / a mincing in-place trot.
3. (reserve) also phase-lock on absolute joint positions, not just deltas, if the
   delta form is too noisy.

---

## Iteration 0 — baseline (`auto_gait_final`, native env, 8 ep)

```
diagonal_trot_corr -0.589   startup_speed_ratio 0.839   fell_fraction 0.00
forward_speed 0.256   forward_distance 1.285   yaw_final -0.16
stride_length 0.103   roll_var 0.014
```

## Iteration 1 — phase-locked trot term, weight 1.0

**Run:** `auto_r4_iter1`, 1M steps (RSI off), `PPO_21`.

```
                       old term @1M   phase-lock @1M (w=1.0)   baseline @2M
diagonal_trot_corr     -0.90          -0.55                    -0.59
yaw_final_deg (abs)    ~0             17.3                     0.16
forward_speed_mps      0.15           0.185                    0.256
stride_length_m        ~0.06          0.030                    0.103
fell_fraction          0.00           0.00                     0.00
std (train)            ~0.90          0.929                    0.65
```

**Read:** the reformulated term at weight 1.0 **did not improve the trot** (−0.55,
same as baseline) and heading regressed to 17° with tiny strides. Frame check:
body visibly yawed, tight leg stance — no clear trot. Under-converged at 1M
(std 0.93), but the old term at the same 1M point reached −0.90, so weight 1.0 is
clearly too weak to engage the new signal.

**Next:** bump the weight. Watching heading — if it worsens with a stronger
weight, the `(diagonal_a − diagonal_b)` form is inducing yaw and needs rethinking;
if heading recovers and trot tightens, weight was the issue.

## Iteration 2 — phase-locked trot term, weight 3.0

**Run:** `auto_r4_iter2`, 1M steps (RSI off), `PPO_22`.

```
                       baseline @2M   iter1 @1M (w=1.0)   iter2 @1M (w=3.0)
diagonal_trot_corr     -0.59          -0.55              -0.70   <- improving
yaw_final_deg (abs)    0.16           17.3               6.0     <- recovered
forward_speed_mps      0.256          0.185              0.139   <- low (1M + term cost)
stride_length_m        0.103          0.030              0.039
fell_fraction          0.00           0.00               0.00
std (train)            0.65           0.93               0.96
```

**Read:** the weight bump moved the trot the right way (−0.55 → −0.70, toward the
−0.75 target) **and** heading recovered (17° → 6°) — so iter1's yaw was the term
being under-engaged, not the `(diagonal_a − diagonal_b)` form inducing yaw. The
term isn't broken. Forward speed and strides are low, but this is a 1M
under-converged checkpoint (std 0.96); Run 1 showed both roughly double from
1M → 2M.

**Decision:** worth a 2M confirming run. The question: does the phase-locked term
*hold* a crisp trot (≤ −0.75) through full convergence — the thing the old term
couldn't — with speed/stride recovering?

## Confirming run — phase-locked trot term, weight 3.0, 2M

**Run:** `auto_r4_final`, 2M steps (RSI off), `PPO_23`.

```
                       baseline @2M   iter2 @1M   auto_r4_final @2M
diagonal_trot_corr     -0.59          -0.70       -0.40   <- REGRESSED at 2M
yaw_final_deg (abs)    0.16           6.0         0.18    <- dead straight again
forward_speed_mps      0.256          0.139       0.238   <- mostly recovered
forward_distance_m     1.285          0.70        1.195
stride_length_m        0.103          0.039       0.047   <- still short
roll_var / pitch_var   .014/.0009     .010/-      .003/.001  <- steadiest of any run
startup_speed_ratio    0.84           0.76        0.76
fell_fraction          0.00           0.00        0.00
```

**Result — the reformulation did not beat the old term.** Same pattern as Run 3:
the trot is crisp-ish at 1M (−0.70) and **relaxes at 2M convergence to −0.40** —
worse than the baseline's −0.59. The phase-locked term *is* better shaped in other
ways (heading stayed dead straight at 2M; body is the steadiest of any run) but it
does not produce a crisper trot at convergence, and strides shrank.

## Run 4 conclusion — reward shaping can't crisp the trot at 2M

Across Runs 3 and 4: **two `gait_symmetry` formulations** (instantaneous
`-diagonal_a*diagonal_b`, and phase-locked `(diagonal_a-diagonal_b)*sin(clock)`),
**~5 weights** (0.5, 1, 3, 3.5, 9, plus a decay ramp). Every one either dissolves
the trot at 2M convergence or costs forward speed/stride to hold it. The policy
consistently trades trot timing for speed + heading as it converges, and no
reward-side lever reverses that without a worse tradeoff.

**Deliverable: no merge.** Keep `auto_gait_final` ("curve fixed") — trot −0.59
with real 0.103 m strides beats `auto_r4_final`'s −0.40 with 0.047 m strides. The
Run 4 log/report are brought to `development` as a record; the reformulated term
is **not**.

**Real next step (structural, needs sign-off):** the policy can't *sense* its own
trot timing — `gait_symmetry` only penalizes it. Options: add the diagonal-pair
phase to the observation; a `wkF` reference-imitation bootstrap; or a CPG action
space. All outside the reward-shaping loop.
