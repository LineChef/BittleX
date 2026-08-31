# Automated Gait-Iteration Report — Run 4 (trot mechanics)

**Loop:** unattended, on `auto-gait-iteration` (reset to `development` @ `d3aef55`).
**Start:** `auto_gait_final` ("curve fixed") — the merged keeper. RSI not in use.
**Goal:** crisper diagonal trot (`diagonal_trot_corr` −0.59 → ≤ −0.75).
**Window:** ~17:55–20:00, 2 iterations + 1 confirming run.

---

## TL;DR

**No improvement. Do not merge.** The `gait_symmetry` reward term was redesigned
from an instantaneous product to a **phase-locked** form —
`(diagonal_a − diagonal_b) · sin(2π · clock)` — so it rewards the diagonal leg
pairs alternating *in rhythm with the gait clock*, which is what the metric
measures. At 1M it looked promising (trot −0.55 → −0.70 with a weight bump,
heading recovered). But **at the full 2M it relaxed to −0.40 — worse than the
baseline's −0.59** — the same collapse-at-convergence seen with the old term in
Run 3.

Keep `auto_gait_final`. Its trot (−0.59) with real strides (0.103 m) beats Run 4's
−0.40 with 0.047 m strides.

---

## Iterations

| # | change | steps | `diagonal_trot_corr` | note |
|---|---|---|---|---|
| 1 | phase-locked term, `FAC_GAIT_SYMMETRY` = 1.0 | 1M | −0.55 | too weak — no change, heading drifted to 17° |
| 2 | weight 1.0 → 3.0 | 1M | **−0.70** | moved toward target, heading recovered to 6° — term works, was under-engaged |
| — | confirming: weight 3.0 | 2M | **−0.40** | **relaxed at convergence — below baseline** |

## `auto_r4_final` vs. the keeper

| metric | `auto_gait_final` (keep) | `auto_r4_final` |
|---|---|---|
| `diagonal_trot_corr` | **−0.59** | −0.40 |
| `stride_length_m` | **0.103** | 0.047 |
| `forward_speed_mps` | **0.256** | 0.238 |
| `yaw_final_deg` (abs) | 0.16 | 0.18 |
| `roll_var` / `pitch_var` | .014 / .0009 | **.003 / .001** |
| `fell_fraction` | 0.00 | 0.00 |

`auto_r4_final` is steadier and just as straight, but slower with a looser trot and
much shorter strides. Net: not better.

## The finding across Runs 3 + 4

Two `gait_symmetry` formulations, ~5 weights, plus a decay ramp. **Every one either
dissolves the trot at 2M convergence or costs forward speed/stride to hold it.** As
the policy converges it trades trot timing for speed + heading, and no reward-side
lever reverses that without a worse tradeoff. Reward shaping has been exhausted
here.

## Real next step — structural (needs your sign-off)

The policy is *penalized* for poor trot timing but can't *sense* it. Options,
outside the reward-shaping loop:

1. **Add the diagonal-pair phase to the observation** — smallest change; lets the
   policy actively hold its trot timing. Costs an obs-space dimension and a fresh
   from-scratch run.
2. **`wkF` reference-imitation bootstrap** — behaviour-clone / trajectory-match
   Bittle's built-in walk, then RL-finetune. The deferred option from the project
   plan.
3. **CPG action space** — the policy modulates a central pattern generator rather
   than raw joint targets. Biggest change, strongest structural prior for a gait.

## How to review

- **HTML page:** the published Artifact (gait GIFs + metrics + this recommendation).
- **TensorBoard:** `PPO_21–23` (Run 4) vs `PPO_13` (`auto_gait_final`).
  http://localhost:6006/
- **Replays:** `g2watch trained/auto_r4_final_ppo` · `g2watch trained/auto_gait_final_ppo`
- **Detail:** `docs/rl-runs/auto-iteration-log-run4.md`
