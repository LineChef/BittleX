# Robustness backlog — pre-hardware walking-policy hardening

Scenarios we want the walking policy to survive on the real robot, with an
env-knob sketch and a keep/revert plan for each. Worked while the frame ships
(2026-09-03 onward). Companion to [`behavior-ideas.md`](../behavior-ideas.md)
(new *behaviours*) and
[`hardware-gated-training-backlog.md`](hardware-gated-training-backlog.md)
(trainings that need a real measurement first).

Base gait `run20m_ppo` is frozen. Everything here is a **reversible continuation**
(`train.py --from trained/run20m_ppo --finetune-lr 1e-4 --finetune-target-kl
0.05`), kept only if it nets capability per the
[capability bar](refinement-regimen.md): beat the frozen base on the target
scenario **without** losing meaningful flat-ground cruise speed or destabilising
the gait.

## Method — the ablation ladder

More domain randomisation is **not** monotonically better. Every knob competes
for policy capacity; past a point you get a gait that hedges everything and walks
like it's permanently on ice. So:

1. Add **one** knob (or one tight cluster).
2. Train a continuation, 3–4 M steps.
3. Eval against the full decathlon (`benchmark_decathlon.py --extra-dr payload`)
   **plus** a held-out cell with that knob forced on.
4. **Keep** if the target cell improves and no decathlon cell regresses past
   noise. **Revert** otherwise. Log the verdict here.
5. If several knobs prove out, fold them into the base recipe so the next planned
   20 M from-scratch run trains with them from step 0 — don't ship a stack of
   one-at-a-time fine-tunes.

The highest-value knobs are the ones that hedge the **sim-to-real gap** (IMU,
servos, latency), because no amount of exotic sim terrain substitutes for the
first hardware run. Do those first.

## Status legend

`TODO` · `RUNNING` · `KEPT` · `REVERTED` · `DEFERRED` · `LATER` · `DROPPED`

## Triage — 2026-09-03 (user)

