# survive-loop — "do something the scripted gait structurally can't"

Branch `survive-loop` (off `development`). The resid-tuning loop got the learned
residual gait to near-parity with scripted `wkF` on heading/roll, but on the axis
that would make it *better* — staying upright when `wkF` falls — it was at dead
parity after 4 rounds. This loop optimises for that gap directly.

## Objective

The learned residual policy should **survive disturbances / terrain that make the
open-loop scripted gait fall**, while holding a commanded speed (~0.10 m/s),
keeping a reasonable heading, and not dissolving the trot. The residual's real
edge is the IMU feedback the scripted gait can't use; this loop rewards using it.

## Primary metric — conditional survival

`benchmark_gaits.py` runs learned + scripted on matched per-episode seeds
(identical courses *and* identical pushes). New headline:

```
conditional_survival = (episodes where scripted fell AND learned survived) / (episodes where scripted fell)
```

Reported per cell and pooled. Also watch `big_stumble_recovery_rate` from
`evaluate_policy.py` (has been stuck at 0 every prior run).

## Benchmark changes (this loop)

- 28 episodes/cell (bigger denominator of scripted falls).
- Per-episode `fell` arrays in the JSON; pooled + per-cell conditional survival.
- New column: **yaw-*rate* rms** (deg/s). The real BiBoard IMU has no
  magnetometer, so absolute heading isn't a signal the robot will have cleanly —
  score heading by yaw rate from here on
  ([`docs/research/hardware-specs.md`](../research/hardware-specs.md)).
- Two new hard cells so scripted actually falls enough to measure:
  `push-hard` (flat + strong impulses, isolates shove-recovery) and
  `obst-50+push`. First four cells unchanged (regression watch).

## Promote / reject rule

```
PROMOTE if:  conditional_survival (pooled) >= 0.30
        AND  learned fall rate <= scripted's at EVERY cell (never worse anywhere)
        AND  flat speed in [0.085, 0.125] m/s          (speed is a band now, not a floor)
        AND  diagonal_trot_corr <= -0.45               (gait not dissolved)
        AND  yaw_rate_rms not >20% worse than the rtune_r4 baseline
REJECT otherwise. Revert to last-good after 2 non-improving rounds.
```

## Baseline — `rtune_r4` (carried from the resid-tuning loop)

Re-benchmarked under the *new* harder cells at the start of S1 for a fair
reference (the old numbers were on easier cells). See the S1 entry.

## Lever bank

| # | type | change |
|---|---|---|
| S1 | baseline reset | harder disturbances + inertia DR + reward the save + speed set-point (below) |
| S2 | reward | `FAC_SURVIVE_BONUS` strength / tilt-scaling shape |
| S3 | DR | `RANDOM_MASS` wider / front-back asymmetric (Pi payload) |
| S4 | DR | push profile — sustained lateral shoves, or `IMPULSE_PUSH` 0.55 → 0.65 |
| S5 | reward | heading → yaw-rate: `FAC_HEADING` 5 → 2, gentle `FAC_YAW` 0.1 → 0.15 |
| S6 | policy | cadence `_phase += 1.05` to recover any speed lost to the harder training |
| S7 | — | consolidation: best reward + best DR + best policy config, longer eval |

---

## S1 — `surv_r1` — survival-oriented baseline

Coordinated reset (like `resid_r2` was). Changes vs `rtune_r4`:

- **Disturbance up:** `IMPULSE_PUSH` 0.4 → **0.55**, `IMPULSE_PUSH_PROB` 0.003 →
  **0.006** — so the policy actually practises big saves.
- **Inertia DR up:** `RANDOM_MASS` 0.10 → **0.18**, `RANDOM_FRICTION` 0.22 →
  **0.30** — the policy must see real mass variation to learn to compensate.
- **Reward the save:** `FAC_BALANCE` 2.0 → **4.0**; new **`FAC_SURVIVE_BONUS =
  40`** — one-shot at episode end if not fallen, scaled
  `clip((peak_tilt − 0.5) / 0.8, 0, 1)` so a calm episode gets ~0 and a held
  near-tip gets the full bonus. Asymmetric — rewards the save, not just walking.
- **Speed set-point:** `MOVEMENT_CAP_AT_TARGET` → **True**, `FAC_MOVEMENT` 1000 →
  **300**, new **`FAC_OVERSPEED = 60`** (`−FAC_OVERSPEED·max(0, v − 0.10)`, mirror
  of the `MIN_SPEED` floor). "Walk at 0.10" becomes a band.
