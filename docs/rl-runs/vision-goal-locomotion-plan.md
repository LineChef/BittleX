# Vision-driven, goal-directed locomotion — investigation plan

**Status:** Phase 0 running (2026-09-06 night). Plan agreed with the user.

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
- **No 20M before Phase 4.** Phases 0–3 are ≤10M smokes whose only job is to
  de-risk and freeze the env design. The ONE 20M (Phase 4) bakes in everything.
- Phase 2 onward: **2–3 seeds per gate decision** — single runs misled us badly
  on 2026-09-06 (course A vision -10%, course B vision +16%, both n=1).

## Phases

### Phase 0 — finish the vision-reward runs *(in flight)*
`graft_A_obsrw` (grafted `run20m_ppo` + `TERRAIN_FEATURE` + the 3 gated
obstacle-response reward terms, course A) and `graft_A_plain` (same, no reward
terms) → `eval_obstacle_response.py` vs `run20m_graft282`.

**Gate Q:** Does the grafted deployment gait's obstacle behaviour change with
vision, and does the reward package help (bump force down, forward distance
holds) or just cause timidity (forward distance craters)?
→ Decides whether reward-shaped vision-on-the-gait is viable, and which terms to
keep. Early signal: `graft_A_obsrw` reward drifted 2990 → 2790 over 1.1M steps
while the policy visibly learned to back away from walls — likely `r_obs_stop` +
the too-tall (30 mm, un-steppable, un-turnable) ledges over-driving avoidance.

### Phase 1 — raw yaw *(SKIPPED — folded into Phase 2)*
Was a debugging-isolation step. Since goal-directed is the committed approach,
`FAC_HEADING` gets retuned in Phase 2 regardless. Kept only as a fallback
diagnostic if the Phase 2 smoke fails ambiguously. `G2E_TRAIN_YAW` (built
2026-09-06) re-enables `cmd_yaw` sampling if we need it.

### Phase 2 — goal-bearing command
**Build:**
- Obs: append `[goal_bearing_norm, goal_dist_norm, goal_active]` — frozen layout,
  `G2E_GOAL_MODE`-gated, Pi-side mirror, zero-init graft.
- Reward: `r_goal_progress` (angle-to-goal reduction + distance closing),
  `r_goal_reached` (bonus, episode may end). When a goal is active, `FAC_HEADING`
  retargets from "hold launch heading" to "align to goal".
- Curriculum: goal at random bearing incl. behind (±180°), distance 0.5–2.5 m;
  ~20% no-goal episodes (velocity fallback preserved).
- `G2E_EPISODE_LENGTH` → ~1200 (built 2026-09-06). Widen the reset area.
- `benchmark_goal.py` — goals at 0/45/90/135/180°: time-to-reach, final distance,
  path efficiency, fell; heading-hold on no-goal episodes; gait-quality vs
  `run20m_ppo`.

**Run:** graft `run20m_ppo` + goal block → 3M smoke × 2 seeds; if learning, extend
to ~12M × 1.

**Gate Q:** Reliably turns to face and reaches goals at every bearing, without
losing straight-line walking (no-goal drift < 8°) or gait quality.

### Phase 3 — vision-driven local avoidance on the goal-seeker
**Build:**
- Widen lane + obstacle lateral spawn so a detour fits; place obstacles ON the
  goal line so avoidance is necessary.
- Reward package v2: **drop `r_obs_stop`**; keep `r_obs_bump` (horizontal-contact
  penalty) + `r_obs_clear` (step over low, ledges at 15–20 mm now); add
  `r_obs_swerve` — reward lateral deviation toward the open side (`bearing_norm`)
  when a close obstacle blocks the goal line. Re-convergence is rewarded for free
  by `r_goal_progress`.
- `eval_obstacle_response.py` v2 (+ detour success rate, deviation-and-recovery,
  goal-still-reached).

**Run:** finetune from the Phase 2 policy, 5M × 2 seeds; if passes, 10M × 1.

**Gate Q:** Detours around blocking obstacles and re-converges on the goal, with
fewer collisions than the goal-only policy, without tanking goal-reach rate.

### Phase 4 — consolidate → the 20M
Freeze one final env: terrain feature + obstacle-response rewards (v2) +
goal-bearing command + goal/avoidance rewards + robustness DR (slopes, rubble,
H2/H3 backlog). 3M smoke to confirm reward still climbing at 3M. Then the
[[project_longrun_trigger]] checklist gates a fresh ~20M.

**Gate Q (adoption):** A/B vs `run20m_ppo` on the full decathlon + commanded +
goal benchmarks. Adopt only if it holds every old capability AND adds the new
ones. (This is where the H12 new-course attempt failed — regressions on
bare-robot / ledges / carpet.)

## Timing (measured 2026-09-06: ~800 steps/s plain, ~690 + obstacle rewards, ~700 + goal/long episodes)

| phase | training wall-clock | eval | notes |
|---|---|---|---|
| 0 | 3M + 3M ≈ 2.4 h | 15 min | results ~12:20 AM 2026-09-07 |
| 2 smoke | 3M × 2 ≈ 2.4 h | 20 min | + build |
| 2 extended | 12M × 1 ≈ 4.8 h | 30 min | if smoke passes |
| 3 smoke | 5M × 2 ≈ 4 h | 40 min | + build |
| 3 extended | 10M × 1 ≈ 4 h | 40 min | if smoke passes |
| 4 smoke | 3M ≈ 1.3 h | 20 min | full final env |
| 4 the 20M | 20M × 1 ≈ 8.5 h | decathlon+commanded+goal ≈ 1.5 h | one overnight |

**Compute: ~34 h training + ~5 h eval.** Calendar ~1–2 weeks with build work,
seed reruns, and iterating on failures between phases.

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
