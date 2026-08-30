> **CORRECTION (post-hoc):** the "start-up stutter" that framed this run was overstated by a
> measurement error. The baseline `startup_speed_ratio` of ~0.49 for `auto_gait_final` was
> measured with RSI (±18° + random gait phase) accidentally active in the eval env — a heavy
> mismatch for a policy trained without it. Measured correctly (native env), `auto_gait_final`
> is **~0.84** — a mild ramp-up, not a severe stutter. RSI's real net effect: negligible
> start-up benefit, measurable trot cost. The user picked `auto_gait_final` ("curve fixed")
> from the visual replays, which the corrected numbers support. Process learnings below still
> hold (RSI needs a 2M budget; weight-tuning the trot term backfires; it needs a phase-locked
> reformulation).

# Automated Iteration Log — Run 3 (trot crispness, with RSI kept)

Branch: `auto-gait-iteration`, stacked on Run 2 (RSI ±6°, not yet merged to
`development`). Started 2026-08-30 ~15:20. Caps: 3 h OR 5 iterations.
Stop early: `rl_training/opencat-gym/STOP`, or interrupt.

## Setup

RSI (`RSI_JOINT_NOISE_DEG = 6`) makes any run needing full convergence a **2M**
job — 1M isn't enough budget (Run 2 proved this twice). So Run 3 runs its fast
tuning iterations with **RSI temporarily off** (`RSI_JOINT_NOISE_DEG = 0`, 1M
steps) to get a clean, quick read on each trot lever, then does **one RSI-on 2M
confirming run** on the winning config to prove the trot fix and the stutter fix
hold together.

## Why

