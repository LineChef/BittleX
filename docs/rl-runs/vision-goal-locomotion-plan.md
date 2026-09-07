# Vision-driven, goal-directed locomotion — investigation plan

**Status:** STREAMLINED + running autonomously (2026-09-06 night). User authorised
Claude to run all phases nonstop, decide gates by the rules below, launch the
Phase B 20M only on a clean checklist (hold + recommend if marginal), and
document outcomes. Phases 2+3 collapsed into **Phase A**; extended runs dropped;
smokes cut to 2M / 1 seed (2nd seed only if near threshold).

## Gate decision rules (locked 2026-09-06 — Claude decides against these)

**Phase 0** (graft obstacle-reward eval): the reward-shaped approach is KEPT only
if `graft_A_obsrw` shows lower peak contact force AND lower clip rate than
`graft_A_plain`, forward-distance/episode >= 70% of `run20m_graft282`, and fall
rate no worse. Otherwise the package is REWORKED for Phase A: drop `r_obs_stop`,
ledges 15-20 mm, `FAC_OBS_BUMP` halved. (The -26% reward on `graft_A_obsrw`
already makes rework the likely call.)

**Phase A** (goal command + vision avoidance, one 2M smoke):
- PASS -> Phase B if ALL: (1) goal-reach >= 80% at bearings 0/45/90/135deg, >=
  60% at 180deg; (2) no-goal heading drift < 10deg/episode; (3) no-goal cruise
  fall rate <= 5% and forward speed within 15% of `run20m_ppo`; (4) obstacle-course
  peak contact force AND clip rate <= the graft baseline.
- MARGINAL -> retune once if goal-reach 50-80%, OR drift 10-20deg, OR one gait
  metric 15-25% off.
- FAIL -> stop, document, recommend if goal-reach < 50%, OR drift > 20deg, OR
  fall rate > 15%, OR gait visibly broken.
- Retune budget: ONE iteration, adjusting the 1-2 terms implicated by the failed
  metric, then re-smoke and re-apply this gate.

**Phase B checklist** (3M smoke on the frozen final env) — 20M launches only if
ALL: (1) `ep_rew_mean` still climbing at 3M (last 500k slope > 0); (2) reward >=
Phase A smoke level (robustness DR added no regression); (3) no-goal cruise fall
rate <= 5%; (4) goal-reach >= Phase A level; (5) `explained_variance` > 0.3
(critic healthy — not the 1.1M-collapse signature). Any one borderline -> HOLD,
document, recommend. The 20M is adopted as the new base only if the full
decathlon + `benchmark_commanded` + `benchmark_goal` vs `run20m_ppo` holds every
old capability (Wilson CIs) AND adds goal/avoidance; else keep `run20m_ppo`.

## Results log

- **2026-09-06 23:10** — `graft_A_obsrw` done: `ep_rew_mean` 2986 -> 2210 (-26%)
  over 3M. Policy visibly learned to back away from walls (replay). `graft_A_plain`
  (vision finetune, no reward terms): 2888 -> 2753 at 311k (-5%) — the reward
  terms, not vision itself, drove the big drop.

- **2026-09-06 23:22** — Phase A infra built + committed (`48c2b42`, `1225344`):
  `G2E_GOAL_MODE` (obs -> 285), `r_goal_progress` / `r_goal_reached` /
  `r_obs_swerve`, heading retarget, moving goals, `GOAL_STANDOFF`,
  `set_goal()`; `benchmark_goal.py`; `graft_terrain_policy.py` generalised to +N;
  `G2E_OBSTACLE_X_HI` / `OBSTACLE_Y_SPREAD` (spread obstacles along a goal path).
  Default byte-identical (obs 278, reward 8224.909). `run20m_graft285` built,
  parity 1.2e-7. **Autonomous driver launched** (`/tmp/g2_phaseA_driver.sh`,
  PID 73021): waits for `graft_A_plain` -> Phase 0 eval -> Phase A 2M smoke
  (`phaseA_s1`, from `run20m_graft285`, GOAL+TERRAIN+OBSTACLE_REWARD v2:
  `FAC_OBS_STOP=0`, `FAC_OBS_BUMP=0.015`, ledges 18mm, obstacles to x=1.1 /
  y=+-0.12) -> Phase A eval -> stops for the gate decision. Expected complete
  ~1:25 AM 2026-09-07.

### Phase A course config (`phaseA_s1`)
`TERRAIN_FEATURE=1 GOAL_MODE=1 OBSTACLE_REWARD=1 EPISODE_LENGTH=1200`
`RANDOM_TERRAIN=0.06 PROB=0.8 MAX_H=0.09  OBSTACLE_COUNT=5 TALL_FRAC=0.3 SPAN_FRAC=0.1`
`OBSTACLE_X_HI=1.1 OBSTACLE_Y_SPREAD=0.12  LEDGE_HEIGHT=0.018 LEDGE_PROB=0.35`
`RUBBLE_PROB=0.3 SLOPE_MAX_DEG=8  FAC_OBS_STOP=0 FAC_OBS_BUMP=0.015`
from `trained/run20m_graft285`, `train.py --steps 2e6` (finetune lr 3e-5, target_kl 0.05).

## The idea

## The idea

`run20m_ppo` is a blind, velocity-commanded gait: `[cmd_fwd, cmd_yaw]`, and
`cmd_yaw` is force-zeroed in training (`_sample_command`, the "G4" comment) so it
only ever walks straight and holds its launch heading. Turning was tried once,
"fought heading-hold", and was cut.

