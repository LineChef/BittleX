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

**Result** (`rtune_r3_ppo`, ~39 min, `ep_len_mean` 251, clean). Benchmark vs
scripted `wkF`, 14 ep/cell:

| | flat | 20 mm | 35 mm | 50 mm | avg 20/35/50 |
|---|---|---|---|---|---|
| yaw max° (r3 / r2 / scr) | 4.9/2.9/2.8 | **6.6**/10.4/4.8 | **5.7**/7.4/5.0 | 13.2/6.2/7.0 | 8.5 / 8.0 / 5.6 |
| roll_var (r3 / r2 / scr) | .006/.005/.003 | **.008**/.015/.006 | .018/.007/.009 | **.039**/.031/.028 | .022 / .018 / .014 |
| falls (r3 / r2 / scr) | 0/0/0 | 0/7/0 | 7/0/7 | **29**/14/14 | 12% / 7% / 7% |
| speed (r3 / r2 / scr) | .097/.095/.091 | .069/.072/.066 | .056/.057/.048 | .046/.055/.038 | 0.057 / 0.062 / 0.050 |

Flat speed 0.097 m/s. Score −342 vs baseline −320.

**Rejected — hard fall guard (12% > 7%), but genuinely informative.** The tighter
±8° budget **fixed heading and roll at 20 & 35 mm** — yaw 6.6°/5.7° (near the
5.6° target, down from 10.4°/7.4°), roll_var at 20 mm below scripted — and lifted
flat speed to 0.097. But at 50 mm it has too little authority to catch a big trip:
falls 14 → 29%, yaw and roll blow out. Confirms the `resid_r1` lesson from the
other side: **residual authority trades heading-tightness at small obstacles
against stumble-catch at big ones.** Reverted to 11.

**Takeaway for R4+:** the corrections themselves are too aggressive/jerky. Attack
that directly without capping magnitude.

---

## R4 — `rtune_r4` — residual-smoothness penalty (reward)

New term: `−FAC_RESID_SMOOTH(6.0) · mean(|action − prev_action|)`, ramped. Keeps
`RESIDUAL_SCALE_DEG` at 11 (full stumble-catch authority) but penalises
frame-to-frame *jerk* in the correction. R3 showed a small, smooth residual
tracks heading well; this rewards smoothness without taking away the authority a
50 mm trip needs. `self._prev_action` added to `reset()`; `r_resid_smooth` in the
info breakdown.

**Hypothesis:** roll_var drops toward 0.014 and yaw toward 6° (smoother
correction = less oscillation) with falls ≤ baseline at *every* level, including
50 mm, and flat speed ≥ 0.08. Risk: too much smoothing = laggy correction, 50 mm
falls creep up anyway.

**Result** (`rtune_r4_ppo`, ~40 min, `ep_len_mean` 250, clean). Benchmark vs
scripted `wkF`, 14 ep/cell:

| | flat | 20 mm | 35 mm | 50 mm | avg 20/35/50 |
|---|---|---|---|---|---|
| yaw max° (r4 / r2 / scr) | 4.7/2.9/2.8 | **5.4**/10.4/4.8 | **5.8**/7.4/5.0 | **7.1**/6.2/7.0 | **6.1** / 8.0 / 5.6 |
| roll_var (r4 / r2 / scr) | .004/.005/.003 | **.004**/.015/.006 | .015/.007/.009 | .029/.031/.028 | **.016** / .018 / .014 |
| falls (r4 / r2 / scr) | 0/0/0 | 0/7/0 | 7/0/7 | 14/14/14 | 7% / 7% / 7% |
| speed (r4 / r2 / scr) | .085/.095/.091 | .068/.072/.066 | .053/.057/.048 | .047/.055/.038 | 0.056 / 0.062 / 0.050 |
| trot (r4 / r2 / scr) | −.59/−.57/−.50 | −.57/−.54/−.48 | −.57/−.54/−.49 | −.58/−.56/−.47 | −0.57 / −0.55 / −0.48 |

Flat speed 0.085 m/s (guard OK). Score **−243** vs baseline −320 — best of the loop.

**PROMOTED — `rtune_r4` is the new baseline.** The smoothness penalty did exactly
what the hypothesis said: penalising frame-to-frame jerk (not magnitude) cut the
correction's oscillation, so **heading dropped from 8.0° → 6.1°** (0.5° off the
scripted target; at 20 mm it's 5.4° vs scripted's 4.8°) and **roll_var 0.018 →
0.016** (below scripted at 20 mm). Falls unchanged at every level — same 0/0/7/14
profile as scripted. Trot got crisper. The only cost: flat speed slipped 0.095 →
0.085, still above the floor but now close to it — the smoother residual walks a
touch slower. That sets up R5.

---

## R5 — `rtune_r5` — speed as a true set-point (reward) — _plan_

Motivation (from the builder): speed should be a **commanded value**, not
something to maximise — "when I say walk I want a specific speed; too slow is also
bad." Right now `FAC_MOVEMENT = 1000` with `MOVEMENT_CAP_AT_TARGET = False` is an
uncapped "every mm forward pays" term; the policy funds overspeed by spending
residual budget → swerve/wobble. R4's smoothness penalty already pulled speed
down toward target; make that the explicit objective.

Changes vs `rtune_r4`:
- `MOVEMENT_CAP_AT_TARGET` → **True** (progress reward stops accruing above
  `TARGET_SPEED`).
- `FAC_MOVEMENT` 1000 → **300** (de-emphasise raw progress; the Gaussian speed
  tracker + `MIN_SPEED` floor carry pace).
- New `−FAC_OVERSPEED · max(0, v − TARGET_SPEED)` term (symmetric with the
  `MIN_SPEED` floor).
- Cadence knob: `_phase += 1.1` per step (reference gait ~10 % faster) so the
  base open-loop walk still hits ~0.10 m/s once the progress incentive is gone.
- Loop guard change: flat speed band **0.085–0.125 m/s** (was: reject if < 0.08),
  so overspeed is scored against too.

**Hypothesis:** flat speed sits ~0.09–0.10 m/s (not drifting up, not stalling),
heading/roll hold R4's gains or improve, falls ≤ baseline.

**Result:** _pending builder go-ahead_
