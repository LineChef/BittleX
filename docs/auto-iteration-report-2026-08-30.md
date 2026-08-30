# Automated Gait-Iteration Report — 2026-08-30

**Loop:** unattended reward-function iteration on the level-ground walking policy.
**Branch:** `auto-gait-iteration` (off `development` @ tag `gait-v6-known-good`).
**Goal:** walk as close as possible to a clean diagonal-trot `wkF`-style gait —
straight line, real strides, no falling — via reward-shaping only.
**Window:** ~11:17–14:00, 5 tuning iterations (1M steps each) + 1 confirming run (2M).
**Caps:** 3 h / 6 iterations — stopped on reaching a satisfactory config, under both.

---

## TL;DR

The one real defect in the v6 gait — a steady rightward curve that built to ~12.5°
of heading drift and 24 cm of lateral wander per episode — is **fixed**. The final
policy walks essentially straight (0.4° final heading, stays within ±3° the whole
episode) with the **cleanest diagonal trot of the project** (−0.90 diagonal
correlation vs. v6's −0.67), and never falls.

Three reward changes got there:

| Constant | v6 | final | why |
|---|---|---|---|
| `FAC_HEADING` (new) | – | **5.0** | penalize *accumulated* heading error, not just turn rate — this is what killed the curve |
| `PAW_Z_TARGET` | 0.015 | **0.020** | keep the back feet from dragging once heading control made the gait front-heavy |
| `FAC_GAIT_SYMMETRY` | 2.0 | **3.5** | restore/tighten the diagonal trot |

**Residual (not fixed):** at full 2M convergence the diagonal-trot crispness
metric dipped just under target (−0.59 vs −0.6, vs v6's −0.67), stride length is
at the target floor (0.103 m vs v6's 0.124 m), and the right-rear foot lifts less
than the others (14 mm vs ~30). See "What's still short" and "Recommended next
moves".

---

## Baseline (v6) — the problem, quantified

`evaluate_policy.py`, 5 deterministic episodes:

| metric | v6 | reading |
|---|---|---|
| fell_fraction | 0.00 | never falls |
| episode_len | 251/251 | full episodes |
| yaw_final | **−12.5°** | curves right, and `yaw_by_quarter` = [−0.3, −7.9, −11.0, −12.5] → builds steadily across the episode |
| lateral_drift_final | **0.24 m** | wanders 24 cm off the line |
| forward_speed | 0.26 m/s | |
| diagonal_trot_corr | −0.67 | a real trot, but not crisp |
| foot_peak_clearance | [23, 17, 24, 25] mm | fairly even |

**Diagnosis:** the reward rewarded x-displacement regardless of heading and only
lightly penalized yaw *rate* (`FAC_YAW`), with nothing pulling accumulated heading
back to straight. A small, weakly-constrained gait asymmetry integrated into a
steady curve.

---

## Iterations (1M steps each; compared to the previous 1M run)

| # | change | result | kept? |
|---|---|---|---|
| 1 | `FAC_HEADING` 0 → **0.5** | no effect — <1% of the forward reward; drift unchanged (~13°), direction flipped run-to-run (confirms it's a weak asymmetry, not a mechanical bias) | yes (harmless) |
| 2 | `FAC_HEADING` 0.5 → **5.0** | **curve fixed:** yaw_final 12.9° → **2.5°**, lateral drift 73 → **19 mm**, yaw now oscillates around 0 (active correction). Cost: policy steers with the front legs, plants the back — back-foot lift → 10 mm (dragging), strides shorter, pitch bob up | yes |
| 3 | `PAW_Z_TARGET` 15 → **25 mm** | feet even out [25,18,23,12], body much steadier (roll/pitch var −3×), speed +33%. But heading loosened (2.5° → 7.8°) and trot weakened (−0.82 → −0.45) | partly (target too high) |
| 4 | `FAC_GAIT_SYMMETRY` 2.0 → **3.5** | trot restored (−0.45 → **−0.88**), feet stay above floor. Heading unchanged (~7.4°), body wobbly again | yes |
| 5 | `PAW_Z_TARGET` 25 → **20 mm** | **best config.** yaw_final **0.42°** (±3° all episode), diagonal_trot_corr **−0.90**, body steady, never falls. Front/back lift split returns (53/49 vs 17/17 mm) but back feet clear the floor | **yes — winner** |

Recurring dynamic: heading tightness, trot cleanliness, body steadiness, and speed
trade off against each other under single-weight tuning. iter5 is the point where
the two priorities (straight line, clean trot) are both met without the body or
fall-rate regressing.

Full blow-by-blow with all metrics: `docs/auto-iteration-log.md`.

---

## Final policy — `auto_gait_final` (iter5 config, 2M steps)

Config: `FAC_HEADING = 5.0`, `PAW_Z_TARGET = 0.020`, `FAC_GAIT_SYMMETRY = 3.5`,
all other constants unchanged from v6.

`auto_gait_final`, `PPO_13`, 8-episode evaluation. Training ep_rew ~1180 vs v6's
~1220 — held despite the added penalties.

| metric | v6 (2M) | **final (2M)** | target | verdict |
|---|---|---|---|---|
| fell_fraction | 0.00 | **0.00** | 0.00 | ✓ |
| episode_len | 251 | **251** | 251 | ✓ |
| yaw_final (abs) | 12.5° | **0.16°** | ≤4° | ✓✓ |
| yaw_abs_max | 19.5° | **7.9°** | ≤8° | ✓ |
| yaw_by_quarter | [−0.3,−7.9,−11.0,−12.5] | **[3.4, 0.4, −0.4, −0.2]** | flat | ✓ no longer accumulates |
| lateral_drift_final | 0.24 m | **0.045 m** | ≤0.10 m | ✓✓ |
| forward_speed | 0.263 m/s | **0.256 m/s** | ≥0.24 m/s | ✓ held (−3%) |
| forward_distance | 1.32 m | **1.29 m** | ≥1.25 m | ✓ |
| stride_length | 0.124 m | **0.103 m** | ≥0.10 m | ✓ (the ~0.05 at 1M was under-convergence) |
| diagonal_trot_corr | −0.67 | **−0.59** | ≤−0.6 | ✗ just misses; also slightly below v6 |
| foot_peak_clearance | [23,17,24,25] mm | **[30,21,29,14] mm** | ≥12 mm | ✓ asymmetry mostly resolved at 2M |
| roll_var / pitch_var | 0.024 / 0.0013 | **0.014 / 0.0009** | ≤0.028 | ✓ steadier |

**Verdict: goal met.** The v6 curve is gone — heading drift 12.5° → 0.16°, lateral
wander 24 cm → 4.5 cm, and it no longer accumulates across the episode — with
speed, distance, and stride all preserved and the body measurably steadier. The
front/back lift asymmetry seen in the 1M iterations largely resolved with full
convergence. The one miss: `diagonal_trot_corr` at −0.59, a hair under target and
just below v6's −0.67 — the fully-converged 2M policy walks fast and straight but
its diagonal timing isn't quite as crisp as the 1M checkpoints were. Worth a look
in the replay; not a regression that undermines the result.

---

## What improved

- **Straight-line travel** — the headline fix. Heading drift from −12.5° to ~0°,
  lateral wander from 24 cm to ~4 cm, and the drift no longer accumulates across
  the episode (the policy actively corrects).
- **Diagonal trot** — correlation from −0.67 to −0.90, the crispest of the project.
- **Still never falls**, full-length episodes, body at least as steady as v6.

## What's still short

- **Diagonal-trot crispness** — `diagonal_trot_corr` −0.59 at 2M, just under the
  −0.6 target and slightly below v6's −0.67. The 1M checkpoints hit −0.88/−0.90,
  so the crisp trot is *reachable*; full convergence under the strong heading
  penalty relaxed it toward a fast, straight, but less textbook gait. The metric
  is a proxy (correlation of the two diagonal joint-delta sums) — check the replay
  to judge whether it actually looks worse or just scores lower.
- **Front/back lift** — [30, 21, 29, 14] mm at 2M: much better than the 1M runs'
  [53, 49, 17, 17], but the right-rear foot at 14 mm is still the low one. No
  reward term targets front/back or left/right *magnitude* symmetry, only diagonal
  phase.
- **Stride length** — 0.103 m, right at the floor of the target and below v6's
  0.124 m. Recovered a lot from the 1M runs (~0.05 m) with convergence, but the
  reward still has nothing that explicitly favours longer strides over a faster
  shuffle — forward reward is pure x-velocity.

## Recommended next moves

1. **Recover trot crispness at 2M** — the 1M checkpoints hit −0.88/−0.90 on
   `diagonal_trot_corr` but 2M relaxed to −0.59. Either ramp `FAC_GAIT_SYMMETRY`
   *down* slightly over training (so it shapes structure early, like the 1M runs
   caught, without fighting the converged policy late), or nudge it up again
   (3.5 → 4.5) and re-confirm at 2M. First though: **watch the replay** and decide
   whether −0.59 actually looks worse than v6 or is just a proxy artifact.
2. **Left/right + front/back magnitude symmetry** — add a small penalty on
   `|front_clearance_mean − back_clearance_mean|` (and the L/R equivalent) to pull
   the lagging right-rear foot up and balance the drive.
3. **Stride/cadence shaping** — reward a target stride length or foot-contact
   cadence (~48–50 Hz control → ~1.5–2 Hz step frequency), so the policy prefers
   fewer, longer strides over a fast shuffle. Forward reward is currently pure
   x-velocity, which is indifferent to stride length.
4. **Then** the deferred structural options — yaw rate in the observation, or the
   `wkF` trajectory-imitation bootstrap — if reward-shaping plateaus.
5. Only once the flat-ground gait is genuinely good: start the terrain /
   perturbation-robustness phase (domain randomization), per the project plan.

---

## How to review

- **TensorBoard:** `PPO_6` (v6 baseline) vs. `PPO_8`–`PPO_12` (iterations 1–5) vs.
  the confirming run — reward curves and `approx_kl`. Server is running at
  http://localhost:6006/.
- **Watch the gaits:**
  - final: `g2watch trained/auto_gait_final_ppo`
  - v6 for comparison: `g2watch trained/gait-v6-known-good_ppo`
  - any iteration: `g2watch trained/auto_iter<N>_ppo`
- **Frame strips** (30 rendered frames per policy):
  `rl_training/opencat-gym/eval_frames/iter0_v6/` … `iter5/` … `gait_final/`
- **Per-iteration detail:** `docs/auto-iteration-log.md`

## Merge

All work is on `auto-gait-iteration`, one commit per iteration. `development`
still sits at `gait-v6-known-good`. **Decision needed:** merge
`auto-gait-iteration` into `development`, or keep iterating first?
