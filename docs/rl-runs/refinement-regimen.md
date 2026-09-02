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

---

## Post-Phase-2 revision (2026-09-02)

Phases 0-4 of the table above ran on branch `gait-refinement`, rebuilt into one
recipe (G1 action+reward, G2 commanded locomotion, G3 sim-to-real DR). The
from-scratch 10M validation (`phase2_ppo`) then surfaced findings that change the
forward plan:

**What Phase 2 showed** (full scorecard: artifact "Phase 2 Gait Scorecard"):

- **The gait is payload-conditioned.** With the 75 g Pi/camera payload on (G3,
  90% of episodes) `phase2` is flawless: 0% falls on all 15 decathlon cells
  including the compound gauntlet. With the payload *off* it falls 17% on
  average, 68% on the gauntlet, 96% on a bare-robot steep descent -- worse than
  open-loop scripted on the hard cells. It over-fit to the near-constant payload.
- **Weight-matched, the walk is at parity with scripted.** Learned + payload vs
  scripted `wkF` + payload + balance-assist 0.5, matched seeds: 0% falls each,
  equal average speed. `phase2`'s value is the *command interface* (speed track
  to 0.003 m/s, stand, backward, heading-hold to 0.2 deg) -- things `wkF`
  structurally cannot do -- not a more robust walk.
- **Turning never trained.** Yaw command has ~zero effect (actual yaw-rate
  ~-0.006 rad/s regardless of command). Heading-hold, which shares the machinery,
  works well.
- **Speed modulation collapses at the ends.** creep (0.04) and fast (0.13) both
  regress toward cruise (~0.10); only mid-range tracks.
- **The decathlon saturates with the payload on.** Both gaits 0% falls even at
  -24 deg descent / 20 deg brutal gauntlet. Falls are no longer a discriminating
  metric; commanded progress + speed retention + heading drift are.

**Revised forward plan:**

| step | change | type | gate |
|---|---|---|---|
| **Phase 3** *(running)* | `PAYLOAD_PROB` 0.90 -> **1.0** + mass range 60-90 g -> **40-110 g** (payload is bolted on; widen mass instead of ever training a bare robot). Drop turning from the command curriculum (`cmd_yaw` always 0; heading-hold stays). Explicit low/mid/top speed bands, heavy weight on extremes. Proportional speed-track band `max(0.012, 0.15*|cmd|)`. | from-scratch 10M, bailout at 1M/3M | speed modulation tracks creep + fast; nominal walk not regressed vs `phase2` on the payload-on decathlon |
| **T6 hardened tier** *(done)* | `benchmark_decathlon` T6.1-T6.5: -24 deg descent, 85 mm obstacles, 1.0 shoves, 20 deg gauntlet, 60% torque cutback + descent. Scored on **commanded progress / speed / drift**, not falls. | eval only | scripted+payload shows a measurable progress/speed gap on T6.1 + T6.5 -> usable as the standing baseline |
| **20M consolidation** | freeze the Phase 3 recipe, one ~20M run | 1 (20M) | green-light checklist (memory `project_longrun_trigger`): reward validated + still climbing at 3M, DR/curriculum in place, residual not saturating, design frozen |
| **Phase 4: stance recovery** *(after 20M)* | ledge / step-down terrain primitive (a sharp 10-40 mm rise/drop, not just the smooth bump field); re-enable `PHASE_SLOW_RATE` (~0.25) above `PHASE_SLOW_TILT` with reduced `FAC_IMITATION` while slowed (R2 disabled this because imitation fought the catch); bonus for regaining a diagonal (1,3)/(0,2) stance after a foot-contact anomaly; loosen the residual cap during `_in_recovery`. | **continuation** on the 20M policy (obs unchanged), 3-5M, 1-2 iterations | dedicated bare-robot ledge eval cell shows fewer topples + off-rhythm re-plant; **hard capability-bar gate** -- nominal speed / fall / smoothness must not regress or revert to the 20M policy |
| **Hardware tuning** | once G2 is built, re-tune Phase 4 against the real failure modes rather than the guessed ones | continuation | on-robot |

**Why this order:** Phase 3 fixes the two real, payload-independent weaknesses
(speed modulation, dead turning channel) and removes the payload over-fit. The
20M run consolidates *robust blind walking + commands* -- the deliverable for the
hardware head-to-head. Stance recovery is the highest sim-to-real-risk change on
the table (a timing-sensitive reactive behaviour, and `PHASE_SLOW` destabilised
the gait once already), so it goes last, as a *reversible* continuation with a
hard gate: if it degrades the nominal walk, revert to the 20M policy and lose
nothing.

**Realistic ceiling** (Boston-Dynamics comparison, 2026-09-02): Spot-level
stability needs torque-controlled backdrivable actuators, a ~1 kHz loop, and free
foothold planning -- none of which this platform has. The achievable target is
"sure-footed on a cluttered floor": won't fall from the disturbances a small
quadruped meets indoors (bumps, thresholds, slopes, a nudge, a shifting
payload), and on a bad foot plant *wobbles and usually recovers* rather than
committing to the topple. Not a crisp capture step -- that needs a free-gait
architecture and faster hardware, neither required for an indoor companion robot.
