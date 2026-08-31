> **CORRECTION (post-hoc):** the "start-up stutter" that framed this run was overstated by a
> measurement error. The baseline `startup_speed_ratio` of ~0.49 for `auto_gait_final` was
> measured with RSI (±18° + random gait phase) accidentally active in the eval env — a heavy
> mismatch for a policy trained without it. Measured correctly (native env), `auto_gait_final`
> is **~0.84** — a mild ramp-up, not a severe stutter. RSI's real net effect: negligible
> start-up benefit, measurable trot cost. The user picked `auto_gait_final` ("curve fixed")
> from the visual replays, which the corrected numbers support. Process learnings below still
> hold (RSI needs a 2M budget; weight-tuning the trot term backfires; it needs a phase-locked
> reformulation).

# Automated Gait-Iteration Report — Run 2 (start-up stutter)

**Loop:** unattended, on `auto-gait-iteration` (stacked on Run 1's merge).
**Goal:** fix the start-of-episode stutter G2 shows when it begins walking.
**Window:** ~13:52–15:25, 3 iterations, ~1h40m.
**Note:** per the user's instruction, no visual review for this run — analysis only.
Run 3 (trot) follows immediately; the full visual/TensorBoard hand-back happens
after Run 3.

---

## TL;DR

The stutter is **fixed** by reference-state initialization (RSI): perturbing the
reset pose by ±6° per joint so the policy no longer overfits to settling out of
one fixed static pose. `startup_speed_ratio` (first-0.5s speed ÷ settled speed)
went **0.49 → 0.79** with no falls, speed held, and the body steadier than before.

The catch: RSI needs the **full 2M training budget** — two attempts at 1M steps
both collapsed (policy fell every episode) because the learning rate decays to ~0
before the harder task converges.

Side effects, all now targeted by Run 3: the diagonal trot loosened
(`diagonal_trot_corr` −0.59 → −0.37), strides shortened (0.103 → 0.055 m), and
heading drift is looser (0.16° → 6.1° final).

---

## Change

`opencat_gym_env.py` `reset()` — reference-state initialization:

| Constant | Value | Effect |
|---|---|---|
| `RSI_JOINT_NOISE_DEG` | **6** | reset pose = fixed pose ± up to 6° uniform per joint (clipped to limits) |
| `RSI_RANDOMIZE_PHASE` | **False** | (tried True at 18° — too much; off for now) |

Plus new eval metrics in `evaluate_policy.py`: `startup_speed_ratio`,
`startup_jerk_ratio`.

## Iterations

| # | change | steps | result |
|---|---|---|---|
| 1 | RSI ±18° + random gait phase | 1M | **failed** — fell every episode (ep_len 72), no trot, wild pitching. Too aggressive; unlearnable in 1M. |
| 2 | RSI ±6°, no phase | 1M | **failed** — ep_len held ~250 for the first ~300K then degraded to ~200 as LR decayed; fell every episode in eval. |
| 3 | RSI ±6°, no phase | **2M** | **works.** See table below. |

## Final policy — `auto_r2_iter3_ppo` (RSI ±6°, 2M)

| metric | Run 1 final (no RSI) | Run 2 final (RSI, 2M) | note |
|---|---|---|---|
| `startup_speed_ratio` | 0.49 | **0.79** | the fix — target was 0.80 |
| `fell_fraction` | 0.00 | 0.00 | |
| `episode_len_mean` | 251 | 251 | |
| `forward_speed_mps` | 0.256 | 0.250 | held |
| `forward_distance_m` | 1.29 | 1.256 | held |
| `roll_var` / `pitch_var` | .014 / .0009 | **.004 / .001** | steadier |
| `foot_peak_clearance` mm | [30,21,29,14] | [21,18,17,14] | more even |
| `yaw_final_deg` (abs) | 0.16 | 6.1 | looser |
| `diagonal_trot_corr` | −0.59 | −0.37 | looser → Run 3 |
| `stride_length_m` | 0.103 | 0.055 | shorter → Run 3 |

## Why RSI needed 2M

Run 1's policies needed 2M to become robust on the *easy* fixed-start task. RSI
adds start-state variation — a harder task — and `train.py`'s linear LR schedule
decays to 0 over the run. At 1M the LR is spent before the policy converges; at 2M
the curve is healthy the whole way (ep_len 251 throughout, no collapse).

**Implication for future RSI work:** any run with RSI enabled must be 2M steps.
Fast 1M tuning iterations must disable RSI and re-confirm with it at 2M.

## Carried into Run 3

Run 3 keeps RSI ±6° and targets the trot/stride/heading regressions:
`diagonal_trot_corr` ≤ −0.7, without losing `startup_speed_ratio` ≥ 0.75 or
regressing falls / speed / heading. Levers: stronger and/or broader
`FAC_GAIT_SYMMETRY`. Iterations run RSI-off at 1M for speed, with a final RSI-on
2M confirming run.
