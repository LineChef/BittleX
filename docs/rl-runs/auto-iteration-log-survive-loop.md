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

**Result:** _pending_