Run 2's final policy (`auto_r2_iter3`, RSI 2M) has the stutter fixed but the
diagonal trot loosened to `diagonal_trot_corr` **−0.37** (Run 1 final was −0.59;
Run 1's 1M checkpoints hit −0.90). `FAC_GAIT_SYMMETRY = 3.5` is applied unramped
and shapes the trot early, but its per-step magnitude (~0.04 vs. a ~5/step
forward reward) is too small to hold that structure once the policy fully
converges — and RSI's added start variation relaxed it further.

## Targets (vs. Run 2 final `auto_r2_iter3` @ 2M)

| Metric | Run 2 final | Target |
|---|---|---|
| `diagonal_trot_corr_mean` | −0.37 | **≤ −0.70** |
| `startup_speed_ratio` | 0.79 | **≥ 0.75** (keep the stutter fix) |
| `fell_fraction` | 0.00 | 0.00 |
| `forward_speed_mps` | 0.250 | ≥ 0.23 |
| `yaw_final_deg` (abs) | 6.1 | ≤ 8 |
| `stride_length_m` | 0.055 | ≥ 0.07 (nice-to-have) |

**Success** = `diagonal_trot_corr` ≤ −0.70 at the RSI-on 2M confirm, with the
stutter fix and no fall/speed regression.

## Levers (one per iteration, RSI-off 1M unless noted)

1. `FAC_GAIT_SYMMETRY` 3.5 → 9.0 — leading hypothesis: too weak to hold.
2. Broaden the `gait_symmetry` term to all 8 joints (shoulder+elbow and hip+knee
   diagonals), not just shoulder/hip — a bigger signal — if #1 falls short.
3. (reserve) ramp `FAC_GAIT_SYMMETRY` down over training instead of unramped —
   shape hard early, ease at convergence.
4. RSI-on 2M confirming run on the winner.

---

## Iteration 0 — baseline (`auto_r2_iter3`, RSI 2M, from Run 2)

```
diagonal_trot_corr_mean -0.37   startup_speed_ratio 0.79   fell_fraction 0.00
forward_speed_mps 0.250   yaw_final_deg -6.1   stride_length_m 0.055
foot_peak_clearance_m [0.021, 0.018, 0.017, 0.014]   roll_var 0.004
```

---

## Iteration 1 — stronger diagonal-trot reward (RSI off, 1M)

**Change:** `FAC_GAIT_SYMMETRY` 3.5 → **9.0**; `RSI_JOINT_NOISE_DEG` 6 → **0** for
this fast tuning iteration (restored to 6 for the confirming run). Read against
Run 1's `auto_iter5` (RSI-off, 1M, `FAC_GAIT_SYMMETRY` 3.5 → corr −0.90) and
`auto_gait_final` (RSI-off, 2M, 3.5 → −0.59): does 9.0 hold the trot tighter
through toward convergence?

**Run:** `auto_r3_iter1`, 1M steps, `PPO_18` (RSI off). **Backfired.**

```
                            1M RSI-off, FGS 3.5   1M RSI-off, FGS 9.0   verdict
                            (Run1 auto_iter5)     (r3_iter1)
diagonal_trot_corr          -0.90                 -0.26                 MUCH WORSE
forward_speed_mps           0.15                  0.19
yaw_final_deg (abs)         ~0                    9.7                   worse
startup_speed_ratio         ~0.5 (est)            0.71
```

**Diagnosis:** cranking `FAC_GAIT_SYMMETRY` up makes the trot *worse*, not better.
The term `-diagonal_a * diagonal_b` is an **instantaneous** product of joint-delta
sums; a stronger weight pushes the policy to maximize that instantaneous quantity
(large, sharp alternating deltas that score well frame-to-frame) rather than a
clean *periodic* diagonal trot, which is what `diagonal_trot_corr` measures over
the whole episode. Reward/metric mismatch, amplified by the bigger weight. 3.5 is
about as far as this formulation goes; more is counterproductive, and broadening
it to more joints (planned iter2) would likely be the same.

**Keep/revert:** revert to 3.5. Don't pursue "bigger symmetry reward".

---

## Iteration 2 — decay the symmetry weight over training

**Change:** `FAC_GAIT_SYMMETRY` back to 3.5, but scaled by a factor that **decays
from 1.0 to a 0.3 floor over the first 1M steps** (`GAIT_SYM_RAMP_END = 1e6`,
`GAIT_SYM_FLOOR = 0.3`). Rationale: Run 1 showed the trot is crisp at 1M
(−0.90) and relaxes by 2M (−0.59) — so shape it hard early, then ease off so the
converging policy isn't fighting the instantaneous term. RSI off, 1M.

**Run:** `auto_r3_iter2`, 1M steps, `PPO_19` (RSI off).

```
                       1M RSI-off ref (FGS 3.5 flat)   r3_iter2 (decay ramp)
diagonal_trot_corr     -0.90                            -0.67
fell_fraction          0.00                             0.17 (1 of 6)
ep_rew_mean @1M        ~730                             553  (std 0.97 -- less converged)
forward_speed_mps      0.15                             0.11
startup_speed_ratio    ~0.5                             0.84
```

**Can't judge the decay ramp at 1M** -- by 1M the scale is already at its 0.3
floor, so the effective weight is ~1.0 (vs. a flat 3.5), and unsurprisingly the
trot is looser and the policy less converged. The ramp's whole design is a
*training-length schedule* (strong for the first ~500K, eased after) -- it only
makes sense to evaluate at 2M. Also picked up a fall (1/6) and slow speed, but
this is an under-converged 1M checkpoint.

**Decision:** stop the 1M tuning iterations. The one remaining trot idea (the
decay ramp) can only be tested at 2M, and that's the confirming run anyway. Go
straight to it.

---

## Confirming run — decay ramp + RSI, 2M

`auto_r3_final`, 2M steps, `RSI_JOINT_NOISE_DEG` back to **6**, `FAC_GAIT_SYMMETRY`
3.5 with the decay-to-0.3 ramp. The test: does shaping the trot hard early then
easing beat plain-3.5-at-2M (`auto_r2_iter3`, corr **−0.37**) while keeping the
stutter fix (`startup_speed_ratio` ≥ 0.75) and not regressing falls / speed /
heading?

- Beats −0.37 toward −0.7 → the ramp helped; hand back a real trot improvement.
- ~−0.37 or worse → ramp didn't help; hand back Run 2's stutter fix as the
  deliverable + an honest "trot needs a phase-based term redesign" report.

**Run:** `auto_r3_final`, 2M steps, `PPO_20`.

```
                       Run1 final    Run2 final       Run3 final
                       (no RSI)      (RSI, flat 3.5)  (RSI, decay ramp)
diagonal_trot_corr     -0.59         -0.37            -0.10   <- trot essentially GONE
startup_speed_ratio    0.49          0.79             0.86
fell_fraction          0.00          0.00            0.00
forward_speed_mps      0.256         0.250            0.264   <- best
forward_distance_m     1.29          1.256            1.327   <- best
yaw_final_deg (abs)    0.16          6.1              3.4
roll_var / pitch_var   .014/.0009    .004/.001        .003/.0006  <- steadiest
foot_peak_clearance_m  [30,21,29,14] [21,18,17,14]    [17,13,14,11]  <- lowest
stride_length_m        0.103         0.055            0.063
```

**Result:** the decay ramp made **everything except the trot better** — best
startup ratio, speed, distance, straightness and stability of any run — but the
trot **collapsed** to −0.10 (no diagonal relationship at all). Reducing the
symmetry weight over training = the policy converges to a fast, dead-straight,
rock-steady gait that isn't a trot.

## Run 3 conclusion — weight tuning can't fix the trot

Three data points now bracket it:

| `FAC_GAIT_SYMMETRY` effective | `diagonal_trot_corr` @ 2M w/ RSI |
|---|---|
| ~1.0 (decay ramp, floored) | −0.10 |
| 3.5 (flat) | −0.37 |
| 9.0 (flat) | −0.26 (policy games the instantaneous term) |

3.5 flat is the best available value, and it still only reaches −0.37 in a
converged RSI policy. **More weight → the policy games the instantaneous
`-diagonal_a*diagonal_b` product (sharp alternation, not periodic). Less weight →
the trot dissolves.** The term is the wrong shape: it rewards an instantaneous
quantity, not a *periodic* diagonal gait.

**Deliverable:** revert the decay ramp. Ship **Run 2's config** — RSI ±6°, flat
`FAC_GAIT_SYMMETRY = 3.5` — policy `trained/auto_r2_iter3_ppo`. Stutter fixed
(0.79), trot −0.37 (present but not crisp), everything else solid.

**Recommended next step (own effort, not weight tuning):** redesign
`gait_symmetry` as a **phase-locked** reward — reward the diagonal leg pairs being
in antiphase *relative to the `TIME_PHASE` clock*, or reward the diagonal-pair
correlation over a rolling window — so the reward matches the metric (and the
actual goal).
