# Vision-driven, goal-directed locomotion — investigation plan

> **Campaign closed 2026-09-08.** Phases A/C: turning not achievable in this sim
> (→ firmware). **Phase D: vision-in-the-loop ruled out** — a forward terrain
> feature made no more capable a gait than the blind policy (report:
> `claude.ai/code/artifact/bfb58d90-71ca-4681-9c72-d14e15e56b7a`; result section
> below). Ship the `Avoider` speed reflex on the frozen `run20m_ppo`. **Next:**
> adapter skill probe — `docs/rl-runs/adapter-skill-probe-spec.md` (specced,
> deferred; skill refs + `G2E_SKILL_REF` hook already on `development`).

---

**Status:** ⛔ **STOPPED 2026-09-07 10:02 (Phase C).** Three campaigns
(A / A-retune / C), zero turning each. **Diagnosis complete:** the scripted
OpenCat turn gaits (`wkL`/`wkR`) do not turn the robot in this sim/URDF, even
open-loop — so no RL at the residual layer can learn a turn. It's a sim-physics
limit, not a reward/architecture problem. Recommendation: **turning goes to
firmware** (see the updated recommendation in **Phase C RESULT** below).
`run20m_ppo` untouched throughout, still the frozen base. No 20M ever ran.

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

## Phase D — the A/B we never ran: from-scratch, vision vs blind (2026-09-07)

Phase A–C all tested vision as a *finetune*, and finetunes fail here. Phase D is
the clean test the user asked for: **two fresh 20M runs, identical course /
rewards / anchor, the only difference is whether the policy can see forward.**

