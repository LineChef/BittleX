# resid-tuning loop — heading + body stability

Branch `resid-tuning` (off `development`). Baseline: `resid_r2` — the first
learned gait to hold `wkF`'s pace *and* match its obstacle fall rate, but it
trails scripted on **heading** (yaw drift 7–10° vs ~5°) and **body roll
variance** on the mid obstacle levels.

**Goal:** close those two gaps without regressing falls (currently at parity) or
pace (~0.10 m/s). Iterate on the **reward system** and the **policy setup**
(action space / observation / net / hyperparameters) in alternating rounds.

## Score (higher = better)

```
score =  −40·avg(yaw_max over 20/35/50 mm)
         −600·avg(roll_var over 20/35/50 mm)
         +20·avg(−trot_corr)
         −HARD:  falls > resid_r2's   -> reject
         −HARD:  flat speed < 0.08 m/s -> reject
```

Each round: one lever, fresh 2M retrain (~42 min), `evaluate_policy.py` +
`benchmark_gaits.py` vs scripted, score, promote/revert (revert to last-good
after 2 non-improving rounds). Stop on `rl_training/opencat-gym/STOP` or
interrupt. Update after each round.

## Baseline — `resid_r2` vs scripted `wkF`

| | flat | 20 mm | 35 mm | 50 mm |
|---|---|---|---|---|
| falls (L / S) | 0/0 | 7/0 | 0/7 | 14/14 |
| speed m/s (L / S) | 0.095/0.091 | 0.072/0.066 | 0.057/0.048 | 0.055/0.038 |
| yaw max° (L / S) | 2.9/2.8 | **10.4**/4.8 | **7.4**/5.0 | 6.2/7.0 |
| roll_var (L / S) | 0.005/0.003 | **0.015**/0.006 | 0.007/0.009 | **0.031**/0.028 |
| trot corr (L / S) | −0.57/−0.50 | −0.54/−0.48 | −0.54/−0.49 | −0.56/−0.48 |

Baseline targets to beat: avg yaw_max (20/35/50) ≈ **8.0°**, avg roll_var ≈ **0.018**.

## Lever bank

| # | Type | Change |
|---|---|---|
| 1 | reward | `FAC_HEADING` 5 → 9 |
| 2 | reward | `FAC_YAW` 0.1 → 0.3 + `FAC_STABILITY` 0.1 → 0.4 (damp roll/yaw rate) |
| 3 | policy | `RESIDUAL_SCALE_DEG` 11 → 8 |
| 4 | reward | residual-smoothness term: `−FAC_RESID_SMOOTH·mean(|action − prev_action|)` |
| 5 | policy | add accumulated heading error + short action history to the observation |
| 6 | reward | `FAC_UPRIGHT` 3 → 6 |
| 7 | — | consolidation: best reward + best policy config together |

---

## R1 — `rtune_r1` — `FAC_HEADING` 5 → 9

Directly penalise accumulated yaw drift harder. Everything else = `resid_r2`.

**Hypothesis:** avg yaw_max drops toward 5–6° with no fall/speed regression;
roll_var roughly unchanged (a straighter gait is often steadier too).

**Result:** _pending_
