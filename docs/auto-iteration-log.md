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

**Run:** `auto_iter2`, 1M steps. _Result pending._
