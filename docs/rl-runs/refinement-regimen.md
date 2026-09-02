# Walking-policy refinement regimen

Staged plan to refine the gait to the point a **~20M-step training run is
justified** (see the green-light checklist in memory `project_longrun_trigger`
and `docs/research/bittle-rl-projects.md`). Each stage = one short run (2-3M)
isolating one design decision, with a keep/revert bar. Built on the Bittle-RL
survey's recommendations.

Base: whatever the drift-fix loop lands (`d2_cadence` / `d3_*` on branch
`drift-fix`).

| stage | change | runs | exit condition |
|---|---|---|---|
| **0. drift-fix** *(in progress)* | D2 per-episode gait-cadence randomization (`PHASE_RAND`), D3 consolidate | 2 | gait holds a straight line across cadences 0.6x-1.4x -- prerequisite for command-following |
| **1. action space** | check action clip-fraction on the current best; if saturating, raise `RESIDUAL_SCALE_DEG` 11 -> 18 -> 25, paired with a stronger `FAC_IMITATION` anchor so it stays a gait not a crawl (r1's 18 warped wkF) | 2-3 | residual has room to correct (green-light #4); keep the largest value that doesn't warp wkF |
| **2. reward completeness** | 2a body-height target `FAC_HEIGHT` (URMA's biggest weight -- kills the crouch/collapse failure); 2b joint-limit-proximity penalty (URMA 10.0); 2c phase-gated foot term (no GRF in swing, no slip in stance, tied to the gait clock -- Bittle_Symmetry_RL) | 3 | reward has no gaps, validated via the per-term `info` breakdown (green-light #1); each additive + isolated, kept on trot-tightness + speed holding |
| **3. domain randomization** | 3a actuator delay (randomised 1-3 control-step command lag); 3b joint zero-point offset (+-few deg/episode); 3c PD-gain / motor-strength randomisation + observation dropout; 3d widen friction 0.30->0.5, mass 0.18->0.25, terrain variety | 4 | DR broad enough to fill 20M steps (green-light #3); narrow a range if it crushes the gait, do not drop the knob (transfer insurance) |
| **4. commanded locomotion** | add commanded forward-speed + yaw-rate to the obs; flip `FAC_YAW`/`FAC_HEADING` from "penalise all turning" to "track the command"; sample commands during training (mostly straight), resample every N steps not every step | 1 (3M) | gives a long run 20M distinct situations; subsumes straight walking (cmd=0); settles the firmware-turn decision gate in the RL-primary direction. Benchmark commanded-vs-achieved tracking |
| **5. freeze + qualify** | assemble the winning config, one 3M run of the frozen recipe | 1 | **the gate:** per-term breakdown clean; `ep_rew_mean` / benchmark score **still climbing at 3M**; clip-fraction healthy; DR + curriculum in place -> alert the user, discuss the 20M run. If plateaued at 3M -> diagnose which term/knob caps it before scaling |

## Sequencing logic

Action space first -- a saturating residual caps everything downstream. Reward
completeness before DR -- get the target behaviour right before making it robust.
Commanded locomotion last -- biggest change, benefits from everything before it.
Stage 5 is the honest gate.

## Compute

~12-15 short runs x (~50 min train + ~15 eval) = ~12-18 h, spread over a few
automated sessions. Plus ~1-2 h code each for the Stage 2c and Stage 4
obs/reward changes.

## GPU sim port -- DEFERRED (decision 2026-09-02)

Porting to a GPU sim (MJX best fit for the user's RTX 2080; Isaac Lab is
minimum-spec on 8 GB) would make every stage run in minutes and the 20M run
~1 h. **Not doing it now.** It is a full re-implementation, not a translation:
different contact/friction/actuator physics (so `wkF` and every tuned `FAC_*`
weight need re-deriving -- `cov_r1_slope` would not exist there), JAX's
functional/vectorised paradigm (rewrite, not copy), and it trades a *known*
sim-to-real gap for an unknown one. The CPU compute for this regimen (~15-20 h
over ~5-6 unattended sessions) is manageable.

Revisit the port only if, after the 20M run, the gait needs dozens more
iterations, or a 100M-scale run is on the table, or commanded-locomotion +
vision-conditioned gait becomes a multi-month effort. If we ever do port, this
PyBullet env stays as the **reference to match** (reproduce these benchmark
numbers) -- which is what makes that rewrite tractable.