**Design (committed `ba77f13`, driver `run_ab_vision.sh`):**
- `abD_vision` — fresh 20M, `G2E_TERRAIN_FEATURE=1` (obs 282).
- `abD_blind` — fresh 20M, `TERRAIN_FEATURE` off (obs 278). Identical everything else.
- Shared: cluttered course (`OBSTACLE_COUNT=5`, 30% tall, spread to 1.0 m,
  18 mm ledges, rubble 0.35, slopes 10°); **R-NOSTALL** anti-stall reward
  (`FAC_NOSTALL=22`: dense window-speed bleed under 40% of cmd + `+8` per 0.15 m
  cleared *while an obstacle was in view*) — the term that gives vision leverage;
  **`FAC_IMITATION` 11 -> 5** (loosen the `wkF` anchor so the gait is free to
  adapt — the user's concern that the anchor has been fighting a vision response).
- `RESIDUAL_MODE` stays ON (isolates *vision*, not architecture; 20M is proven
  sufficient for residual-from-scratch). No turning, no goal, no cliff — this run
  is only about "does seeing forward help obstacle walking."
- Eval: `eval_obstacle_response.py` on both (matched seeds, 40 ep) + decathlon
  each (base-capability regression check).

**Question:** does `abD_vision` make significantly more forward progress / stall
less on the cluttered course than `abD_blind`, without a decathlon regression?
If yes -> vision-in-the-loop is worth pursuing (Tier B proper). If ~equal ->
rule it out, ship the behaviour-layer `Avoider` reflex (Phase 8 plan).

**Timing:** ~9.3 h + ~8.5 h + ~2 h eval ≈ **20 h**. Started 2026-09-07 ~11 AM ET
-> complete **~7 AM ET 2026-09-08** (well before the Tue 1 PM quota rollover).

### Phase D RESULT (2026-09-08 01:19 — `A/B COMPLETE`): vision ruled out.

Report artifact: `claude.ai/code/artifact/bfb58d90-71ca-4681-9c72-d14e15e56b7a`.

Both runs trained cleanly (EV ~0.82, KL <0.004, std ~0.11, 0 training falls),
converged. `ep_rew_mean` blind ~−1650 vs vision ~−1800 (vision pays into the +8
breakthrough channel; absolute reward not the verdict).

**`eval_obstacle_response` (40 ep, matched seeds, 147/141 encounters):**
| | vision decel | blind decel | vision peakF | blind peakF | fall (both) |
|---|---|---|---|---|---|
| tall | 0.83 | 1.89 | 1.9 N | 2.0 N | 0.0 |
| low | 1.51 | 1.56 | 2.6 N | 2.2 N | 0.0 |
| all | 1.14 | 1.72 | 2.2 N | 2.1 N | 0.0 |

- Falls: tie at zero, every cell.
- The seeing policy slows **less** on tall obstacles (0.83 vs 1.89) — the
  opposite of the intended "see it, brace". It ignored the feature and walked
  through at commanded speed.
- Low obstacles: vision slightly rougher (2.6 N vs 2.2 N, clip 0.67 vs 0.59).
- Per-term reward near an obstacle: `r_obs_clear/stop/swerve` all 0.0,
  `r_nostall` nets −0.2. The dense speed-track penalty rewards *holding*
  commanded speed; the breakthrough bonus fired too rarely to shape anything.

**Regression check (decathlon, obstacle-free cells, `abD_vision` re-run WITH
`G2E_TERRAIN_FEATURE=1`):** vision holds — flat 0.092 vs blind 0.084, both 0%
fall on every base-tier cell T1–T6.5. The feature cost nothing on plain walking;
it just bought nothing.

**Verdict:** not a vision win → rule vision-in-the-loop out. Ship the `Avoider`
speed reflex on the frozen `run20m_ppo`. `abD_vision`/`abD_blind` kept as
checkpoints, not adopted (no capability gain; fresh-20M trades some robustness on
the hardened stress tiers). Next: the adapter skill probe.

**Driver bug:** `run_ab_vision.sh` ran `benchmark_decathlon.py` for `abD_vision`
without `G2E_TERRAIN_FEATURE=1` → obs-shape crash, no `abD_vision_deca.json` from
the driver. Fixed: decathlon lines now prefixed with the feature flag.

---

## Phase E — vision-triggered SCRIPTED skills (planned 2026-09-08)

**User's decision after Phase D:** vision-in-the-loop *did* alter behaviour (the
vision policy tried to high-step — but only one front arm, "feeling" for the
ledge; a bounded residual on `wkF` can't coordinate a whole-gait step-over). So:
**the main walk stays learned (`run20m_ppo`, untouched); the extra skills are
SCRIPTED keyframe movements**, and vision selects which one to run. No adapter, no
fresh base — `run20m_ppo` is never modified. Cheaper than teaching the skills;
the open question is how well scripted (open-loop) skills actually clear
obstacles and survive a disturbance mid-skill.

**Also settled:** the obstacle `Avoider`'s slow/stop logic **moves out of the
walking layer into `CliffGuard`** — anticipatory slowing only has a safety
rationale at a drop-off, not for obstacles G2 never falls on. Obstacle `Avoider`
→ `STOP`/`BACK_UP`/`TURN` only, or shelved until hardware.

**Why Phase D failed (design inputs for the next test):**
- `_scan_terrain()` casts a *horizontal* ray fan pegged to `base_pos[2] − 0.08`.
  The policy learned to **stand ~3 cm taller so the low rays pass over short
  obstacles** → feature reads "clear" → keep walking. It blinded its own sensor.
- Reward made *being near an obstacle* net-negative (`r_speed` 2.4 vs 3.0 clear,
  `r_speed_track` −2.8 vs −2.4). "Don't detect obstacles" was optimal.
- `r_obs_clear/stop/swerve` were all inactive (config never enabled them).

### Plan

**E-1 — skill-switch layer.** DONE (`pi_pipeline/gait/skill_switch.py` +
`test_skill_switch.py`, 9 green). `SkillSwitch.update(GaitMode, rl_joint_deg) ->
(joint_deg, Source)`. Modes `CRUISE` / `CAREFUL` (RL drives, `speed_scale` 0.6) /
`STEP_OVER` / `INSPECT` (crouch → mast pitches down) / `HALT` (preempts). Blended
handoff: lerp RL pose → skill frame 0 over `blend_in_steps`, play the keyframe
loop, lerp back. Pure logic + keyframe interpolator; refs are the
`reference_gait/*_ref.npy` (rad, URDF order), converted to deg internally. Still
to wire: a `run20m_ppo`-driver → `SkillSwitch` → `deploy_map` loop, and the
vision→`GaitMode` selector (rule-based on the terrain feature to start).

**E-2 — env fixes** (env changes, small-scale testable, gate everything):
- Anchor the terrain scan to the **camera pose** (fixed mast height, angled
  slightly down), not body height — kills the "stand tall to go blind" exploit.
- Course with **real fall hazards** (drop-offs / gaps: blind = fall) so vision
  has something to prove; tighten obstacle difficulty so "barge through" isn't
  free.
- Reward: detected-and-cleared ≥ never-detected; don't punish slowing while an
  obstacle is in view; enable `r_obs_clear`.
- Optional: replace the 4-float terrain summary with an 8–16-cell height-map
  strip for a cleaner trigger.

**E-3 — tune:** which scripted skill (`tr_ref` trot has the widest foot lift;
`cr_ref` = inspect crouch; author a high-step if `tr` isn't enough) for which
situation; trigger thresholds; strides per skill; blend timing.

**E-4 — eval:** `run20m_ppo` alone vs `run20m_ppo` + skill-switch on the hazard
course — clears obstacles the blind gait stumbles on / fewer falls at gaps,
**no** open-ground regression. A clean win here is what finally justifies a
fresh vision-baked ~20M (Tier B).

**Order:** E-2's scan + reward fixes first (they're why D failed), E-1 wiring in
parallel, then E-3/E-4. The adapter probe (`adapter-skill-probe-spec.md`) is
**shelved** — only revisited if a scripted `STEP_OVER` proves too fragile
open-loop, in which case that one skill becomes a learned module.

### E-4 FIRST RUN (2026-09-08): promising, not yet proven

Report: `claude.ai/code/artifact/88ea1a14-ab32-4000-8e87-422264667150`.

Built + committed: `SkillSwitch` (via-stance blend + phase-gated start, 13
tests), `GaitSelector` (terrain reading → `GaitMode`, 11 tests), `_scan_terrain`
pinned to true ground via a down-raycast (kills the D self-blinding exploit),
inert `_abs_joint_override` env hook, and `eval_skill_switch.py` — a **no-training**
A/B harness (frozen `run20m_ppo` + `GaitSelector`→`SkillSwitch` vs the policy
alone). Course: 5 obstacles, mostly ≤55 mm (step-over), 15% tall (walls), 22 mm
ledges. 24 eps, matched seeds.

| run | falls | wall-stops | walked fwd | step% | halt% |
|---|---|---|---|---|---|
| baseline (`run20m_ppo` alone) | 0% | 0/24 | 0.116 m | — | — |
| + switch, conservative trigger | 0% | 5/24 | 0.148 m | 1% | 18% |
| + switch, **eager trigger** | 0% | 4/24 | **0.195 m** | 16% | 22% |

- Infra works end-to-end, 0 crashes / 0 falls in 72 eps, policy never modified.
- The switch **stops at walls** (4–5/24 `HALT`) where the blind gait plows in.
- Conservative trigger under-fired `STEP_OVER` (1%) — stale ~16 Hz scan + 0.1 m/s
  creep means it must commit early. `GaitSelector` defaults retuned eager
  (`far/mid/close` 0.62/0.50/0.50, `debounce` 1) → `STEP_OVER` 16%, walked
  distance **+68% vs blind**.
- **Not a clean win yet:** blind never falls here either, so "clears what blind
  can't" isn't shown; and the +68% isn't fully attributed to `STEP_OVER` vs the
  careful/handoff dynamics. Small n, one seed offset, favourable course.

### E-3 done (2026-09-08): seed sweep + attribution + crouch ruled out

5 seed offsets × 12 eps = 60 per arm. `CAREFUL` now scales `cmd_fwd` 0.6× (was a
harness no-op). Report updated (same URL).

| | walked fwd (mean ± sd) | wall-stops | falls |
|---|---|---|---|
| baseline | 0.152 ± 0.166 m | 0/60 | 0% |
| + switch | **0.225 ± 0.166 m (+48%)** | 11/60 | 0% |

- **Step-over IS the mechanism.** Per obstacle encounter: `STEP_OVER` fired →
  passed 0.075 ± 0.094 m (n=84); didn't fire → 0.012 ± 0.023 m (n=23, stuck).
  ~6× traversal. The gain isn't a handoff artifact. (Some selection — it fires
  when the obstacle looks clearable.)
