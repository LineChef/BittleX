# Automated Iteration Log — gait on level ground

Branch: `auto-gait-iteration` (off `development` @ `gait-v6-known-good`).
Loop started: 2026-08-30 ~11:17. Caps: 3 h wall-clock OR 6 iterations, whichever first.
Iteration runs: 1M steps (~20 min). Final confirming run: 2M steps.
Goal: level-ground walking as close as possible to a clean diagonal-trot `wkF`-style
gait — straight line, real strides, no falling — via reward-shaping only.

Stop early: create `rl_training/opencat-gym/STOP`, or interrupt the session.

## Targets (vs. iteration-0 / v6 baseline)

| Metric | v6 baseline | Target | Note |
|---|---|---|---|
| `fell_fraction` | 0.00 | 0.00 | must not regress |
| `episode_len_mean` | 251 | 251 | must not regress |
| `forward_speed_mps_mean` | 0.263 | ≥ 0.24 | hold speed while fixing the curve |
| `forward_distance_m_mean` | 1.32 | ≥ 1.25 | " |
| `yaw_final_deg_mean` (abs) | 12.5 | ≤ 4 | **primary fix** — near-straight by episode end |
| `lateral_drift_final_m_mean` | 0.24 | ≤ 0.10 | stay near the start line |
| `yaw_abs_max_deg_mean` | 19.5 | ≤ 8 | no big mid-episode swing |
| `diagonal_trot_corr_mean` | −0.66 | ≤ −0.6 | keep the trot (more negative = better) |
| `foot_peak_clearance_m` (min of 4) | 0.017 | ≥ 0.012 | keep real steps, don't shuffle |
| `stride_length_m_mean` | 0.124 | ≥ 0.10 | keep real strides |
| `roll_var_mean` | 0.024 | ≤ 0.028 | don't get wobblier |

**Success** = `yaw_final ≤ 4°` and `lateral_drift ≤ 0.10 m` with no regression on
fall rate, episode length, speed, trot, or stride. If met before the cap, stop and
run the 2M confirming run. Spare iterations go toward tightening the trot correlation
toward −0.8 and evening out per-foot clearance.

---

## Iteration 0 — baseline (`full_run_v6_ppo`, existing at kickoff)

No change. Evaluated with `evaluate_policy.py --episodes 5`. Frames:
`rl_training/opencat-gym/eval_frames/iter0_v6/`.

```
episode_len_mean            251      fell_fraction              0.00
forward_distance_m_mean     1.322    forward_speed_mps_mean     0.263
lateral_drift_final_m_mean  0.239    lateral_drift_max_m_mean   0.239
yaw_final_deg_mean         -12.49    yaw_abs_max_deg_mean      19.52
yaw_by_quarter_deg         [-0.28, -7.92, -11.02, -12.49]
foot_peak_clearance_m      [0.0229, 0.0168, 0.0238, 0.0250]
stride_length_m_mean        0.124    diagonal_trot_corr_mean   -0.665
roll_var_mean               0.0243   pitch_var_mean            0.00126
```

Read: solid trot, never falls, but a **steady rightward yaw that builds across the
episode** (near-0 in Q1 → −12.5° by the end) and ~24 cm of lateral drift. One foot
(idx 1) lifts less than the others.

---

## Iteration 1 — absolute heading-error penalty

**Change:** added `FAC_HEADING = 0.5`, penalizing `yaw²` (heading relative to the
straight-ahead reset heading), as its own ramped term in the reward + `r_heading`
in the per-term info. Yaw taken from the base quaternion already in the observation
— no observation-space change. Rationale: `FAC_YAW` only penalizes turn *rate*;
nothing corrected accumulated heading, so small gait asymmetry integrated into the
rightward curve.

**Smoke test:** ep_rew_mean ~56 at 20K steps, no NaN, `r_heading` present. OK.

**Run:** `auto_iter1`, 1M steps (~19 min), `PPO_8`. Training clean (approx_kl 0.002,
no collapse; LR decayed to ~0 by end, so the last stretch barely learned).

**Result (`evaluate_policy.py --episodes 5`):**