The forward terrain feature (Phase 8, `TERRAIN_FEATURE`) gives the policy a coarse
"something ahead, this far, this bearing, tall-or-not" signal. Combined with a
**goal bearing**, turning becomes *purposeful* — the policy turns because the goal
is off to the side — and "hold heading" vs "turn" stop being in tension (both are
just "reduce the angle to the goal"). Obstacle detour + "return to bearing" also
falls out for free: there's no previous bearing to remember, just a still-current
goal to re-converge on.

**North star:** goal-seek with vision-driven local avoidance. Go-to-object (B8),
come-when-called, patrol (B7), obstacle detour — one behaviour.

**Realism constraints:** vision gives bearing to *detected objects*, no metric
depth, no odometry/SLAM. So goals are "toward/away from a detected thing" or a
short dead-reckoned vector — never "navigate to a point 3 m away". Policy leans on
`bearing`, treats `distance` as soft/optional.

## Rules

- Every new obs input follows the terrain-feature pattern: frozen index layout,
  `G2E_*`-gated, Pi-side mirror module, zero-init graft, parity test.
- `run20m_ppo` stays the frozen deployment base through every phase.
- **No 20M before Phase B.** Phases 0/A are de-risking smokes; the ONE 20M bakes
  in everything frozen.
- 1 seed per smoke; a 2nd seed only if the result lands near a gate threshold.

## Phases (streamlined)

### Phase 0 — vision-reward graft eval *(in flight)*
`graft_A_obsrw` (grafted `run20m_ppo` + `TERRAIN_FEATURE` + the 3 obstacle-
response reward terms, course A) and `graft_A_plain` (same, no reward terms) →
`eval_obstacle_response.py` (20 ep) vs `run20m_graft282`. Decides which reward
terms survive into Phase A (see Phase 0 gate rule above).

### Phase A — goal-bearing command + vision avoidance *(2+3 collapsed)*
**Build (one batch):**
- Obs: append `[goal_bearing_norm, goal_dist_norm, goal_active]` — frozen layout,
  `G2E_GOAL_MODE`-gated, zero-init graft (`run20m_graft282` → `run20m_graft285`).
  Pi-side `goal_feature.py` mirror + parity test.
- Reward: `r_goal_progress` (angle-to-goal reduction + distance closing),
  `r_goal_reached` (bonus + standoff distance so it stops short of the target,
  episode may end). Goal active → `FAC_HEADING` retargets from launch heading to
  goal heading.
- Reward package v2 (per Phase 0 outcome): keep `r_obs_bump`; ledges 15–20 mm;
  likely drop `r_obs_stop`; add `r_obs_swerve` (reward lateral deviation toward
  the open side when a close obstacle blocks the goal line — re-convergence is
  free from `r_goal_progress`).
- Curriculum: goal at random bearing incl. ±180°, distance 0.5–2.5 m, ~15%
  moving goals, ~20% no-goal (velocity fallback). `G2E_EPISODE_LENGTH` ~1200.
  Widen lane + obstacle lateral spawn so a detour fits; obstacles on the goal line.
- `benchmark_goal.py` — goals at 0/45/90/135/180°: reach rate, time-to-reach,
  path efficiency, fell; no-goal heading drift; gait-quality vs `run20m_ppo`.
  `eval_obstacle_response.py` for the collision metrics.

**Run:** `run20m_graft285` → **2M smoke, 1 seed**. Gate by the Phase A rule above
(PASS / MARGINAL→retune once / FAIL→stop).

### Phase B — freeze → 3M smoke → 20M
Freeze one final env: terrain feature + obstacle rewards v2 + goal-bearing
command + goal/avoidance rewards + robustness DR (slopes, rubble, H2/H3 backlog).
**3M smoke**, apply the Phase B checklist above. Clean → launch the **20M**
(one seed, ~8.5 h). Marginal → HOLD + write a recommendation.

**Adoption:** full decathlon + `benchmark_commanded` + `benchmark_goal` vs
`run20m_ppo`. New base only if it holds every old capability (Wilson CIs) AND adds
goal/avoidance. Else keep `run20m_ppo`, document the gap.

## Timing (measured: ~800 steps/s plain, ~690 + obstacle rewards, ~700 + goal/long episodes)

| step | training | eval | 
|---|---|---|
| Phase 0 *(running)* | 3M + 3M ≈ 2.4 h | 15 min |
| Phase A build | — | — |
| Phase A smoke | 2M ≈ 0.8 h (×2 if near threshold) | 20 min |
| Phase A retune (budget 1) | 2M ≈ 0.8 h | 20 min |
| Phase B build/freeze | — | — |
| Phase B 3M smoke | 3M ≈ 1.3 h | 20 min |
| Phase B 20M | 20M ≈ 8.5 h | decathlon+commanded+goal ≈ 1.5 h |

**Compute: ~16 h training + ~2.5 h eval.** ~16–20 h elapsed if run nonstop with
≤1 retune; longer if Phase A needs rework or a run diverges.

## Built so far (2026-09-06)

- `graft_terrain_policy.py` — 278→282 weight graft, zero-init new columns,
  verified 0.00 action delta (`run20m_ppo` → `run20m_graft282`).
- `OBSTACLE_REWARD` package (`r_obs_bump` / `r_obs_clear` / `r_obs_stop`),
  `eval_obstacle_response.py`, `watch_vision.py`.
- `G2E_*` override system; `G2E_TRAIN_YAW`, `G2E_EPISODE_LENGTH` (Phase 2 prereqs).
- Course A/B/C configs in `train_vision_smoke.py` (`--obs-reward`, `--from`, `--tag`).

## Still to build

- Goal-bearing obs block + `r_goal_progress` / `r_goal_reached` + goal curriculum
  + `G2E_GOAL_MODE` + Pi-side `goal_feature.py` mirror.
- `benchmark_goal.py`.
- `r_obs_swerve`; wider lane / obstacle spawn; ledge height → 15–20 mm in the
  course configs.
