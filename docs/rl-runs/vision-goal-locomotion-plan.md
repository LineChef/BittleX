# Vision-driven, goal-directed locomotion — investigation plan

**Status:** ⛔ **STOPPED 2026-09-07 02:09** — Phase A failed its gate twice
(smoke + the one budgeted retune). Goal-directed turning was not achieved;
`RESIDUAL_MODE` on a forward-only reference gait looks architecturally unable to
produce a turn. Phase B / the 20M did NOT run. See **Conclusion & recommendation**
below. Autonomous run per user authorisation 2026-09-06; `run20m_ppo` untouched
and still the frozen base.

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

- **2026-09-07 00:56** — **Phase 0 verdict: REWORK** (as anticipated).
  `eval_obstacle_response` (20 ep): `graft_A_obsrw` peakF 2.8 N / clip 0.75 vs
  base `run20m_graft282` 2.4 N / 0.69 — the reward package made contact *worse*,
  plus −26% reward and visible backing-away. Gate rule (keep only if force AND
  clip both drop) fails → package v2 for Phase A: `FAC_OBS_STOP=0`,
  `FAC_OBS_BUMP` halved, ledges 18 mm. (0 falls for all three — survival was
  never the issue.)

- **2026-09-07 00:56** — **Phase A (`phaseA_s1`) verdict: FAIL.**
  `benchmark_goal`: goal-reach **0% at every bearing** (0/45/90/135/180°);
  the policy ignored the goal and walked straight (closed 1.5→0.88 m for a
  dead-ahead goal, ended *farther* for side/behind goals). No-goal heading
  drift **34.7°** (gate wants <10°). `ep_rew_mean` (1200-step episodes)
  15129 → 7944 (−47%), min −2767, `explained_variance` 0.81.
  **Root cause:** `phaseA_s1` ran with `GOAL_MODE` but NOT `G2E_TRAIN_YAW` —
  the policy has never learned to turn, so no goal reward could produce turning,
  and `r_goal_progress` buried it under unescapable negative reward for
  off-axis goals → destabilised the finetune. The Phase-1 turning question,
  folded into Phase A, is now unavoidable.

- **2026-09-07 01:00** — **Retune (`phaseA_s2`), the one budgeted iteration:**
  add `G2E_TRAIN_YAW=0.4` (yaw command in the curriculum — teaches turning);
  `G2E_GOAL_BEARING_MAX=1.4` (~80°, narrow cone while turning is learned);
  `FAC_GOAL_PROGRESS 320→140`, `FAC_GOAL_FACE 8→22` (facing is the primary early
  signal); `r_goal_progress` per-step delta clamped ±0.02 m; less-gentle
  finetune `--finetune-lr 1e-4 --finetune-target-kl 0.15`, 3M steps, from
  `run20m_graft285`. If this also fails the gate → STOP, Phase B does not run,
  write the recommendation.

- **2026-09-07 02:09** — **Phase A retune (`phaseA_s2`): FAIL. Campaign STOPPED
  (retune budget exhausted). Phase B / the 20M did NOT run.**
  `benchmark_goal`: goal-reach still **0% at every bearing**; no-goal heading
  drift **37.3°** (worse than s1's 34.7°); `ep_rew_mean` 15214 → 8792 (−42%).
  Adding `G2E_TRAIN_YAW=0.4` + narrower goal cone + rebalanced goal rewards +
  a less-gentle finetune produced **no goal-directed turning whatsoever** — the
  policy still just walks straight (dead-ahead goal: closes 1.5→0.83 m by
  walking forward; side/behind goals: ends farther away).

## Phase C — turn-blend + full vision stack (2026-09-07, autonomous, rate-limit-safe)

After Phase A's finding (residual-on-`wkF` can't turn), the user approved:
fold `wkL`/`wkR` scripted turn gaits into the residual base, bake **all**
vision-derived gait inputs into ONE fresh run, and run it hands-off.

**Built (2026-09-07 AM, committed `04fd747`/`6079b2d`):**
- `wkL` parsed from `InstinctBittleESP.h` -> `wkl_ref.npy`; `wkr_ref.npy` = its
  L/R mirror (`reference_gait/build_turn_references.py`). `TURN_BLEND` (`G2E`):
  residual base = `wkF + |w|*(wkL_or_R - wkF)`, `w = cmd_yaw/CMD_YAW_MAX`.
  Verified: `w=0` -> pure `wkF`; `w=+-max` -> 28-44 deg of turn-shaped deviation.
- Goal feature gains a **polarity** dim `[bearing, dist, active, polarity]`
  (+1 approach / -1 flee) -> `GOAL_AVOID_FRAC`. Reward + heading retarget flip
  with polarity.
- **Cliff feature** `[edge_present, edge_dist, edge_bearing]` (`G2E_CLIFF`):
  finite platform on `CLIFF_PROB` episodes, forward floor-scan, `FAC_CLIFF_FALL`
  penalty + terminate on CoM off-platform, tight (`< CLIFF_SLOW_DIST`) slow
  reward. No general caution reward -> not timid.
- obs 278 -> **289** with full config (4 terrain + 4 goal + 3 cliff); default
  every flag off => byte-identical (verified obs 278, reward 8224.909).
- `run20m_graft289` (278->289 zero-init graft, parity 1.2e-7).
- `FAC_IMITATION` now `G2E`-overridable (loosen the anchor for turning).
- **Deferred** (note for the 20M, not blocking): terrain `spanning` bit
  (wall-vs-around stays emergent for now).