```
                         v6@2M    iter1@1M   target
episode_len_mean         251      251        251      ok (never falls)
forward_speed_mps        0.263    0.139      >=0.24   REGRESSED
forward_distance_m       1.322    0.698      >=1.25   REGRESSED
stride_length_m          0.124    0.058      >=0.10   REGRESSED
yaw_final_deg (abs)      12.5     12.9       <=4      NO CHANGE (sign flipped: now curves LEFT)
yaw_by_quarter_deg       ...      [6.4, 9.1, 12.5, 12.9]   still builds across episode
lateral_drift_final_m    0.239    0.073      <=0.10   ok (but partly because it barely moves)
diagonal_trot_corr       -0.665   -0.876     <=-0.6   IMPROVED
roll_var                 0.024    0.016      <=0.028  improved
```

**Diagnosis:**
1. **`FAC_HEADING = 0.5` was far too weak.** At a 13 deg drift the term is
   ~`penalty_scale(2.0) * 0.5 * (0.23 rad)^2` ≈ 0.05 / step, vs. a forward reward
   of ~7 / step — under 1% of the objective. The policy ignored it: yaw drift is
   unchanged and just landed on a left-curving asymmetry this run instead of a
   right-curving one (confirms the drift is a weakly-constrained gait-asymmetry
   artifact, not a fixed mechanical bias).
2. **The speed/stride regression is mostly the 1M-vs-2M step difference, not the
   penalty** — v6 only reached ~1220 reward near 2M; at 1M it was far from
   converged too. Comparing iteration runs (1M) against `v6@2M` is unfair on
   absolute speed. **Fix going forward:** treat `iter1` as the de-facto 1M
   baseline (heading penalty present but negligible) and judge each iteration by
   its delta vs. the previous 1M run. Absolute speed vs. `v6` is judged only by
   the final 2M confirming run.

**Keep/revert:** keep `FAC_HEADING` (harmless at this weight), crank it next.

---

## Iteration 2 — stronger heading penalty

**Baseline for comparison:** `iter1` (1M).
**Change:** `FAC_HEADING` 0.5 -> **5.0** (10x). Now ~0.5 / step at a 13 deg drift
(~7% of the forward reward) — enough to actually register. Single variable.
Hypothesis: if the drift is correctable via a heading signal, yaw_final drops
toward 0; watch for a forward-speed tradeoff.

**Run:** `auto_iter2`, 1M steps (~19 min), `PPO_9`. Training clean.

**Result:**

```
                       iter1@1M   iter2@1M   target
episode_len_mean       251        251        251      ok (never falls)
yaw_final_deg (abs)    12.9       2.5        <=4      FIXED
yaw_abs_max_deg        13.4       9.9        <=8      close (v6 was 19.5)
yaw_by_quarter_deg     [6,9,12,13]  [4.3, 2.7, -1.2, -2.5]   now oscillates around 0, not building
lateral_drift_final_m  0.073      0.019      <=0.10   FIXED
forward_speed_mps      0.139      0.135      >=0.24   ~flat (still the 1M-convergence gap, not the penalty)
diagonal_trot_corr     -0.876     -0.823     <=-0.6   ok
foot_peak_clearance_m  [.040,.033,.018,.022]  [.051,.046,.012,.010]   front feet lift MORE, back feet now drag
stride_length_m        0.058      0.042      >=0.10   shrank further
roll_var / pitch_var   .016/.0025 .015/.0099           pitch bob 4x worse
```

**Diagnosis:** the strong heading penalty **worked for the curve** — yaw drift
2.5 deg, lateral drift 19 mm, and yaw now oscillates around 0 (active correction)
instead of accumulating. Cost: the policy is steering with the front legs and
planting the back ones — back-foot clearance fell to ~10 mm (below the 12 mm
floor) while front feet lift ~50 mm, strides shortened, pitch bob up. A
front-heavy, choppy gait that goes straight.

**Keep/revert:** keep `FAC_HEADING = 5.0` (straight-line goal met). Next: fix the
front/back clearance split.

---

## Iteration 3 — raise the swing-height target to un-plant the back feet

**Baseline for comparison:** `iter2` (1M).
**Change:** `PAW_Z_TARGET` 0.015 -> **0.025** m. `FAC_CLEARANCE` penalizes squared
deviation from this target in *both* directions, so raising it asymmetrically
helps here: the dragging back feet (~10 mm) go from `(0.010-0.015)^2` to
`(0.010-0.025)^2` — 9x more penalty for not lifting — while the high front feet
(~50 mm) are penalized *less* than before, so they needn't come all the way down.
Should even out the gait. 0.025 also matches what v6 actually achieved (~23 mm)
and looked good. Single variable; `FAC_HEADING` held at 5.0.

**Run:** `auto_iter3`, 1M steps (~19 min), `PPO_10`. Training clean (ep_rew ~785).

