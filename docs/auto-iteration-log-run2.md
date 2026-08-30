> **CORRECTION (post-hoc):** the "start-up stutter" that framed this run was overstated by a
> measurement error. The baseline `startup_speed_ratio` of ~0.49 for `auto_gait_final` was
> measured with RSI (±18° + random gait phase) accidentally active in the eval env — a heavy
> mismatch for a policy trained without it. Measured correctly (native env), `auto_gait_final`
> is **~0.84** — a mild ramp-up, not a severe stutter. RSI's real net effect: negligible
> start-up benefit, measurable trot cost. The user picked `auto_gait_final` ("curve fixed")
> from the visual replays, which the corrected numbers support. Process learnings below still
> hold (RSI needs a 2M budget; weight-tuning the trot term backfires; it needs a phase-locked
> reformulation).

# Automated Iteration Log — Run 2 (trot crispness + foot-clearance evenness)

Branch: `auto-gait-iteration`, synced from `development` @ `87af0bc` (Run 1 merged).
Started: 2026-08-30 ~13:52. Caps: 3 h wall-clock OR 5 iterations, whichever first.
Iteration runs: 1M steps (~19 min). Final confirming run: 2M steps.
Stop early: create `rl_training/opencat-gym/STOP`, or interrupt the session.

## Why a second run

Two issues in Run 1's final policy (`auto_gait_final`, 2M):

1. **Start-of-episode stutter** (user-reported): G2 hesitates when it starts
   walking, then smooths out. Quantified — `startup_speed_ratio` = **0.49**: the
   robot covers only ~half its settled speed in the first 0.5 s. Cause: every
   episode starts from the *one* fixed reset pose with the gait-phase clock at 0,
   so the policy always has to settle out of that exact static configuration.
   Fix: **reference-state initialization** (pre-loop change, below).
2. **Trot crispness**: `diagonal_trot_corr` = **−0.59** — under the −0.6 target
   and just below v6's −0.67, even though Run 1's *1M* checkpoints hit −0.90.
   `FAC_GAIT_SYMMETRY = 3.5` (unramped) shapes the trot early but its magnitude
   (~0.04/step vs. a ~5/step forward reward) is too small to hold it once the
   policy converges hard on speed + heading in the second 1M steps.

## Pre-loop change — reference-state initialization (RSI)

`opencat_gym_env.py` `reset()`, applied before the loop iterates (a change to the
initial-state distribution, outside "reward shaping", so it's a deliberate one):

- `RSI_JOINT_NOISE_DEG = 18` — each episode's start pose = the fixed pose ± up to
  18° of uniform noise per joint (clipped to joint limits).
- `RSI_RANDOMIZE_PHASE = True` — the `TIME_PHASE` clock starts at a random offset
  each episode (new `self.phase_offset`), so "gait phase" is decoupled from
  "steps since reset".

Verified: `check_env` passes, phase offset varies per reset, 0/8 immediate falls
holding a neutral pose from the perturbed start, smoke test clean (reward lower
than usual — the task is genuinely harder with varied starts, as intended).

New eval metrics in `evaluate_policy.py`: `startup_speed_ratio` (first-25-step
speed / next-50-step speed; ~1 = no stutter) and `startup_jerk_ratio`.

_(Run 2 iteration 1 was briefly launched as `FAC_GAIT_SYMMETRY` 3.5→8.0, then
stopped and superseded by this RSI-first plan; `FAC_GAIT_SYMMETRY` is back at 3.5.)_

**Diagnosis:** `FAC_GAIT_SYMMETRY = 3.5` is applied unramped and shapes the trot
early — but the term's magnitude is tiny (a product of two small normalized
joint-angle deltas, ~1e-2, ×3.5 ≈ 0.04/step, vs. a forward reward of ~5/step). In
Run 1's second 1M steps the reward climbed 757 → 1180 and `std` fell 0.91 → 0.65:
the policy optimized hard against the `FAC_MOVEMENT`/`FAC_HEADING`-dominated
landscape and the weak symmetry term couldn't hold the trot structure it had
imposed early. Separately, foot peak clearance is uneven at 2M —
[30, 21, 29, 14] mm — the right-rear foot lags.

## Targets (vs. Run 1 final `auto_gait_final` @ 2M)

