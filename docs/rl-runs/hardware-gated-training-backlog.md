# Hardware-gated training backlog

RL / gait-training work that is **deliberately deferred until the real robot is
available for testing**. Sim iteration on locomotion is otherwise considered done
as of 2026-09-03 (`run20m_ppo` is the frozen base gait — see
[`refinement-regimen.md`](refinement-regimen.md) and
[`phase4-decision-log.md`](phase4-decision-log.md)).

Each entry has a **trigger**: the specific thing hardware testing would have to
show before the run is worth doing. If the trigger never fires, the item stays
closed. Add freely; when one gets picked up, note it in
[`../project-plan.md`](../project-plan.md).

Related: behaviour-level backlog in [`../behavior-ideas.md`](../behavior-ideas.md)
(B1, B2, B13 especially); self-righting in
[`../research/self-righting-research.md`](../research/self-righting-research.md).

Status legend: 🔴 blocked on hardware · 🟡 partial sim work possible now · ⚪ may never be needed

---

## H1 — Learned vs scripted head-to-head on the real robot  🔴

**The question the whole RL locomotion track hinges on.** Is a learned gait
actually better than OpenCat's firmware `wkF` (which has a live gyro-balance
layer the sim baseline doesn't) for plain walking on real ground?

- **Contenders:** firmware `wkF` · `run20m_ppo` (current base) · `gait-v7-stumble-catch` · `walk-v8-r2`
- **Measure:** sim-to-real gap per gait, forward speed, heading drift, fall rate
  on real thresholds/rugs/slopes, power draw, recovery from real shoves.
- **Trigger:** hardware assembled + policy deployed (ONNX on the Pi, or on-MCU).
  This is step one, not a maybe.
- **Outcome decides:** whether to keep building on RL locomotion at all, or fall
  back to firmware gaits + a perception layer.

## H2 — Payload re-tuning  🟡

`run20m_ppo` is **payload-conditioned** — trained with a single 75 g welded rear
payload every episode. The gait's stability leans on that mass.

**Sim payload model updated 2026-09-03** (BOM in `docs/research/hardware-specs.md`
"Mounted payload weight"; user expects the camera on the bot by the time the
frame arrives, so the target is the *fully-loaded* config). Now **two welded
bodies** so the fore/aft CoM split is right:
- `PAYLOAD_MASS_NOM 0.061` ± `0.018` (spine 43–79 g) at `PAYLOAD_POS
  (-0.020, 0, 0.025)` — Pi Zero 2 WH + SD + PiSugar S 1200 mAh + wiring + cover.
- `HEAD_MASS_NOM 0.015` ± `0.005` (head 10–20 g) at `HEAD_MASS_POS
  (0.055, 0, 0.020)` — Grove Vision AI V2 + OV5647 + case, front mast.
- Combined nominal ≈ 76 g, payload CoM ~14 mm forward of the spine-only point.
- `run20m_ppo` does **not** have this (still frozen at the old lumped 75 g rear).
  The next training run picks it up.

- **Trigger:** the real built stack weighs meaningfully off ~76 g combined (weigh
  it), OR the spine/head mass split or positions differ from the estimate above,
  OR something is added/removed later (e.g. camera stays off, bigger battery).
- **Work:** set `PAYLOAD_MASS_*` / `HEAD_MASS_*` / positions to the **measured**
  values (kitchen scale; balance each sub-assembly on an edge for its CoM), then
  a from-scratch 20M run — or a clean `--finetune-lr` continuation from
  `run20m_ppo` if the delta is small. Re-run the decathlon payload-on.
- **Cheap-ish** and high-value — a wrong payload model is a direct sim-to-real error.

## H3 — Clean re-run of the 4a ledge test  🟡  ⚪

Phase 4a (ledge terrain in training DR) regressed the walk, **but that run was on
a diverged policy** (the `--from` LR bug, fixed in commit `bcf20fd`). The verdict
is unreliable.

- **Trigger:** hardware testing shows G2 actually trips on door sills / rug edges
  / cables / low curbs that the current gait + firmware balance don't handle.
- **Work:** one continuation, `--from trained/run20m_ppo --finetune-lr 1e-4`,
  `LEDGE_PROB ≈ 0.12`, height cap ~12–15 mm, `LEDGE_RANDOMIZE` on. ~3.5M steps.
- **Skip permanently if** real thresholds turn out fine — folding curbs into the
  walk policy is B13 tier-2 and low priority.

## H4 — Active stance recovery, from scratch  🔴  ⚪