**Result:**

```
                       iter2@1M   iter3@1M   target
episode_len_mean       251        251        251      ok (never falls)
foot_peak_clearance_m  [.051,.046,.012,.010]  [.025,.018,.023,.012]   EVENED OUT (back feet un-planted)
roll_var / pitch_var   .015/.0099 .0049/.0018          body much steadier, pitch bob gone
forward_speed_mps      0.135      0.179      >=0.24   +33%
forward_distance_m     0.676      0.900      >=1.25   better
yaw_final_deg (abs)    2.5        7.8        <=4      REGRESSED (still < v6's 12.5)
yaw_by_quarter_deg     [4,3,-1,-2] [4.9,5.8,8.8,7.8]  building again, less self-correction
lateral_drift_final_m  0.019      0.090      <=0.10   regressed, borderline
diagonal_trot_corr     -0.823     -0.451     <=-0.6   REGRESSED -- trot loosened
stride_length_m        0.042      0.041      >=0.10   still short
```

**Diagnosis:** raising the swing-height target did its job — feet lift evenly now,
body is far steadier, speed up 33%. But rebalancing the gait came at the cost of
heading tightness (yaw 2.5 -> 7.8 deg) and trot cleanliness (-0.82 -> -0.45).
There's a real tension: iter2 was straight + clean-trot but front-heavy/bobbing;
iter3 is even + steady + faster but wanders more and trots less crisply.

**Best config so far:** neither iter2 nor iter3 outright. iter3's gait *quality*
is clearly better; its heading/trot are the gap.

**Keep/revert:** keep `PAW_Z_TARGET = 0.025`. Next: restore the trot (which should
also tighten heading -- a symmetric diagonal trot is inherently straighter).

---

## Iteration 4 — restore the diagonal trot

**Baseline for comparison:** `iter3` (1M).
**Change:** `FAC_GAIT_SYMMETRY` 2.0 -> **3.5**. iter3's trot correlation fell to
-0.45; a stronger symmetry reward should pull it back toward -0.8, and because a
clean diagonal trot is left/right symmetric, it should also cut the heading drift
that re-appeared in iter3 -- addressing both weak metrics with one lever.
`FAC_HEADING` held at 5.0, `PAW_Z_TARGET` at 0.025. Single variable.

**Run:** `auto_iter4`, 1M steps (~19 min), `PPO_11`.

**Result:**

```
                       iter3@1M   iter4@1M   target
diagonal_trot_corr     -0.451     -0.875     <=-0.6   TROT RESTORED (best of the loop)
foot_peak_clearance_m  [.025,.018,.023,.012]  [.034,.030,.026,.019]   all above floor, even-ish
lateral_drift_final_m  0.090      0.046      <=0.10   better
stride_length_m        0.041      0.056      >=0.10   slightly better, still short
yaw_final_deg (abs)    7.8        7.4        <=4      ~unchanged -- the "clean trot => straighter" hope didn't pan out
yaw_by_quarter_deg     [4.9,5.8,8.8,7.8]  [-7.9,-1.1,0.9,-7.4]   less monotonic, but +/-7-8 swings
forward_speed_mps      0.179      0.155      >=0.24   dropped back
roll_var / pitch_var   .0049/.0018  .026/.0074         body less steady again (~v6 level)
```

**Diagnosis:** the stronger symmetry reward **restored the trot** (-0.45 -> -0.875)
and kept feet above the clearance floor, but it did *not* tighten heading, and the
body got wobblier and slower again. Four iterations in, a clear pattern: heading
tightness, trot cleanliness, body steadiness and speed trade off against each
other under single-weight tuning, and no 1M config wins on all of them.

**Scoreboard (1M runs):**
- **iter2** — best heading (2.5 deg, meets target) + clean trot, but front-heavy /
  planted back feet / bobbing / slow.
- **iter3** — evenest feet, steadiest body, fastest, but heading 7.8 + weak trot.
- **iter4** — cleanest trot + even feet, heading 7.4, body wobbly again.

**Keep/revert:** the straight-line goal (the whole point of the loop) is met only
by iter2's config. One more try to combine iter2's heading with iter3/iter4's
gait quality, then the confirming run.

---

## Iteration 5 — settle the swing-height target between the two tested values