| Metric | Run 1 final | Target | Note |
|---|---|---|---|
| `fell_fraction` | 0.00 | 0.00 | must not regress |
| `episode_len_mean` | 251 | 251 | must not regress |
| `startup_speed_ratio` | 0.49 | **≥ 0.80** | primary — kill the start stutter |
| `diagonal_trot_corr_mean` | −0.55/−0.59 | **≤ −0.75** | crisper trot at 2M |
| `foot_peak_clearance` (min of 4) | 14 mm | **≥ 18 mm** | even out the lagging foot |
| `yaw_final_deg` (abs) | ~0.2 | ≤ 4 | keep the straight-line win |
| `forward_speed_mps` | 0.24–0.26 | ≥ 0.24 | keep speed |
| `stride_length_m` | 0.103 | ≥ 0.10 | keep |
| `roll_var` | 0.014 | ≤ 0.028 | keep steady |

**Success** = `startup_speed_ratio` ≥ 0.80 AND `diagonal_trot_corr` ≤ −0.75 at 2M,
no regression on falls / heading / speed / stride. Met early → stop, run 2M confirm.

## Planned levers (one per iteration, may reorder on results)

1. **RSI baseline** (no reward change) — does reference-state init fix the stutter?
   any regressions?
2. `FAC_GAIT_SYMMETRY` 3.5 → 8.0 — hold the trot through convergence.
3. Broaden the `gait_symmetry` term to include the knee/elbow joints (idx 1,3,5,7)
   — a fuller, larger trot signal — if #2 is insufficient.
4. New `FAC_CLEARANCE_SYM` term penalizing per-foot peak-clearance spread —
   targets the [30,21,29,14] mm unevenness.
5. (reserve) stride/cadence shaping via the `TIME_PHASE` signal.

Structural options (yaw rate / gravity vector in the observation, `wkF` imitation)
remain out of scope for the loop — flagged to the user if shaping plateaus.

---

## Iteration 0 — baseline (`auto_gait_final`, from Run 1, no RSI)

```
episode_len_mean 251   fell_fraction 0.00
startup_speed_ratio 0.49   startup_jerk_ratio 0.99      <- the stutter
diagonal_trot_corr_mean -0.55
foot_peak_clearance_m [0.0297, 0.0212, 0.0286, 0.0144]  (spread 15.3 mm)
yaw_final_deg -0.16    lateral_drift_final_m 0.045
forward_speed_mps 0.24-0.26   stride_length_m 0.103
roll_var 0.0141   pitch_var 0.00092
```

---

## Iteration 1 — RSI baseline (reference-state initialization only)

**Change:** the RSI reset changes above; no reward change (`FAC_GAIT_SYMMETRY` back
at 3.5). Tests whether starting from varied poses/phases removes the start-up
stutter and whether it costs anything elsewhere.

**Run:** `auto_r2_iter1`, 1M steps, `PPO_15`. **Failed — RSI too aggressive.**

```
                       Run1 final   r2_iter1    verdict
fell_fraction          0.00         1.00        FALLS EVERY EPISODE
episode_len_mean       251          72          tips ~step 72-82
ep_rew_mean (train)    ~757 @1M     175
diagonal_trot_corr     -0.55        +0.06       no trot at all
pitch_var              0.0009       0.194       wild forward pitching
startup_speed_ratio    0.49         0.77        (improved, but irrelevant when it falls)
```

**Diagnosis:** +/-18 deg uniform noise on all 8 joints + a full-cycle random
gait-phase start made the task hard enough that the 1M-step policy (LR decays to
~0 by 1M) never learned a stable gait -- it spends its capacity failing to
recover from wild starts. Bad random poses trip `is_fallen` immediately, so those
episodes give ~no useful gradient. Smoke passing was necessary-not-sufficient (20K
steps, fresh policy -- doesn't reveal a converged policy can't handle it).

**Keep/revert:** revert. RSI is the right idea but needs to be gentle.

---

## Iteration 2 — gentle RSI

