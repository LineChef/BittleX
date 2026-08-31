# Residual-on-wkF line ("resid")

Motivation: the learned-vs-scripted benchmark
([`docs/gait-benchmark.md`](gait-benchmark.md)) showed Bittle's open-loop `wkF`
keyframes are hard to beat on obstacle courses — the fast learned gaits are
brittle. This line starts *from* the scripted gait and learns a correction on
top, borrowing what makes the scripted gait robust.

**Primary goal:** a gait that doesn't fall (or does everything it can to avoid
it). Speed and capability come later, with the vision module.

## R1 — `resid_r1`

### Changes vs the `development` env

- **Residual action space** (`RESIDUAL_MODE=True`): the policy output modulates
  the scripted `wkF` pose instead of accumulating per-step deltas —
  `joint_target = wkF(phase) + action · deg2rad(18)`. `action = 0` reproduces the
  open-loop scripted walk exactly (verified: +0.30 m / 250 steps, upright). So
  the policy can only *add* a learned correction to a gait that already walks and
  doesn't fall — a learned version of the firmware's gyro-balance layer.
- **`FAC_RESIDUAL_COST = 1.5`** — `−mean(action²)`: deviate from the scripted pose
  only when it helps.
- **`FAC_DUTY = 4.0`** — reward `paws-in-contact / 4`. The scripted walk's
  stability comes from keeping 2–3 feet down; this pushes a trot toward a walk.
- **`FAC_UPRIGHT = 8.0`** — ramped `−tilt²` penalty, always on. Not-falling is the
  objective.
- **`FAC_IMITATION` 20 → 10** — with residual mode the baseline already matches
  `wkF`; a lighter pull just discourages large residuals.
- **Speed de-emphasised:** `TARGET_SPEED` 0.11 → **0.10** (the scripted pace),
  `FAC_SPEED` 4 → **2**, `MOVEMENT_CAP_AT_TARGET` → **True** (no incentive to
  speed up — fast gaits are the brittle ones).
- **`RANDOM_TERRAIN` 0.03 → 0.045** — train against real obstacles; the DR
  curriculum ramps to this and holds.
- Kept: `FAC_BALANCE` (stumble-catch), `FAC_GAIT_SYMMETRY`, `FAC_HEADING`,
  273-dim observation, `IMPULSE_PUSH` drills, `is_fallen()` instant-terminate.

Fresh from scratch, 2M steps.

**Hypothesis:** converges at or below the scripted gait's obstacle fall rate
(open-loop `wkF`: 0% at ≤35 mm, ~8% at 50 mm) while keeping the learned flat-ground
advantage — because the policy starts at the scripted gait and can only improve
on it. Re-run `benchmark_gaits.py` after.

**Result** (`resid_r1_ppo`, PPO_42, ~42 min, `ep_len_mean` 251 throughout —
nothing fell in training):

| benchmark vs scripted `wkF` | flat | 20 mm | 35 mm | 50 mm |
|---|---|---|---|---|
| resid speed (m/s) | 0.031 | 0.034 | 0.025 | 0.018 |
| scripted speed | 0.088 | 0.065 | 0.047 | 0.038 |
| resid falls | 0% | 0% | **7%** | **21%** |
| scripted falls | 0% | 0% | 0% | 14% |

**Regressed — lost to scripted on every axis.** The residual policy used its
±18° budget to **slow `wkF` to ~⅓ speed** and got *less* robust on obstacles
(worse at 35 and 50 mm). The reward pointed the wrong way: `FAC_DUTY=4` (reward
feet-down) + `FAC_UPRIGHT=8` (penalise tilt) + `MOVEMENT_CAP_AT_TARGET` + weak
`FAC_SPEED=2` stacked into a "stand still, feet planted, body level" attractor
with almost no counter-incentive to keep walking. Architecture is sound (`action
= 0` = `wkF`, verified); the shaping smothered the walk.

---

## R2 — `resid_r2` — preserve the walk

- **Restore forward drive:** `MOVEMENT_CAP_AT_TARGET` → **False**, `FAC_SPEED`
  2 → **5**, and a new hard floor: `min_speed_penalty = FAC_MIN_SPEED(120) ·
  max(0, MIN_SPEED(0.07) − v)` — steep, unramped, so the policy can never learn
  to stall.
- **`FAC_DUTY` 4 → 0** — the main freeze attractor; `wkF` already has a good duty
  factor.
- **`FAC_UPRIGHT` 8 → 3** — keep a tilt penalty, don't let it dominate.
- **`RESIDUAL_SCALE_DEG` 18 → 11** — less authority to warp the gait, enough for
  balance corrections.
- Kept: `FAC_RESIDUAL_COST` (deviate only when it helps — worked), residual
  action space, 45 mm terrain, 273-dim obs.

**Hypothesis:** holds ~`wkF` pace (≥ 0.07 m/s) while the learned correction cuts
the obstacle fall rate to at or below scripted's. Re-benchmark.

**Result:** _pending_