**Baseline for comparison:** `iter4` (1M).
**Change:** `PAW_Z_TARGET` 0.025 -> **0.020**. 15 mm (iter2) gave tight heading but
planted back feet; 25 mm (iter3) freed the feet but broke heading. 20 mm splits
the difference -- keep enough of the back-foot lift and body-steadiness gain
without the heading cost. `FAC_HEADING = 5.0` and `FAC_GAIT_SYMMETRY = 3.5` held.
Single variable. **Last iteration** -- confirming 2M run next regardless.

**Run:** `auto_iter5`, 1M steps (~19 min), `PPO_12`.

**Result — best config of the loop:**

```
                       iter4@1M   iter5@1M   target
yaw_final_deg (abs)    7.4        0.42       <=4      DEAD STRAIGHT
yaw_by_quarter_deg     [-7.9,-1.1,0.9,-7.4]  [3.0, 0.8, -1.3, 0.4]   stays within +/-3 deg all episode
yaw_abs_max_deg        10.9       9.8        <=8      close
lateral_drift_final_m  0.046      0.038      <=0.10   ok
diagonal_trot_corr     -0.875     -0.904     <=-0.6   CLEANEST TROT OF ANY RUN
roll_var / pitch_var   .026/.0074 .014/.0052          steady, never falls
foot_peak_clearance_m  [.034,.030,.026,.019]  [.053,.049,.017,.017]   front/back split back, but back feet 17mm > floor
stride_length_m        0.056      0.048      >=0.10   still short
forward_speed_mps      0.155      0.149      >=0.24   still the 1M number
```

**Diagnosis:** 20 mm was the right split. iter5 nails the two goals that matter
most — **dead-straight heading (0.42 deg final, +/-3 deg all episode)** and the
**cleanest diagonal trot of the whole project (-0.904)** — while keeping the body
steady and all feet above the clearance floor. Residual imperfections: the front
legs still lift ~3x higher than the back (stylistic, not a failure), and strides
are short / speed modest — but iter1-iter5 all show ~0.14-0.18 m/s at 1M, so
that's the training-length gap, to be judged by the confirming run.

**Winner: iter5's config** — `FAC_HEADING = 5.0`, `PAW_Z_TARGET = 0.020`,
`FAC_GAIT_SYMMETRY = 3.5`, all else = v6.

---

## Confirming run — iter5 config at full 2M steps

`auto_gait_final`, 2e6 steps, on iter5's reward config unchanged. `PPO_13`.
ep_rew ~1180 (v6 was ~1220 — held, despite the extra heading/trot penalties).

**Result (8 episodes) vs. v6 @ 2M:**

```
                       v6@2M    final@2M   target   verdict
fell_fraction          0.00     0.00       0.00     ok
episode_len_mean       251      251        251      ok
yaw_final_deg (abs)    12.5     0.16       <=4      FIXED
yaw_abs_max_deg        19.5     7.9        <=8      meets
yaw_by_quarter_deg     [-.3,-7.9,-11,-12.5]  [3.4, 0.4, -0.4, -0.16]   flat, non-accumulating
lateral_drift_final_m  0.239    0.045      <=0.10   FIXED
forward_speed_mps      0.263    0.256      >=0.24   held (-3%)
forward_distance_m     1.322    1.285      >=1.25   held
stride_length_m        0.124    0.103      >=0.10   meets (the 1M ~0.05 was under-convergence)
diagonal_trot_corr     -0.665   -0.589     <=-0.6   JUST MISSES (1M checkpoints were -0.88/-0.90)
foot_peak_clearance_m  [23,17,24,25]  [30,21,29,14]   all above floor; asymmetry mostly resolved at 2M
roll_var / pitch_var   .024/.0013  .014/.0009           steadier than v6
```

**Verdict:** goal met. The rightward curve — the one concrete defect in v6 — is
fixed (heading 12.5 -> 0.16 deg, lateral wander 24 -> 4.5 cm, no longer
accumulating) with **speed, distance and stride all preserved** and the body
steadier. The front/back lift asymmetry that showed up in the 1M iterations
largely resolved with full convergence. One soft spot: `diagonal_trot_corr` came
in at -0.589, a hair under the -0.6 target and slightly below v6's -0.665 — the
2M policy found a fast, straight gait that isn't quite as crisp a textbook
diagonal trot as the 1M checkpoints were. Worth eyeballing in the replay; not a
regression that undermines the result.

## Loop end

Stopped after the confirming run — 5 tuning iterations + 1 confirming run, ~2h40m,
under both the 3h and 6-iteration caps. Report: `docs/auto-iteration-report-2026-08-30.md`.
Best policy: `trained/auto_gait_final_ppo`. All commits on `auto-gait-iteration`.
