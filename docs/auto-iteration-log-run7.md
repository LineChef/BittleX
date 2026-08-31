# Auto-iteration log — Run 7 ("walk": target speed + stumble recovery)

Goal (user, 2026-08-31): from R5 (`gait-v7-stumble-catch`), significantly improve
**stumble recovery** and add a **deliberate target walk speed** the policy always
tries to hold (speed still below gait-match in priority). Call this line "walk" —
perfect walking-speed fundamentals first, faster gaits later.

Branch `auto-gait-iteration`. R5 is the baseline; it is NOT yet merged to
`development`.

## Structural changes this run (env + eval), all in the R1 commit

**Observation** (`SIZE_OBSERVATION` 247 → **273**; forces fresh training, can't
load R5):
- `LENGTH_TILT_HISTORY = 12` steps of (roll, pitch), normalised so the 1.3 rad
  fall line = ±1 — lets the policy see a stumble as a developing trajectory.
- roll/pitch **angular acceleration** (2 values), ANG_FACTOR-scaled, clipped.
- Both carry the same IMU noise as the existing orientation channels. IMU-only,
  so it transfers to the real BiBoard.

**Phase clock** — the wkF phase index normally advances 1/step; while the body
was tilted past `PHASE_SLOW_TILT = 0.6` rad last step it advances at
`PHASE_SLOW_RATE = 0.25`. `time_obs` **and** the imitation reference both read
this counter (`self._phase`), so a stumbling policy isn't forced onto the stride
beat or penalised by imitation for stepping off-phase to catch itself; it
re-syncs once level.