- **The replay "crouch" is nothing.** Body-z by control source: RL 0.074, blend
  0.076, scripted 0.078 m (higher, not lower); pitch flat ±0.002 rad. What looked
  like a crouch on approach is the `CAREFUL` slowdown, not a posture change.
- Wide per-episode spread (σ 0.17 m both arms) — a consistent lean, not a
  landslide. Still 0 falls; stops at walls where blind (0/60) never does.

**Still open in E-3:** pick the step-over skill deliberately — `tr` (trot) vs an
authored high-step.

### Proposed skill set for obstacle navigation (sandbox backlog)

Firmware refs already extracted: `wkF/wkL/wkR/cr/tr/vt/bk/rc`.

| skill | situation | ref | status |
|---|---|---|---|
| **step-over** | low obstacle in path | `tr` (or authored high-step) | HAVE |
| **halt** | wall / impassable → stop, hand to nav | stance | HAVE |
| **inspect / peer-down** | pitch mast down to see near-ground | `cr` held | defined, not triggered |
| **brace** | anticipated unavoidable bump — widen/lower/stiffen 1 beat | authored posture | — |
| **back-out** | too close to step over / wedged | `bk` | — |
| **crouch-walk** | pass under an overhang | `cr` looped | — |
| **high-step-up / mount** | climb *onto* a raised surface | `vt` or authored | — |
| **step-down** | controlled descent off a ledge | authored | — |
| **sidestep / strafe** | pass a wide obstacle at its edge; move off a drop-off without turning | **needs authoring** (no lateral gait) | — the big one |
| **pivot** | reorient to a gap / away from hazard | firmware `kang`+IMU (not a sim keyframe) | firmware |