"Wobble → re-plant → keep walking" beyond what `FAC_BALANCE=4.0` already gives
**cannot be reached by continuation** — Phase 4c confirmed it (walk preserved,
zero recovery gain). Two independent findings say the ceiling is the control
setup, not the reward: this, and the original Run 6/7 conclusion.

- **Trigger:** the H1 head-to-head shows real servo torque supports active
  recovery *better than sim predicted* — i.e. the ceiling was a sim artefact, not
  physics. (If hardware confirms the ceiling is real, this stays closed forever.)
- **Work:** from-scratch 20M-class run with the diagonal-support catch bonus +
  loosened in-recovery residual baked in from step 0, not bolted on. Gated on the
  green-light checklist ([[project_longrun_trigger]]).
- Measure with `benchmark_recovery.py` (payload off — the payload masks recovery
  in eval).

## H5 — Command-conditioned turning (yaw)  🔴

Turning was **dropped in G4** — `cmd_yaw` is always 0, heading-hold only. Firmware
turn gaits (`wkL`/`wkR`) work today.

- **Trigger:** firmware turns oscillate or overshoot during *visual pursuit* on
  hardware, or fail on real terrain. Decision gate is **after** the vision
  pursuit layer is running on the robot — see B2.
- **Work:** add `cmd_yaw` back to the observation + a yaw-rate tracking reward,
  from-scratch (the current policy never learned it). One command-conditioned
  policy, not a separate turn gait.

## H6 — Specialty gaits: sidestep / sneak / backward  🔴  ⚪

B2. Only if autonomy-mode testing surfaces a concrete gap.

- **Sidestep:** mechanically capped on Bittle (planar fore-aft legs, no lateral
  reach). **Trigger:** go-to-object / charger-docking on hardware shows a
  positioning need that turn-step-turn can't cover. Even then, expect a shuffle.
- **Sneak (slow, low, quiet):** not an RL problem — a posture + cadence variant
  of the existing walk. **Do this as a Skill Composer keyframe** (needs B3 +
  hardware), not a training run. Personality/patrol value (B4/B6/B7).
- **Backward as its own tuned gait:** the current policy does `cmd_fwd < 0`
  already; only revisit if hardware shows backing up is unreliable.

## H7 — Climb as a separate skill policy  🔴  ⚪

B13. Surfaces taller than standing height (full stairs, curbs it can't walk up,
onto a low platform). Its own motion, reward, terminal condition.

- **Highest sim-to-real risk on the roadmap** — contact-rich, posture-dependent.
- **Trigger:** a real, demonstrated need — does G2 actually have to change floors
  / get onto furniture in the use cases we care about? Not before.
- **Tier 2 (~25–70 mm):** a conditioning-input extension of the walk policy
  rather than a separate policy — the Phase 4 ledge primitive is the on-ramp.
- Needs hardware to validate at all.

## H8 — On-MCU gait policy (Decision Transformer)  🔴

B1. Shrink the policy to run on Bittle's own ESP32 (BiBoard V1) instead of the
Pi, per the "Tiny RL for Quadruped Locomotion using Decision Transformers" work.

- **Trigger:** measure `predict()` latency for the ONNX policy on the real Pi
  Zero 2 W (a step already in the plan). If the Pi *can't* hit control rate, or
  if freeing the Pi for voice/vision/memory is worth it, this becomes real.
- Research-heavy; a distinct pipeline from PPO + PyBullet.

## H9 — Get-up / self-right coverage  🟡  ⚪

The RL policy **can't** self-right (no roll-axis DOF — [[project_g2_no_self_righting]]).
Firmware has a scripted self-right, but only for slow side/forward falls and with
no BiBoard-V1 IR trigger.

- **Do now (sim):** run the get-up-sim reminder — replay the rc/rl get-up scripts
  in PyBullet and watch them ([[project_getup_sim_reminder]]).
- **Trigger (hardware):** G2 falls in orientations the firmware self-right
  doesn't cover, often enough to matter.
- **Work:** almost certainly a **keyframe/scripted** skill (Skill Composer), not
  RL — plus a fall-orientation classifier to pick the right recovery. Possibly an
  IR-trigger workaround for BiBoard V1.

---

## Do-now sim tasks (not hardware-gated)

- **Get-up sim replay** (H9) — watch the existing scripts in PyBullet.
- **ONNX export + numerical-parity check** — export `run20m_ppo`, confirm the
  exported policy matches the PyTorch one step-for-step before the Pi arrives.