| Item | Call |
|---|---|
| R1 single weak/dead servo | **DROPPED** |
| R2 IMU bias & mount tilt | **DEFERRED** — decide after seeing how sturdy the real Pi↔PiSugar connector is on hardware (a flaky power/data seat changes whether IMU-bias hardening is the right lever) |
| R3 pick-up & set-down | **EXPLORE** (user 2026-09-03) — but test the frozen base first, may be a no-train win |
| R4 directional terrain catches | **TEST FIRST** — run the `run20m_carpet` checkpoint against a 12–15 mm threshold strip (head-on + angled) before deciding; overlaps carpet + `FAC_BALANCE` |
| R5 slope transitions | **LATER** |
| R6 left/right friction asymmetry | **LATER** |
| R7 servo backlash / deadband | **DROPPED** |
| R8 aggressive command dynamics | **DROPPED** |
| R9 within-episode degradation (battery sag / latency ramp) | **DROPPED** |
| R10 long-duration drift | **YES — priority** (it's an eval, not training; cheap) |
| R11 lateral link collision | **DROPPED** |
| R12 uneven left/right surface (side-hill + stepped split) | **EXPLORE** (user 2026-09-03) |

Next after `run20m_carpet` evals: **R10**, the R3 base test, then the R4 threshold test.

---

## Tier 1 — high real-world payoff, cheap, de-risks bring-up

### R1 · Single weak / dead servo — `DROPPED` (2026-09-03)
One joint (not global `TORQUE_CUTBACK`) at 40–60 % force, or frozen at its last
command, for a whole episode. Servos fail one at a time — wear, a loose cable, a
stripped gear. Tests whether G2 can *limp* instead of faceplant.
- **Knob sketch:** per-reset pick `j ∈ WALKING_DOF` with prob ~0.15; scale that
  joint's `maxForce` by `uniform(0.0, 0.6)` for the episode. New
  `WEAK_JOINT_PROB` / `WEAK_JOINT_SCALE`.
- **Held-out eval:** force each of the 8 joints weak in turn, report distance +
  fall%.
- **Risk:** policy learns a permanently asymmetric gait. Keep prob low.

### R2 · IMU bias & mount tilt — `DEFERRED` (2026-09-03)
Gated on a hardware observation: how solid is the real Pi↔PiSugar S connection?
If the seat is flaky, that's a mechanical fix, not an IMU-bias training target;
if it's solid, revisit this as a sim-to-real hedge.

Not white noise (`RANDOM_GYRO` already covers that) — a *constant* offset:
slow-varying gyro bias + a fixed few-degrees error in how the IMU sits in the
body. Real IMUs have bias and no mount is perfect. This is the single most likely
reason a sim policy wobbles on real hardware.
- **Knob sketch:** per-reset draw `gyro_bias ~ N(0, 0.02 rad/s)` per axis (held
  for the episode) and `mount_rp ~ uniform(±2°)` applied to the quaternion before
  it enters the obs. New `IMU_BIAS_STD` / `IMU_MOUNT_TILT_DEG`.
- **Held-out eval:** sweep bias magnitude; where does heading drift / fall% break?
- **Pairs with:** `sysid_replay.py` — once we have a real log, fit the actual
  bias and set these to match.

### R3 · Pick-up & set-down — `TODO` (not yet triaged)
Zero all foot contacts for N ticks (robot "held"), optionally reorient, then drop
from a small height and require the gait to re-acquire. Owners and kids do this
constantly.
- **Knob sketch:** with prob ~0.05, at a random step: disable ground contact +
  apply gentle centring force for `uniform(20, 60)` ticks, then restore with a
  `uniform(0, 40) mm` drop and `±15°` orientation jitter. New `PICKUP_PROB`.
- **Held-out eval:** count re-acquisitions vs. tumbles over 32 pick-ups.
- **Note:** the obs `tilt_history` may already carry enough to cope — worth
  stress-testing the frozen base first; might be a no-train win.

### R4 · Directional terrain catches — `TODO`
The `CARPET` heightfield is isotropic. Real floors have *lines*: grout, floorboard
gaps, the lip of a rug or floor mat, a doorway threshold strip. A single toe
catching a linear edge is a different failure mode than rolling over bumps.
- **Knob sketch:** overlay 1–3 straight grooves/ridges on the carpet at random
  yaw — narrow (`~8–15 mm`) slots a foot can drop into, or a `~6–12 mm` step up
  onto a "rug". Reuse the retired `LEDGE_*` primitive (currently inert) at low
  height + random heading.
- **Held-out eval:** approach a threshold strip head-on and at 30° / 60° yaw.
- **2026-09-03:** `TEST FIRST` — before building this, run the `run20m_carpet`
  checkpoint against a 12–15 mm threshold strip (`watch.py --challenge step-up` /
  `threshold-up`, plus angled approaches). If it steps over cleanly the scenario
  is already covered by carpet + `FAC_BALANCE` and R4 is dropped; if it
  face-plants, build it. What it teaches: retry a caught swing foot (add
  clearance), absorb a dropped stance foot with the other three legs, reject the
  one-sided yaw kick — without becoming permanently high-stepping.

- **The timidity risk (user, 2026-09-03):** real concern — same ceiling as Phase 4
  stance-recovery. Design so it stays *reactive*, not prophylactic:
  - catches in **only ~15–20 %** of episodes, interleaved with clean flat +
    carpet so flat efficiency stays in every rollout's gradient;
  - **no clearance bonus** — reward the outcome (no fall, heading held), so
    high-stepping only survives if it nets fewer falls after the power penalty;
  - **unanticipatable** — random lip/groove position + heading, catch enabled
    only after the gait is established, so any high-stepping the policy learns is
    forced to be permanent-everywhere and the flat eval catches it at once;
  - the trigger is already in the obs (`tilt_history` / angvel spike on a catch),
    so a conditioned "lift + shift" response is at least representable.
  - **Keep/revert gate:** R4 is a keeper only if threshold traversal improves
    **and** all of these stay within noise of `run20m_ppo` — flat cruise speed,
    mean swing peak paw-Z, power / cost-of-transport, step cadence, decathlon
    flat + slope cells. Else: document as a control-setup ceiling, revert.

---

## Tier 2 — worth it, a bit more env work

### R5 · Slope transitions — `LATER` (2026-09-03)
Flat → ramp → flat. The *transition* (breaking over the top of a rise, or the
ramp meeting the floor at the bottom) is harder than a steady grade. The carpet
swell is a mild version; make some episodes a real ramp with a defined lip.
- **Knob sketch:** a `~15–25°` ramp segment starting `x ∈ [0.4, 1.0]` m ahead,
  `~0.5 m` long, then flat again.

### R6 · Left/right friction asymmetry — `LATER` (2026-09-03)
One body side on tile, the other on carpet → an induced yaw the policy must
cancel continuously. Different from a uniform low-friction patch.
- **Knob sketch:** split the ground at `y = uniform(±0.05)`; friction
  `1.0` one side, `uniform(0.3, 0.7)` the other.

### R7 · Servo backlash / deadband — `DROPPED` (2026-09-03)
Cheap servos have slop: a `~1–3°` deadzone around the commanded angle where the
horn doesn't move, plus hysteresis on direction reversal.
- **Knob sketch:** before applying the motor command, snap it to the previous
  position if `|Δ| < deadband`; `deadband ~ uniform(0.5°, 3°)` per joint per
  episode. New `SERVO_DEADBAND_DEG`.

### R8 · Aggressive command dynamics — `DROPPED` (2026-09-03)
We train speed *tracking* but not fast *transitions*: full-speed → hard reverse,
sharp yaw while cruising, repeated stop/start. Also: a long sustained arc
(`fwd + yaw` held for the whole episode) — does heading spiral or drift?
- **Knob sketch:** a command-schedule mode that steps `cmd_fwd` / `cmd_yaw`
  between extremes every `uniform(30, 80)` ticks; plus an "arc" mode holding a
  fixed nonzero yaw.

---

## Tier 3

### R9 · Within-episode degradation — `DROPPED` (2026-09-03)
Battery sag / thermal cutback / latency that *ramps during* the episode, not a
fixed per-episode value. `CMD_LATENCY_STEPS` 0→2 over 60 s; `maxForce` decaying
10–15 %.

### R10 · Long-duration drift — `TODO — PRIORITY` (eval, not train) (2026-09-03)
Episodes are 251 steps (~3 s). Run the frozen base **and** `run20m_carpet` for
60 s+ on flat + carpet and check for an accumulating limp, heading creep, or a
slow oscillation that a short episode never reveals. If it drifts, *then* consider
a training fix (longer `EPISODE_LENGTH`, a drift penalty). First real task after
the `run20m_carpet` evals.

### R11 · Lateral link collision — `DROPPED` (2026-09-03)
Bumping a chair leg / wall with a shin mid-swing: a short lateral impulse on a
random lower-leg link (not the base). Distinct from `IMPULSE_PUSH` on the torso.

### R12 · Uneven left/right surface — `EXPLORE` (user 2026-09-03)
One body side persistently lower/higher than the other. Two sub-cases:
- **R12a · side-hill / traverse a contour.** A sustained roll tilt (`~8–15°`)
  held for the whole episode with `cmd_fwd` along the contour, so gravity pulls
  G2 downhill continuously and it must hold heading. `SLOPE_MAX_DEG` already draws
  a random per-episode roll, but independently of pitch, so a *pure* sustained
  side-hill is diluted. Add a mode that forces roll-dominant tilt + a longer
  episode. **Held-out eval:** downhill drift (m) and heading error over a 60 s
  contour walk at `±10°` / `±15°`.
- **R12b · stepped split.** Left legs `~15–25 mm` higher than right — walking with
  one side up on a rug edge / a low curb / a floor-vent lip. A height
  discontinuity down the centerline, not a tilt. The height-twin of R6. Reuse a
  half-width raised slab at `y = uniform(±0.03)`.
  **Held-out eval:** traverse with the split under the left, then the right.
- **Timidity check:** same gate as R4 — flat cruise speed / swing height / power
  must hold within noise of the base.

---

## Log

| Date | Item | Run | Verdict | Notes |
|---|---|---|---|---|
| 2026-09-03 | R0 (baseline: continuous rough terrain) | `run20m_carpet` | RUNNING | `CARPET` 13 mm bumps + 22 mm swell, 50 % of DR episodes; from `run20m_ppo`, 4 M steps, `--finetune-lr 1e-4`. Eval pending. |