**Target walk speed** (tracking-bonus form, user pick):
- `TARGET_SPEED = 0.11` m/s (wkF open-loop ≈ 0.10; R5 ≈ 0.12 — target ties the
  baseline to the reference walk's own pace).
- `speed_reward = FAC_SPEED · exp(−SPEED_SHARPNESS · ((v − TARGET)/TARGET)²)`,
  `FAC_SPEED = 6` (vs `FAC_IMITATION = 20` — sub-dominant), `SPEED_SHARPNESS = 2.5`.
  `v` = base-x velocity averaged over `SPEED_WINDOW = 12` steps.
- `FAC_MOVEMENT` forward-progress term is now **capped at `TARGET_SPEED`** (reward
  progress up to the set-point, nothing above) so it stops fighting the tracker.
  Backward motion still penalised.
- `CONTROL_HZ = 80` constant added; `evaluate_policy.py` speed fixed from the old
  50 Hz assumption to 80 Hz → **all Run 7 m/s are ×1.6 of pre-Run-7 reported
  numbers** (R5's old "0.076" ≈ 0.12 true).

**Balance-catch shaping** (`FAC_BALANCE` stays 2.0, now three-part):
`FAC_BALANCE · (1.0·max(0, Δtilt↓) + 0.6·max(0, Δtilt_rate↓) + 0.15·feet_down)`
while `0.5 < tilt < 1.3` rad — rewards damping the wobble (tilt *rate*), not just
leaning back, and planting feet.

**Perturbation drills** — `RANDOM_TERRAIN` 0.03 → **0.045** (curriculum ramps to
this by ~25% of a 2M run then holds — converge against the hard distribution).
New `IMPULSE_PUSH = 0.7` m/s kick at `IMPULSE_PUSH_PROB = 0.004` (~once/episode),
random direction and gait phase — concentrated big-wobble practice.

**Eval metrics added** (`evaluate_policy.py`):
- `speed_vs_target_err_mps_mean` — |speed − TARGET_SPEED|, the walk-speed number.
- `big_stumble_episodes` / `big_stumble_recovery_rate` — fraction of episodes with
  a >0.7 rad (~40°) tilt spike that came back under 0.35 rad and finished upright.
  **This is the number Run 7 is trying to move — R5 scores ~0.**

**Servo torque** — `forces=0.2` N·m (~2 kg·cm) left as-is for R1; roughly matches
the Bittle P-series servo class. Flagged to verify against the real spec and
revisit if under-modelled.

## Scenarios (headless eval)

- **flat** `--dr-friction 0` — regression + clean walk-speed check.
- **course** `--dr-terrain 0.045 --dr-push 0.25` — the training distribution.
- **drills** `--dr-terrain 0.045 --dr-push 0.6` — harder, to exercise
  `big_stumble_recovery_rate`.

## Score (Run 7 — walk)

```
score = 100·(1 − fell_fraction_course)
      +  80·big_stumble_recovery_rate            # the headline goal
      +  40·(−diagonal_trot_corr)                # keep the wkF walk
      +  40·(1 − speed_err/TARGET_SPEED)         # hold the target speed (clamped ≥0)
      −  60·flat_fell_fraction
```
Promote if `score > best + 5`. Baseline = R5 re-evaluated in the Run 7 env — but
R5 can't run here (obs mismatch), so R1 itself sets the first baseline and later
rounds compare to the best Run-7 checkpoint.

---

## Round 1 — `walk_r1` — all of the above, fresh 2M

**Hypothesis:** `big_stumble_recovery_rate` climbs off ~0 (target > 0.3),
`speed_err` is small (policy sits near 0.11 m/s), trot stays ≤ −0.45, flat
regression none. Fresh from scratch, DR curriculum, 2M steps.

**Result** (`walk_r1_ppo`, PPO_38, 40 min, clean convergence, approx_kl ~0.003):

| scenario | fell | dist m | speed m/s | speed_err | trot corr | big-stumble | recov_rate | yaw° |
|---|---|---|---|---|---|---|---|---|
| course (0.045 + 0.25) | **0.25** | 0.161 | 0.056 | 0.054 | −0.510 | 6 | **0.00** | 9.4 |
| drills (0.045 + 0.60) | 0.54 | 0.122 | 0.064 | 0.064 | −0.537 | 15 | 0.07 | 16.9 |
| flat | **0.25** | 0.223 | 0.079 | 0.032 | −0.508 | 3 | 0.00 | 9.1 |

**Regressed. The everything-at-once round broke the base gait: 25% of FLAT-ground
episodes fall** (R5: 0%). Speed dropped to ~0.08 m/s (below target 0.11 and below
R5's ~0.12). `big_stumble_recovery_rate` barely moved (0.00–0.07). Trot held
(−0.51).

**Diagnosis — two prime suspects, both reverted for R2:**
1. **Phase-clock pause has a design flaw.** It slows `self._phase` under tilt,
   which also freezes the *imitation reference* — so while wobbling, the policy is
   told "match wkF frame N" for many steps, and if frame N isn't a recovery pose
   the imitation reward actively fights the catch. It also seems to let the
   nominal gait lose cadence and not re-sync.
2. **`FAC_MOVEMENT` cap removed the main "walk briskly" gradient.** Capped at the
   target with a speed bonus the policy can't yet reach (~0.08 vs 0.11), there's
   little pull to move forward at all → slower, mushier, less stable gait.

**Decision:** R1 not carried forward. Revert target = R5's stability. Decompose:
keep the low-risk additions (IMU history obs, balance-rate shaping), back out the
two suspects and the harsh DR, re-introduce one at a time.

---

## Round 2 — `walk_r2` — decompose: keep the safe additions, revert the suspects

**vs R1:**
- **Phase-clock pause OFF** (`PHASE_SLOW_RATE` → 1.0, i.e. phase always advances
  normally). The gentler "reduce imitation weight while wobbling, don't freeze
  its target" idea is deferred to R3 if the gait recovers.
- **`FAC_MOVEMENT` cap removed** — back to uncapped forward-progress reward (R5
  behavior). The speed tracking bonus stays but at `FAC_SPEED` 6 → **4** so it
  nudges rather than fights.
- **DR back toward R5:** `RANDOM_TERRAIN` 0.045 → **0.03**, `IMPULSE_PUSH` 0.7 →
  **0.4** at prob 0.004 → **0.003** — keep *some* big-hit practice, not a brutal
  plateau.
- **Kept:** 273-dim observation (tilt history + ang accel), 3-part balance
  shaping (angle + rate + feet), `TARGET_SPEED` 0.11.

**Hypothesis:** flat `fell_fraction` back to ~0, trot ≤ −0.52, speed near 0.11,
and with the IMU history + balance shaping + mild impulses the
`big_stumble_recovery_rate` shows *some* lift over R5's ~0. If recovery is still
flat, R3 re-introduces a *fixed* phase clock (no pause) but drops imitation weight
during a wobble, and bumps impulse practice.

**Result:** _pending_