Priority: step-over (refine) → inspect → brace → back-out → crouch-walk →
high-step-up/step-down → sidestep.

### E-4c done (2026-09-08): the fall-hazard test — DECISIVE

Pure drop-off course (`CLIFF_PROB=1`, `CLIFF_PLATFORM_HW=0.18`, obstacles off),
robot marches at a fixed command, `DR_EVAL_FULL`. Switch arm runs `CliffGuard`
on downward "is there floor ahead" probes (`edge_reading()` — more robust than
the env's in-box horizontal `_cliff_scan`), forcing `HALT` before the edge.
`CLIFF_PROB > 0` alone now builds the platform + fall-detection, decoupled from
the `CLIFF` obs flag, so the blind 278-d policy runs unchanged.

**70 episodes / 5 seed offsets, all drop-off:**

| | walked off the edge | fall rate | halted at edge |
|---|---|---|---|
| baseline (blind) | **24/70 (34%)** | 23% | 0 |
| + `CliffGuard` | **0/70 (0%)** | 0% | 31/70 |

The blind gait walks off a drop-off a third of the time; the vision layer never
does. This is the "vision or die" result Phases D / E-4 were missing. Cost: on
the 39 eps it still walked, 0.30 vs 0.35 m forward — the correct trade near a
cliff. GIFs (blind walks off / CliffGuard halts) in the report.

**Watch it:** `G2E_RANDOM_TERRAIN_PROB=0 G2E_RUBBLE_PROB=0 G2E_LEDGE_PROB=0
G2E_CLIFF_PLATFORM_HW=0.18 python eval_skill_switch.py --render --episodes 6
--cliff-prob 1.0 --fwd-cmd 0.14 --max-steps 300` (add `--no-switch` for blind).

### BACK_OUT skill + mixed course (2026-09-08)

**BACK_OUT** (commit `4f17f93`): `GaitMode.BACK_OUT` plays `bk_ref` for a cycle
then auto-releases. `GaitSelector.update(reading, stalled=...)` fires it when the
robot is stalled against something (no forward progress + obstacle in view),
with a cooldown. Harness computes `stalled` from body-x history.

**Mixed course** (obstacles + 40% drop-offs on one course, platform HW 0.28 =
mostly unreached, 70 eps/5 seeds):

| | falls | edge falls | wall-stops | fwd (walked) |
|---|---|---|---|---|
| baseline | 0% | 1/22 | 0 | 0.239 m |
| + switch | 0% | 0/22 | 27 | 0.169 m |

- **Safety fully holds** — 0 falls, 0 edge falls.
- **But forward progress drops ~29%** (0.169 vs 0.239): `HALT` is 40% of ticks,
  27/70 eps wall-stop-dominated. On a course dense with tall obstacles + edges
  the switch halts a lot — and in sim `HALT` = frozen for the episode (no
  turn/nav layer to route around). In the real system a wall-`HALT` hands to
  firmware turning; here it over-penalises forward distance.
- **BACK_OUT is helping**: "STEP_OVER didn't fire" encounters now advance
  0.05–0.07 m (vs 0.012 m in E-3, no back-out).

**Read:** the pieces compose and safety is airtight, but a mixed course is not a
clean forward-progress win *without a turn/nav layer* — `HALT`-forever in sim
reads as a regression it wouldn't be on hardware. Don't over-tune the sim course
to fix this; it's a known sim limitation (turning → firmware).

### Where Phase E stands

Individually: **+48%** through low obstacles (E-3, step-over attributed) and
**0% vs 34%** edge-falls on drop-offs (E-4c) — both with frozen `run20m_ppo`,
0 training. Mixed: safety holds, forward traded down by frequent halting (sim
has no turn layer). Skills built: `STEP_OVER` (trot), `BACK_OUT` (`bk`), `HALT`,
`CAREFUL`; `CliffGuard` `STOP`/`SLOW`. Defined-not-triggered: `INSPECT`.

### >>> RESUME (Phase E) <<<

State: all committed + pushed on `development` through `4f17f93`. Report:
`claude.ai/code/artifact/88ea1a14-ab32-4000-8e87-422264667150`. Nothing running.

Next, in order:
1. **E-5 — INSPECT.** Env change first: a near blind zone in `_scan_terrain`
   (don't report obstacles within ~0.15 m; `tall_flag` unreliable up close)
   *unless* a look-down flag is set. Then `GaitSelector` triggers `INSPECT` on
   "close + unresolved" or after a `BACK_OUT`, and it re-acquires the obstacle /
   picks a step height. `SkillSwitch` already has the `INSPECT` mode (held
   crouch, `cr_ref`).
2. **More skills** (sandbox backlog table above): brace, crouch-walk,
   high-step-up / step-down, sidestep (needs authoring).
3. **E-4b — reward rework** (deferred, training-only): detected-and-cleared ≥
   never-detected; don't punish slowing while an obstacle is in view.
4. When the skill set is frozen → the "design frozen" gate for one
   consolidation ~20M (Tier B). Not before hardware confirms the scripted layer's
   limits (open-loop fragility, blend transients) actually bite.

Key files: `pi_pipeline/gait/skill_switch.py`, `pi_pipeline/vision/gait_selector.py`,
`pi_pipeline/vision/cliff_guard.py`, `rl_training/opencat-gym/eval_skill_switch.py`,
`opencat_gym_env.py` (`_scan_terrain` ~line 1728, `_recolor_scene`, the
`CLIFF_PROB` decouple, `_abs_joint_override` hook).

**Next:**
- **E-5 — INSPECT** (peer-down). Needs a sim change first: a near blind zone in
  `_scan_terrain` (don't report obstacles within ~15 cm / unreliable `tall_flag`
  up close) *unless* a look-down flag is set. Then INSPECT re-acquires
  close/stalled obstacles (the E-3 "STEP_OVER didn't fire → stuck" 23 encounters)
  and enables a graded step-over height.
- Build out the rest of the skill backlog (brace, back-out, crouch-walk,
  high-step-up/step-down, sidestep).
- **E-4b (reward)** deferred — training-only.
- When the skill set is frozen and holds on a mixed hazard+obstacle course →
  that's the "design frozen" gate for one consolidation ~20M (Tier B).

**Longer horizon (user, 2026-09-08):** the real answer to "don't plow into
walls" is *intentional* navigation — always moving toward a chosen destination
along a planned path that routes around large obstacles, so the gait only ever
meets small step-over-able things. That needs turning (firmware) + localisation /
place memory (B11, hard on the Pi) and sits in the behaviour layer above E.
Near-term = E's scripted step-over for the small stuff; goal-nav is the layer on
top, later.

---

### >>> RESUME (Phase D) <<<  *(done — kept for provenance)*
1. `tail -40 rl_training/opencat-gym/trained/ab_vision_results.log`.
2. Ends with `A/B COMPLETE`: read `trained/abD_eval.txt`,
   `abD_vision_obs.json` vs `abD_blind_obs.json`, `abD_*_deca.json`.
   **Read it right (user 2026-09-07):** a vision policy that correctly slows at
   obstacles scores LOWER mean speed on an obstacle course — that is NOT a
   walking regression. So:
   - **Regression check = the decathlon's obstacle-FREE / cruise / commanded
     cells only.** Vision must hold those at >= `abD_blind` (and ~`run20m_ppo`).
   - **Obstacle cells:** compare on traverse-success / cleared-obstacle count /
     fall rate, NOT mean speed/distance. In `eval_obstacle_response.py` read the
     `tall` vs `low` split — slowed/stopped on `tall` = correct; on `low` the
     target is *cleared* (if it backs off `low` obstacles at 20M -> a targeted
     follow-up with `r_obs_clear`, not a fail of the whole idea).
   - Verdict "vision significantly better" = clearly better obstacle-cell
     traverse/clear/fall vs `abD_blind` AND no regression on the obstacle-free
     cells.
   Then write the report + update `docs/project-plan.md` Phase 8 + memory.
3. Mid-run (no final line) + `pgrep -f 'run_ab_vision|train.py'` alive: let it
   finish, re-arm a watcher on `ab_vision_results.log`.
4. Process died mid-train: last `trained/abD_*_console.log` + checkpoint show
   where; re-run `run_ab_vision.sh` or resume the `train.py` with `--from` the
   last `trained/checkpoints/abD_*_<steps>_steps.zip`.
5. `run20m_ppo` untouched -- always the fallback.

### Phase C RESULT (2026-09-07 10:02): STOPPED at the smoke gate.
`phaseC_s1` (finetune from `run20m_graft289`, full stack): goal-reach **0% at
every bearing**, no-goal heading drift **46.2°** (worse than A: 34.7 -> 37.3 ->
46.2), `ep_rew_mean` 9953 -> 2750 (-72%). No 20M.

**Root cause found (the diagnostic that should have run first).** Open-loop, pure
scripted (`action = 0`, `TURN_BLEND` on):

| command | heading change over 250 steps | fwd |
|---|---|---|
| `wkF` (straight) | −0.4° | +0.30 m |
| `wkL` (full left) | **−0.3°** | +0.17 m |
| `wkR` (full right) | **+0.3°** | +0.17 m |

**The scripted OpenCat turn gaits do not turn the robot in this sim/URDF.** They
just slow the forward walk. So all three campaigns failed for the same reason —
there is no motor pattern available (scripted or blended) that produces a turn,
so no reward/curriculum/architecture at the residual layer can learn one.
A *strong hand-built* asymmetry (one side's stride reversed) does yaw the sim
robot ~12°/episode — but forward progress collapses to ~0 (spin-in-place, not
walk-and-turn). Likely cause: real Bittle turning leans on foot-slip + the
firmware gyro turn-assist, which PyBullet's contact model + this URDF don't
reproduce.

**Recommendation (updated — turning is not a reward problem, it's a sim-physics
one):**

1. **Turning goes to firmware, permanently** *(recommended, low risk)*. On
   hardware the scripted `kbk`/`wkL` turn the real robot fine. RL policy =
   straight-line walk + vision-driven slow/brace/step-over + cliff-edge slowing.
   A behavior-layer layer calls firmware turn gaits for heading changes, feeding
   the goal bearing. "Detour + return" becomes: RL walks & slows, behavior layer
   steers via firmware. Matches the original project stance.
2. **From-scratch residual-OFF ~20M** — the policy would have to *discover* the
   progress-killing asymmetry that the sim can yaw with, then balance it against
   forward motion. High cost, high risk (residual-off lost transfer robustness
   before), and if sim turning is unphysical it may not transfer to hardware.
3. **Separate learned turn-in-place sub-skill** — train a small policy for the
   ~12°/episode stationary spin, behavior layer invokes it then hands back to
   the walk policy. Modular, lower risk than (2), but stop-and-turn not smooth.

**Open sub-decision (smaller, after the turning fork):** the vision features that
DON'T need turning — terrain slow/step-over, cliff-edge slowing — are built and
verified. They could go into a narrower fresh 20M (no turn blend, no goal
command) OR stay as behavior-layer slowdown on `run20m_ppo`. The 3× finetune
failures argue against a finetune; a from-scratch run for *just* those may not
be worth an 8-hour run given how modest the effect measured (~neutral in Phase 0).

**Kept (committed, dormant):** `run20m_graft282/285/289`, `TURN_BLEND` +
`wkl_ref`/`wkr_ref`, `GOAL_MODE` (+ polarity), `CLIFF` feature, `G2E_TRAIN_YAW`,
`benchmark_goal.py`, `gate_check.py`, `run_vision_goal_campaign.sh`. Thrown away:
`phaseA_s1/s2`, `phaseC_s1`. `run20m_ppo` untouched.

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
