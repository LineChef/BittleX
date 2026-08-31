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

**Result:** _pending_