**Autonomous driver:** `run_vision_goal_campaign.sh` + `gate_check.py`
(deterministic). Flow: 3M smoke (finetune from `run20m_graft289`, full config)
-> `benchmark_goal` -> `gate_check` -> **GO_20M** (fresh 20M, same config,
`--tag phaseC_20m`) / **RETUNE** (one pass: narrower goal cone, stronger facing
pull, `FAC_IMITATION` 7->4) / **STOP**. All steps run detached; progress to
`trained/campaign_results.log`, final line `CAMPAIGN COMPLETE` or
`CAMPAIGN STOPPED`.

**Gate rule (locked):** GO_20M iff reach >=60% at 0/45/90deg, >=40% at
135/180deg, no-goal drift <15deg, cruise fall <=8%, reward not collapsed
(final >= 55% of peak). STOP iff reach <30% at 0deg. Else RETUNE (once).

### >>> RESUME HERE if a session died mid-campaign <<<
1. `tail -40 rl_training/opencat-gym/trained/campaign_results.log` -- shows the
   last stage + gate decisions.
2. If it ends with `CAMPAIGN COMPLETE`: read `trained/phaseC_20m_eval.txt`,
   `phaseC_20m_goal.json`, `phaseC_20m_commanded.json`,
   `phaseC_20m_decathlon.json`. Compare `phaseC_20m_ppo` vs `run20m_ppo` on the
   decathlon; adopt as new base only if it holds every old cell AND adds
   turning/goal. Then write the HTML report + update this doc + memory.
3. If it ends with `CAMPAIGN STOPPED`: read the smoke `*_goal.json` +
   `*_eval.txt`, diagnose, write the recommendation. Do NOT relaunch a 20M
   without a fresh design pass.
4. If it's mid-run (no final line) and `pgrep -f 'run_vision_goal_campaign|train.py'`
   shows it alive: let it finish, re-arm a watcher on `campaign_results.log`.
5. If the process died but training didn't finish: the last `trained/phaseC_*_console.log`
   + its checkpoint show where it stopped; re-run `run_vision_goal_campaign.sh`
   (it will overwrite tags) or resume the specific `train.py` with `--from` the
   last `trained/checkpoints/phaseC_*_<steps>_steps.zip`.
6. `run20m_ppo` is untouched throughout -- it is always the safe fallback base.

## Conclusion & recommendation (2026-09-07) — supersedes for Phase A only

**The streamlined plan's core bet — "graft `run20m_ppo` + finetune teaches
goal-directed turning" — is disproven.** Two finetunes (gentle 2M; less-gentle
3M with a yaw curriculum), zero turning both times, heading control *degraded*
both times.

**Why (best read):** `RESIDUAL_MODE = True` with `RESIDUAL_SCALE_DEG = 22` and
`FAC_IMITATION = 16`. The policy outputs a bounded ±22° correction on the
scripted **`wkF` forward-walk** keyframes, anchored to them by a strong
imitation reward. A turn is a sustained *asymmetric* gait (the firmware turns
with entirely different keyframe tables, `kbk`, not by perturbing `wkF`). A
±22° residual on a symmetric forward reference almost certainly **cannot express
a turning gait**, so no reward or curriculum at this layer will produce one.
This matches the historical note that turning "trained to zero effect in phase 2
and fought heading-hold" — same symptom, now with a mechanism. A gentle finetune
from a 20M-converged policy also can't add a limb-coordination pattern it never
had; both runs just added heading noise.

The **vision obstacle-response** side is separable and roughly neutral: package
v2 (`FAC_OBS_STOP=0`, `FAC_OBS_BUMP` halved, 18 mm ledges) on `phaseA_s2` gave
peak contact 2.7 N / clip 0.69 vs base 2.6 N / 0.66 — not harmful, not buying
much either. 0 falls throughout. The terrain feature + a light bump penalty are
safe to carry into a future run but don't justify one alone.

**Recommendation, in order:**

1. **Ship what works now (low risk):** keep `run20m_ppo` for straight-line
   locomotion; do heading changes with the **firmware's scripted turn gaits**
   (`kbk` etc.), switched by a higher layer. Use the RL policy for forward walk
   + vision-driven *slow-down* near obstacles (not detour). This is a real,
   shippable capability and matches the original project stance ("real turns go
   to firmware"). No 20M needed.

2. **If a proper learned turning gait is wanted — it's a fresh run, not a
   finetune, and needs an architecture change first:**
   - **2a (preferred):** add turn-gait references (`wkL`/`wkR` from
     OpenCatEsp32, or build them) and make `RESIDUAL_MODE` blend
     `wkF`→`wkL`/`wkR` by the yaw command, policy residual on top. Then a
     **fresh ~15–20M** run with the yaw + goal curriculum from step 0. Keeps
     the residual's transfer robustness. ~1 build session + one 20M.
   - **2b:** drop `RESIDUAL_MODE` for the goal-directed policy, learn the gait
     from scratch with yaw + goal curriculum, ~20M. Cleanest, but loses the
     residual robustness and re-opens sim-to-real risk.
   Either is gated on the [[project_longrun_trigger]] checklist and should wait
   until hardware validates the forward gait.

3. **Defer entirely** until hardware, when real servo turn authority is known —
   a learned turning gait tuned in sim may not transfer.

**Not carried forward:** Phase B, the 20M, `phaseA_s1/s2` checkpoints (throwaway).
**Kept:** `run20m_graft282` / `run20m_graft285` (grafts, reusable), the
`G2E_GOAL_MODE` / `G2E_TRAIN_YAW` / goal-reward / `benchmark_goal.py`
infrastructure (all committed, dormant by default, ready for a proper run).

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
