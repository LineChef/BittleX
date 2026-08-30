> **CORRECTION (post-hoc):** the "start-up stutter" that framed this run was overstated by a
> measurement error. The baseline `startup_speed_ratio` of ~0.49 for `auto_gait_final` was
> measured with RSI (±18° + random gait phase) accidentally active in the eval env — a heavy
> mismatch for a policy trained without it. Measured correctly (native env), `auto_gait_final`
> is **~0.84** — a mild ramp-up, not a severe stutter. RSI's real net effect: negligible
> start-up benefit, measurable trot cost. The user picked `auto_gait_final` ("curve fixed")
> from the visual replays, which the corrected numbers support. Process learnings below still
> hold (RSI needs a 2M budget; weight-tuning the trot term backfires; it needs a phase-locked
> reformulation).

# Automated Gait-Iteration Report — Run 3 (trot crispness)

**Loop:** unattended, on `auto-gait-iteration`, stacked on Run 2 (RSI stutter fix).
**Goal:** tighten the diagonal trot, which loosened in Run 2 (`diagonal_trot_corr`
−0.59 → −0.37) as a side effect of the RSI change.
**Window:** ~15:20–16:45, 2 tuning iterations + 1 confirming run.

---

## TL;DR

**Weight-tuning `FAC_GAIT_SYMMETRY` cannot fix this.** Three attempts bracketed it:

| effective weight | `diagonal_trot_corr` @ 2M with RSI |
|---|---|
| ~1.0 (decay-to-0.3 ramp) | **−0.10** (trot dissolves) |
| 3.5 (flat — Run 2's value) | **−0.37** (best available) |
| 9.0 (flat) | **−0.26** (policy games the term) |

The `gait_symmetry` reward is `-diagonal_a * diagonal_b` — an *instantaneous*
product of joint-angle deltas. Raise the weight and the policy maximizes that
instantaneous quantity with sharp frame-to-frame alternation that isn't a
periodic trot; lower it and the trot just fades. It's the wrong shape.

**Deliverable:** no change from Run 2. Ship Run 2's config — RSI ±6°, flat
`FAC_GAIT_SYMMETRY = 3.5` — policy `trained/auto_r2_iter3_ppo`. The decay ramp is
reverted. (An explanatory comment is left in `opencat_gym_env.py`.)

**One genuine trade to decide** — see "Two candidate policies" below.

---

## Iterations

| # | change | steps | result |
|---|---|---|---|
| 1 | `FAC_GAIT_SYMMETRY` 3.5 → 9.0 (RSI off) | 1M | trot **worse**: corr −0.90 (ref) → −0.26. Stronger weight → the policy games the instantaneous term. |
| 2 | 3.5 with a weight decaying 1.0 → 0.3 over 1M (RSI off) | 1M | Can't judge at 1M — the ramp is a *training-length schedule*, at floor by 1M. Went to the 2M confirm. |
| — | confirming: decay ramp + RSI ±6° | 2M | Everything **but** the trot improved (see table); trot **collapsed** to −0.10. |

## Two candidate 2M policies (both: RSI, stutter fixed, never fall)

| metric | **`auto_r2_iter3`** (flat 3.5) | `auto_r3_final` (decay ramp) |
|---|---|---|
| `diagonal_trot_corr` | **−0.37** | −0.10 |
| `startup_speed_ratio` | 0.79 | **0.86** |
| `forward_speed_mps` | 0.250 | **0.264** |
| `forward_distance_m` | 1.256 | **1.327** |
| `yaw_final_deg` (abs) | 6.1 | **3.4** |
| `roll_var` / `pitch_var` | .004 / .001 | **.003 / .0006** |
| `foot_peak_clearance` mm | **[21,18,17,14]** | [17,13,14,11] |
| `stride_length_m` | 0.055 | 0.063 |

`auto_r3_final` is better on almost every number — faster, straighter, steadier,
smoother start — **but it doesn't trot** (−0.10 ≈ no diagonal pattern). `auto_r2_iter3`
keeps a real, if not crisp, diagonal trot (−0.37, vs v6's −0.67 which you found
looked good).

**Recommendation:** ship `auto_r2_iter3` (flat 3.5). The diagonal trot is a stated
goal; −0.10 means it isn't trotting. Watch both replays before deciding.

---

## Recommended next step (not weight tuning)

Redesign `gait_symmetry` as a **phase-locked** reward: reward the diagonal leg
pairs being in antiphase *relative to the `TIME_PHASE` clock* (which is already in
the observation), or reward the diagonal-pair correlation over a rolling window —
so the reward optimizes the same thing the metric (and the goal) measure. This is
a term redesign, ~1–2 focused iterations, and belongs in its own run.

## How to review

- **TensorBoard:** `PPO_6` (v6) · `PPO_8–13` (Run 1) · `PPO_15,17` (Run 2 RSI) ·
  `PPO_18–20` (Run 3). http://localhost:6006/
- **Replays:**
  - recommended: `g2watch trained/auto_r2_iter3_ppo`
  - the ramp version: `g2watch trained/auto_r3_final_ppo`
  - Run 1 for reference: `g2watch trained/auto_gait_final_ppo`
- **Detail:** `docs/auto-iteration-log-run3.md`, `docs/auto-iteration-log-run2.md`