- **Kept:** `RESIDUAL_SCALE_DEG = 11` (authority NOT shrunk), `FAC_RESID_SMOOTH =
  6` (rtune_r4's win), 273-dim obs, `is_fallen()` instant-terminate.
- **Not touched:** heading reward terms — that's S5.

**Hypothesis:** pooled `conditional_survival` ≥ 0.30, learned fall rate ≤ scripted
at every cell, flat speed 0.09–0.10, trot ≤ −0.45. Risk: harder disturbances lift
*both* gaits' fall rates and the gap stays ~parity → the save-reward is too weak
(S2).

**Result** (`surv_r1_ppo`, ~40 min, `ep_len_mean` 251 in training). Benchmark
28 ep/cell vs scripted `wkF`:

| cell | cond. surv. | L falls | S falls | L speed | L trot | L yaw-rate | L roll |
|---|---|---|---|---|---|---|---|
| flat | – | 0% | 0% | 0.081 | −0.51 | 7.4 | .009 |
| obst-20 | – | 0% | 0% | 0.062 | −0.50 | 7.8 | .008 |
| obst-35 | 0% (1) | 4% | 4% | 0.052 | −0.47 | 8.9 | .011 |
| obst-50 | 0% (1) | **11%** | 4% | 0.049 | −0.47 | 12.7 | .024 |
| push-hard | **25% (16)** | 57% | 57% | 0.063 | −0.54 | 28.1 | .071 |
| obst-50+push | 10% (10) | **54%** | 36% | 0.047 | −0.49 | 22.5 | .069 |

**Pooled conditional survival: 18% (5/28).**

| gate | threshold | result | verdict |
|---|---|---|---|
| pooled cond. survival | ≥ 0.30 | 0.18 | ❌ FAIL |
| fall ≤ scripted everywhere | no cell worse | worse at obst-50, obst-50+push | ❌ FAIL |
| flat speed | 0.085–0.125 | 0.081 | ❌ FAIL (marginal) |
| trot corr | ≤ −0.45 | −0.47…−0.54 | ✅ PASS |
| yaw-rate rms | ≤ 1.2× rtune_r4 | no baseline — sets it | ⚪ n/a |

**REJECT — worse-or-tied vs scripted on every axis.** A GUI replay (flat +
frequent 0.75 m/s shoves) confirmed it: 5 of 7 episodes got a real hit, all 5
fell (peak tilt 75–81°); the 2 "survivals" were episodes with no big hit.

**Learnings → S2:**
1. **`FAC_SURVIVE_BONUS` is the wrong shape** — one-shot at episode end, pays 0 if
   the episode ended in a fall, so a mid-episode recovery earns nothing. No
   gradient toward the save. → replace with a **dense per-step danger-band
   reward**.
2. `obst-50+push` regressed — terrain + shove makes the policy thrash (roll .069,
   yaw-rate 22) instead of catching. Dense "don't fall" credit should also damp
   this.
3. Flat speed 0.081 < 0.085 → `FAC_OVERSPEED` 60 → 35.
4. The faint positive: `push-hard` cond. survival 25%, `big_stumble_recovery`
   0.06 vs scripted 0.00 — mechanism exists, far too weak.

---

## S2 — `surv_r2` — dense danger-band survival reward

Changes vs `surv_r1`:
- **New `FAC_SURVIVE_STEP = 6`** — per step, unramped, while `0.8 < tilt < 1.3`
  and not fallen. Continuous "stay up one more step" gradient. Below 0.8 rad =
  normal wobble, no credit → no farming incentive (and the ramped `FAC_UPRIGHT`
  tilt² penalty still pushes it to leave the band).
- **`FAC_SURVIVE_BONUS` 40 → 12** — demoted to a small finishing cherry; the
  dense term is the driver now.
- **`FAC_OVERSPEED` 60 → 35** — recover the flat-speed gate.
- Kept: harder DR (`IMPULSE_PUSH` 0.55, `RANDOM_MASS` 0.18), `FAC_BALANCE` 4,
  `RESIDUAL_SCALE_DEG` 11, speed set-point.

**Hypothesis:** pooled cond. survival clears 0.30, driven by `push-hard` and
`obst-50+push`; flat speed back ≥ 0.085; no new fall regressions.

**Result** (`surv_r2_ppo`, ~40 min, clean). Benchmark 28 ep/cell:

| cell | cond. surv. (r2 / r1) | L falls (r2 / r1) | S falls | L speed | L trot | L yaw-rate | L roll |
|---|---|---|---|---|---|---|---|
| flat | – | 0% / 0% | 0% | 0.076 | −0.49 | 4.9 | .003 |
| obst-20 | – | 0% / 0% | 0% | 0.060 | −0.50 | 6.1 | .004 |
| obst-35 | 0% / 0% | 4% / 4% | 4% | 0.050 | −0.47 | 7.9 | .008 |
| obst-50 | 0% / 0% | 7% / 11% | 4% | 0.049 | −0.48 | 8.2 | .012 |
| push-hard | **12% / 25%** | 61% / 57% | 57% | 0.053 | −0.50 | 27.7 | .073 |
| obst-50+push | **50% / 10%** | **32% / 54%** | 36% | 0.038 | −0.50 | 17.2 | .042 |

**Pooled conditional survival: 25% (7/28)** — up from surv_r1's 18%.

| gate | threshold | result | verdict |
|---|---|---|---|
| pooled cond. survival | ≥ 0.30 | 0.25 | ❌ FAIL (18 → 25, improving) |
| fall ≤ scripted everywhere | no cell worse | worse at obst-50, push-hard | ❌ FAIL |
| flat speed | 0.085–0.125 | **0.076** | ❌ FAIL (worse than r1) |
| trot corr | ≤ −0.45 | −0.47…−0.50 | ✅ PASS |
| yaw-rate rms | ≤ 1.2× surv_r1 | flat 4.9 vs 7.4, push similar | ✅ PASS |

**REJECT — but real directional signal, so carry forward (not revert).**
- **The dense reward works where terrain is involved:** `obst-50+push` cond.
  survival 10% → **50%**, and learned fall rate there **32% vs scripted 36%** —
  the first cell where learned beats scripted at staying up.
- **`push-hard` (pure flat shove) regressed** (25% → 12%). A fast flat shove
  blows past the 0.8 rad hard cutoff before the credit engages → the policy never
  earned the save there.
- **Flat speed dropped again (0.081 → 0.076)** despite softening `FAC_OVERSPEED`.
  `FAC_MOVEMENT = 300` + cap is too weak a forward pull. This is a hard blocker —
  no round can promote below the 0.085 gate.

**Learnings → S3:**
1. Flat-speed gate: `FAC_MOVEMENT` 300 → 550, `MIN_SPEED` floor 0.07 → 0.085.
2. `push-hard`: make the survive credit **ramp** from 0.6 rad instead of a hard
   0.8 on/off — engages while the policy can still act, near-zero for routine
   wobble (no farming a mild tilt).

---

## S3 — `surv_r3` — earlier-engaging survival credit + fix the flat-speed gate

Changes vs `surv_r2`:
- **`FAC_SURVIVE_STEP` now ramped:** `6 · clip((tilt − 0.6) / 0.7, 0, 1)` — ~0 at
  routine wobble, full near the 1.3 rad fall line. Was a hard on/off at 0.8.
- **`FAC_MOVEMENT` 300 → 550**, **`MIN_SPEED` 0.07 → 0.085** — get flat speed into
  the gate band; still capped at `TARGET_SPEED` so no over-speed swerve.
- Kept: `FAC_BALANCE` 4, `FAC_SURVIVE_BONUS` 12, `FAC_OVERSPEED` 35, harder DR,
  `RESIDUAL_SCALE_DEG` 11.

**Hypothesis:** flat speed 0.09–0.10 (gate ✅); pooled cond. survival ≥ 0.30 with
`push-hard` recovering toward `obst-50+push`'s level; no fall regression vs
scripted.

**Result** (`surv_r3_ppo`, ~40 min, clean). Benchmark 28 ep/cell:

| cell | cond. surv. (r3 / r2) | L falls (r3 / r2) | S falls | L speed | L trot | L yaw-rate | L roll |
|---|---|---|---|---|---|---|---|
| flat | – | 0% / 0% | 0% | 0.085 | **−0.45** | 5.7 | .003 |
| obst-20 | – | 0% / 0% | 0% | 0.067 | **−0.44** | 6.2 | .003 |
| obst-35 | 0% / 0% | 4% / 4% | 4% | 0.057 | **−0.44** | 9.0 | .009 |
| obst-50 | 0% / 0% | 7% / 7% | 4% | 0.051 | **−0.44** | 11.1 | .014 |
| push-hard | **6% / 12%** | 61% / 61% | 57% | 0.066 | −0.49 | 26.8 | .072 |
| obst-50+push | **20% / 50%** | 36% / 32% | 36% | 0.043 | −0.45 | 20.2 | .050 |

**Pooled conditional survival: 11% (3/28)** — DOWN from surv_r2's 25%, below even
surv_r1.

| gate | threshold | result | verdict |
|---|---|---|---|
| pooled cond. survival | ≥ 0.30 | **0.11** | ❌ FAIL (regressed 25 → 11) |
| fall ≤ scripted everywhere | no cell worse | obst-50, push-hard worse | ❌ FAIL |
| flat speed | 0.085–0.125 | 0.085 | ✅ PASS (fix worked) |
| trot corr | ≤ −0.45 | **−0.44** at 4 cells | ❌ FAIL (new regression) |
| yaw-rate rms | ≤ 1.2× surv_r1 | ok | ✅ PASS |

**REJECT — regression. Revert to `surv_r2` as the base.** Both bundled changes
backfired:
1. **Ramping the survive credit from 0.6 rad gutted its magnitude in the zone
   that matters.** At 0.9 rad it paid 6·(0.9−0.6)/0.7 ≈ 2.6, vs surv_r2's flat
   6.0. So the save incentive got *weaker* right where the save happens →
   `obst-50+push` cond. survival 50% → 20%, the one real win lost.
2. **`FAC_MOVEMENT` 300 → 550 flattened the trot** to −0.44 (below gate). The
   `MIN_SPEED` floor at 0.085 is what actually fixed the speed gate (speed landed
   exactly 0.085), so `FAC_MOVEMENT` doesn't need to be that high.

**Learnings → S4:** keep `MIN_SPEED` 0.085 (that fixed speed), drop `FAC_MOVEMENT`
back to 350 (restore trot), and un-ramp the survive credit — flat 6.0 with the
cutoff at **0.7** (between r2's 0.8 and r3's 0.6, without the magnitude loss).

---

## S4 — `surv_r4` — surv_r2 base + un-ramped earlier survive credit + speed-gate fix that keeps the trot

Effectively `surv_r2` with three corrections:
- **`FAC_SURVIVE_STEP`** back to flat 6.0; **`SURVIVE_BAND_LO` 0.8 → 0.7** (reach
  fast flat shoves without r3's magnitude loss).
- **`MIN_SPEED` 0.07 → 0.085** (kept from r3 — this fixed the speed gate).
- **`FAC_MOVEMENT` 300 → 350** (not r3's 550 — the floor holds the gate; 550
  killed the trot).
- Kept: `FAC_BALANCE` 4, `FAC_SURVIVE_BONUS` 12, `FAC_OVERSPEED` 35, harder DR,
  `RESIDUAL_SCALE_DEG` 11.

**Hypothesis:** restores surv_r2's `obst-50+push` win (≥ 40% cond. survival),
lifts `push-hard` past 12%, pooled ≥ 0.30; flat speed ≥ 0.085 with trot ≤ −0.47.

**Result** (`surv_r4_ppo`, ~40 min, clean). Benchmark 28 ep/cell:

| cell | cond. surv. (r4 / r2) | L falls (r4 / r2) | S falls | L speed | L trot | L yaw-rate | L roll |
|---|---|---|---|---|---|---|---|
| flat | – | 0% / 0% | 0% | **0.088** | −0.49 | 8.3 | .009 |
| obst-20 | – | 0% / 0% | 0% | 0.074 | −0.49 | 8.7 | .008 |
| obst-35 | 0% / 0% | 7% / 4% | 4% | 0.057 | −0.48 | 9.8 | .013 |
| obst-50 | 0% / 0% | 7% / 7% | 4% | 0.052 | −0.49 | 11.6 | .016 |
| push-hard | 6% / 12% | 64% / 61% | 57% | 0.060 | −0.53 | 29.7 | .073 |
| obst-50+push | **20% / 50%** | **46% / 32%** | 36% | 0.041 | −0.51 | 23.3 | .062 |

**Pooled conditional survival: 11% (3/28)** — no better than surv_r3, well below
surv_r2's 25%.

| gate | threshold | result | verdict |
|---|---|---|---|
| pooled cond. survival | ≥ 0.30 | 0.11 | ❌ FAIL |
| fall ≤ scripted everywhere | no cell worse | obst-35, obst-50, push-hard, obst-50+push worse | ❌ FAIL |
| flat speed | 0.085–0.125 | 0.088 | ✅ PASS |
| trot corr | ≤ −0.45 | −0.48…−0.53 | ✅ PASS |
| yaw-rate rms | ≤ 1.2× surv_r1 | ok flat/obst, high push cells | ➖ |

**REJECT — 2nd non-improving round; revert to `surv_r2`.** The speed gate is
fixed (`MIN_SPEED` 0.085 works) but survival collapsed to r3 levels.
**Root cause identified: the steep `MIN_SPEED` floor (weight 120) and the
survival objective are in direct conflict.** When shoved, the right move is to
slow down / widen stance — but the 0.085 floor punishes that ~4/step, so the
policy keeps driving forward into instability. surv_r2 (`MIN_SPEED` 0.07, lower
floor) had the room to slow and got the best survival of the loop.

**Learnings → S5:** revert to surv_r2 exactly, then make **one** change — gate the
`MIN_SPEED` penalty on `tilt < BALANCE_TILT_ON`. Floor active only while upright
(holds the flat-speed gate); suspended while wobbling (survival can slow the
walk).

---

## S5 — `surv_r5` — surv_r2 base + tilt-gated speed floor

`surv_r2` config restored (`FAC_MOVEMENT` 300, `SURVIVE_BAND_LO` 0.8, flat
`FAC_SURVIVE_STEP` 6.0, `FAC_OVERSPEED` 35, `FAC_BALANCE` 4), plus:
- **`MIN_SPEED` = 0.085, but the penalty applies only when `tilt < 0.5 rad`.**
  Upright → floor holds flat pace to the gate. Wobbling → no speed-floor
  pressure, so catching the stumble can cost forward speed for free.

**Hypothesis:** flat speed ≥ 0.085 (floor active on level ground) **and** pooled
cond. survival back to ≥ 25% and ideally past 0.30 (floor off during the save);
`obst-50+push` win restored.

**Result** (`surv_r5_ppo`, ~40 min, clean). Benchmark 28 ep/cell:

| cell | cond. surv. (r5 / r2) | L falls (r5 / r2) | S falls | L speed | L trot | L yaw-rate | L roll |
|---|---|---|---|---|---|---|---|
| flat | – | 0% / 0% | 0% | **0.094** | **−0.55** | 7.6 | .006 |
| obst-20 | – | 0% / 0% | 0% | 0.073 | −0.55 | 8.2 | .007 |
| obst-35 | 0% / 0% | 4% / 4% | 4% | 0.056 | −0.54 | 8.7 | .010 |
| obst-50 | 0% / 0% | 7% / 7% | 4% | 0.053 | −0.54 | 13.8 | .018 |
| push-hard | **19% / 12%** | **57% / 61%** | 57% | 0.073 | −0.59 | 31.2 | .075 |
| obst-50+push | **20% / 50%** | 36% / 32% | 36% | 0.050 | −0.56 | 24.2 | .051 |

**Pooled conditional survival: 18% (5/28)** — up from S3/S4's 11%, still under S2's 25%.

| gate | threshold | result | verdict |
|---|---|---|---|
| pooled cond. survival | ≥ 0.30 | 0.18 | ❌ FAIL (< S2) |
| fall ≤ scripted everywhere | no cell worse | obst-50 7% vs 4% (~1 ep) | ❌ FAIL (marginal) |
| **flat speed** | 0.085–0.125 | **0.094** | ✅ PASS — fixed |
| trot corr | ≤ −0.45 | −0.54…−0.59 | ✅ PASS — crispest of the loop |
| yaw-rate rms | ≤ 1.2× surv_r1 | ok | ✅ |

**Mixed — keep the S5 base, target the one regression.** The tilt-gated floor
**worked for what it was for**: flat speed 0.076 → **0.094** (gate cleared for the
first time in the loop), trot the crispest yet, and **`push-hard` survival
improved 12% → 19%** (the policy can now slow to catch a flat shove). But
**`obst-50+push` regressed 50% → 20%.**

**Diagnosis:** on rough terrain the policy sits at moderate tilt (~0.3–0.45 rad)
fighting the obstacles — *below* the hard 0.5 rad cutoff, so the 0.085 floor is
still fully active and still pushing it forward into the terrain. S2's blanket
0.07 floor gave rough ground more room.

**Learnings → S6:** keep S5 (its speed/trot/`push-hard` gains are real) but
**ramp** the floor down with tilt instead of a hard cutoff — full at tilt 0,
zero at ≥ 0.5, so moderately-rough terrain gets partial relief too.

---

## S6 — `surv_r6` — ramp the speed floor out with tilt

`surv_r5` base, one change:
- `min_speed_penalty *= clip((0.5 − tilt) / 0.5, 0, 1)` — was a hard on/off at
  tilt 0.5. Now: full floor when upright, ~half at tilt 0.25, off at ≥ 0.5.
  Rough terrain (tilt 0.3–0.45) gets meaningful relief without letting
  flat-ground pace sag (flat tilt ≈ 0.1 → ~80% floor).

**Hypothesis:** flat speed stays ≥ 0.09, `push-hard` holds ~19%, `obst-50+push`
recovers toward 40–50%, pooled clears 25% and ideally 0.30.

**Result:** _pending_