**Change:** `RSI_JOINT_NOISE_DEG` 18 -> **6**, `RSI_RANDOMIZE_PHASE` True -> **False**.
Just enough pose variation to break the single-pose overfit that causes the
stutter, without a random phase contradiction ("clock says mid-stride, body
static") on top. If falls stay elevated at 1M, next step is more training budget
(1.5M) rather than less noise.

**Run:** `auto_r2_iter2`, 1M steps, `PPO_16`. **Also failed, but differently.**

```
                       Run1 final   r2_iter2@1M   verdict
fell_fraction          0.00         1.00          falls (~step 205)
ep_len_mean (train)    251          251->~200->217  degrades mid-training
ep_rew_mean (train@1M) ~750         350           far from converged (std still 0.88)
diagonal_trot_corr     -0.55        +0.27         no trot
yaw_final_deg          -0.16        -31           heading control gone
roll_var / pitch_var   .014/.0009   .061/.128     unstable
startup_speed_ratio    0.49         1.04          stutter gone -- but everything else broke
```

**Diagnosis:** even gentle 6 deg RSI can't be learned in **1M steps**. Run 1's
policies needed 2M to become robust on the *easy* fixed-start task; RSI makes it
harder and 1M + LR decaying to 0 runs out of budget before convergence. The
training curve shows it: ep_len holds ~250 for the first ~300K, then degrades as
LR shrinks. The stutter metric "improved" only because the gait fell apart.

**The 1M iteration budget was fine for reward-weight tweaks on an already-solved
task, but RSI changes the task and needs a full 2M.**

**Keep/revert:** keep RSI at 6 deg, give it the proper budget.

---

## Iteration 3 — gentle RSI at full 2M budget

**Change:** none to the env vs. iter2 — same RSI (6 deg, no phase). Only the step
count: **2M instead of 1M**. Single discriminating test: was 1M simply not enough?
If it converges to a stable, straight gait with the stutter gone -> RSI works and
this is the loop's final run. If it still falls -> RSI needs deeper work (LR floor
instead of decay-to-0, or a curriculum ramp of the noise) beyond this loop's
time budget, and the report says so.

**Run:** `auto_r2_iter3`, 2M steps, `PPO_17`. **RSI works at 2M — budget was the
whole problem.**

```
                       Run1 final   r2_iter2(1M,fail)   r2_iter3(2M)   verdict
fell_fraction          0.00         1.00               0.00           FIXED
episode_len_mean       251          205                251            ok
ep_rew_mean (train)    ~1180        350                1110           ~matches Run1
startup_speed_ratio    0.49         1.04               0.79           STUTTER FIXED (0.49 -> 0.79)
forward_speed_mps      0.256        0.09               0.250          held
forward_distance_m     1.29         0.37               1.256          held
roll_var / pitch_var   .014/.0009   .061/.128          .004/.001      steadier than Run1
foot_peak_clearance_m  [30,21,29,14] [24,11,57,22]     [21,18,17,14]  more even than Run1
yaw_final_deg (abs)    0.16         31                 6.1            looser than Run1 (was dead straight)
diagonal_trot_corr     -0.59        +0.27              -0.37          LOOSER -- RSI variation relaxed it further
stride_length_m        0.103        0.030              0.055          shorter than Run1
```

**Diagnosis confirmed:** RSI changes the task and needs the full 2M budget; at 1M
the LR decays to ~0 before convergence. At 2M the training curve is healthy
(ep_len 251 throughout, ep_rew 54 -> 1110, std 0.96 -> 0.61, no collapse).

**Result:** the **start-up stutter is fixed** (`startup_speed_ratio` 0.49 -> 0.79,
target was 0.80) with no fall regression, speed held, and the body actually
steadier and feet more even than Run 1. **Costs:** the trot loosened further
(-0.59 -> -0.37), strides shortened (0.103 -> 0.055), heading is looser (0.16 ->
6.1 deg, mildly re-accumulating). These are exactly what Run 3 targets.

## Run 2 end

Stopped after iter3. 3 iterations (2 failed 1M RSI attempts + the 2M fix), ~1h40m.
**Deliverable: RSI at `RSI_JOINT_NOISE_DEG = 6` (no phase randomization), trained
2M.** Policy `trained/auto_r2_iter3_ppo`. All on `auto-gait-iteration`, not merged
— Run 3 (trot) stacks on top; combined review + merge after Run 3.
Report: `docs/auto-iteration-report-2026-08-30-run2.md`.
