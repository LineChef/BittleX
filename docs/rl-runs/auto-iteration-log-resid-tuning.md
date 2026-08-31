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

**Result** (`rtune_r1_ppo`, ~39 min, `ep_len_mean` ~250, `approx_kl` clean —
nothing fell in training). Benchmark vs scripted `wkF`, 14 ep/cell, matched seeds:

| avg over 20/35/50 mm | rtune_r1 | resid_r2 | scripted |
|---|---|---|---|
| yaw max° | 7.73 | 8.01 | 5.62 |
| roll_var | 0.0207 | 0.0177 | 0.0140 |
| falls | 0.071 | 0.071 | 0.071 |
| speed m/s | 0.056 | 0.062 | 0.051 |

Flat speed 0.085 m/s (guard ≥ 0.08 — passes). Score −310.5 vs resid_r2 −320.1.

**Wash — not promoted.** The composite score ticked up, but entirely on a 0.3°
yaw improvement that is within run-to-run noise, and **roll_var regressed**
(0.021 vs 0.018) — the wrong direction for half the goal. Falls stayed at parity
(R1 fixed the 20 mm outlier but picked up a 35 mm fall). Doubling `FAC_HEADING`
did not meaningfully straighten the walk; accumulated-heading penalty alone isn't
the lever. Reverting `FAC_HEADING` to 5 and moving to rate-level damping.

---

## R2 — `rtune_r2` — `FAC_YAW` 0.1 → 0.3 + `FAC_STABILITY` 0.1 → 0.4

`FAC_HEADING` (accumulated error) barely moved yaw in R1. Try the **rate** level
instead: penalise roll/pitch angular velocity (`FAC_STABILITY`) and yaw rate
(`FAC_YAW`) ~3–4× harder, to damp the body oscillation that inflates `roll_var`
and to catch heading drift before it accumulates. Everything else = `resid_r2`.

**Hypothesis:** `roll_var` drops toward scripted's 0.014 and yaw_max toward 6°,
with no fall regression and flat speed ≥ 0.08 m/s. Risk: over-damping stiffens
the correction layer and slows the walk.

**Result** (`rtune_r2_ppo`, ~39 min, `ep_len_mean` 250, `approx_kl` clean).
Benchmark vs scripted `wkF`, 14 ep/cell:

| avg over 20/35/50 mm | rtune_r2 | resid_r2 (baseline) | scripted |
|---|---|---|---|
| yaw max° | **12.92** | 8.01 | 5.62 |
| roll_var | 0.021 | 0.018 | 0.014 |
| falls | **0.095** | 0.071 | 0.071 |
| falls @ 50 mm | **0.214** | 0.143 | 0.143 |

**Rejected — hard fall guard (`falls > resid_r2`).** Over-damping backfired: a
stiffer correction layer reacts too slowly to a 50 mm trip (falls 14 → 21%) and,
counter-intuitively, drifts *worse* on heading (yaw 8 → 13°) — a sluggish
residual can't re-straighten after a stumble. Score −518. Reverted `FAC_YAW` and
`FAC_STABILITY` to 0.1.

**Two rounds, no gain — reward shaping (harder heading penalty, harder rate
damping) is not moving these metrics.** Pivoting to the policy/action side.

---

## R3 — `rtune_r3` — `RESIDUAL_SCALE_DEG` 11 → 8 (policy / action space)

Tighten how far the learned correction may push the joints off the `wkF`
keyframes: ±8° instead of ±11°. If the policy's *own* corrections are what
overshoot into roll oscillation and heading drift, a smaller budget forces it to
stay near the proven-robust scripted pose and only nudge for balance. Everything
else = `resid_r2`.

**Hypothesis:** roll_var and yaw_max both drop (less room to over-correct), falls
stay ≤ baseline, flat speed ≥ 0.08 m/s. Risk: too little authority to catch a
real stumble → falls creep up like `resid_r1`'s reverse case.

**Result:** _pending_
