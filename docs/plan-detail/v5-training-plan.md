# V5 training plan (approved 2026-10-09)

The plan for the next fresh 20M gait run, built from an evaluation of V4 (the policy promoted and deployed 2026-10-09), and the automation that runs it unattended.
Times are Eastern. Current state of the run: `python phase_v5.py status` (below); what is deployed: [`../STATUS.md`](../STATUS.md).

## 0. Where to resume (any session)

From `rl_training/opencat-gym/`, RL venv:

| What | Command |
|---|---|
| Where the plan is | `../../.venv/bin/python phase_v5.py status` and `tail trained/phase_v5.log` |
| Start or resume it | `nohup bash ../../tools/v5_watchdog.sh > /dev/null 2>&1 &` (relaunches the runner every 2 min if it died; the runner resumes from `trained/v5_state.json` and never restarts a run that is training) |
| It stopped for a judgement call | the log line says `DECISION NEEDED`; answer with `../../.venv/bin/python phase_v5.py decide SCREEN adopt` (or `reject`), then `rm trained/v5_halt` and start the watchdog again |
| It stopped on a failure | the log line says `HALT`; fix the cause, `rm trained/v5_halt`, start the watchdog again |
| The final report | `trained/v5_report/report.html` once the log says `REPORT ready`: publish it as an Artifact page for the user |

Never put a run's tag text (`v5_control_s42`, `v5_20m`, ...) in a shell command: `run_pipeline.any_training()` greps the process list for it.

## 1. What the V4 evaluation found (2026-10-09 morning)

Measured on Candidate A (`v4_c2` at 1.0M, deployed as V4) with short read-only sims; numbers are falls unless said otherwise.

1. **Bug: the old static caps silently capped the curriculum in every V4 run.** `g2_profile.FULL_COURSE` sets `G2E_CAP_SIDEHILL_DEG` 8, `UPHILL` / `DOWNHILL` 10 and
   `LEDGE_M` 0.02, which override the `frontier` lever's zeros, and the env applied them to frontier episodes too. V4 never trained a side-hill above 8 deg, a slope
   above 10 deg or a ledge above 20 mm; the `slope_floor` run's "10 deg side-hills" were 8 deg; frontier outcomes above the caps were logged under the wrong size.
2. **The side-hill is weak and lopsided, and the benchmark only tested one side.** 10 deg: right side down (T3.2) V3 0.29 / V4 0.26, left side down V3 0.19 / V4 0.49;
   8 deg: V3 0.00 / 0.00, V4 0.03 / 0.09.
3. **Training was harsher than the curriculum intended.** In V4's own training world an episode carried 2.2 hazards on average and about 33% of hazard episodes ended in a
   fall; a big shove (0.6 m/s) landed about every 2 s and a small nudge (up to 0.22 m/s) about 1.6 times a second. 9-10 deg climbs stacked with rubble or hot servos fell
   6 of 8 times while the plain 12 deg uphill benchmark cell falls 10%.
4. **The curriculum's measurements were skewed.** Hazard episodes ran 7.5 s but the hazard-free comparison episodes 3.1 s; a size "passed" at half the hazard-free success
   rate (about 30% absolute); the step-up frontier never got past 9 mm in any run.
5. **Reward shares on a 12.5 s calm walk:** imitation of the scripted walk 78% of the positive reward, speed 21%, forward progress 1.4%, heading 0.5%; the diagonal-trot
   term is effectively zero (a product of two per-step joint deltas). Nothing pays for getting across an obstacle; the speed-tracking penalty punishes slowing down on a hazard.
6. **Symmetry:** on flat ground V4 is more symmetric than V3 (left/right residuals within 0.3 deg, mirror gap 0.029 vs 0.040). The problems are situational (the side-hill
   above; 12 mm step joint asymmetry 11.9 deg vs V3 5.6), checkpoint-to-checkpoint instability (one-sided gaits came and went with the learning rate and the curriculum,
   see [`decisions-log-2026-10-08.md`](decisions-log-2026-10-08.md)), and per-episode heading wander (N1 heading spread 17 deg vs V3 13; 40 s run 66 vs 55).
7. **Heading:** V3 and V4 both trained with the accumulated-heading penalty at 5.0 (the 2026-10-07 "no command drift" decision dropped the extra steering levers, not this
   penalty). Neither policy steers on its yaw input: a fake +-30 deg yaw offset changed the turn rate by less than 0.4 deg/s. So the sim/real steering sign reversal cannot
   currently hurt, and in-policy steering was never really learned.
8. **The benchmark could not see most of this:** T cells are 3.1 s (slope falls happen at 2-5 s), T3.2 tests one direction, T5 mixes up and down steps (the new split shows
   step-ups stall at the edge and step-downs of 20-25 mm fall 60-85% for V4 AND the scripted walk), T5.3 and T11.2 are saturated, and 29 cells at p < 0.05 flag about 1.5
   cells by chance.
9. **Longer hazard episodes helped:** crossing a moderate course end to end went from 22% (V3) to 36-53% (V4 checkpoints). Longer than 7.5 s only helps with a longer course.

## 2. Decisions (user, 2026-10-09)

| Decision | Detail |
|---|---|
| Slopes and tilts in no more than 10% of training episodes | V5: 9.5% (`G2E_FR_SLOPE_SHARE` 0.095), dealt evenly from a shuffled deck: uphill, downhill, left side down, right side down, 25% each |
| No background tilt anywhere | the +-2 deg tilt every non-slope episode had is removed |
| Side-hills trained evenly both ways | left-down and right-down are separate curriculum hazards (`sidehill_l`, `sidehill_r`), so neither can advance on the other's success |
| Slope sizes | ladder tops 10 deg uphill / downhill, 8 deg side-hill |
| Ledge sizes | step-up top 35 mm (the best any policy has cleared is about 30 mm), step-down top 40 mm |
| Gentler shoves | small nudges up to 0.12 m/s about every 4 s; big shoves about every 8 s; no x1.10 hard scaling on either |
| Longer hazard-free comparison episodes | 7.5 s, the same as hazard episodes |
| No steering in the policy | the Pi's front-foot hold steers (proven most effective); screen `heading_blind` approved (the user expects to keep it) |
| Symmetric base walk | parked: too big a change (the scripted walk stays the base) |
| Crossing bonus | yes |
| Baseline for this training | the scripted walk, not V3; V3 and V4 are left out of the report |
| The 20M | not held for V4's hardware walks; the user reports V4 results separately |
| Every variation in equal parts (user, 2026-10-09, before the start) | lever setting `G2E_BALANCED`: shove and nudge directions dealt evenly over 8 compass sectors (nudge magnitudes isotropic), step-up vs step-down, and the mirror image of the overheated-servo set, the servo zero offsets, the IMU roll bias and the payload's sideways offset, each from a shuffled per-env deck, so no side gets more of anything (obstacle fields' sideways placement stays random: many objects per episode average out) |
| Watch the real run | `g2watchrun` shows the training run itself: env 0 streams the episode it is simulating while a viewer is open (`watch_live.py`); the old fresh-simulation viewer is `g2watchsim` |
| Report | plain-language summary sections (verdict, per-hazard result with training level reached and size of change, better / worse / unchanged lists, symmetry) above the full statistics |

Claude's additions inside the approved plan: at most two hazards per episode, size passed at 0.7 of hazard-free success, fewer all-at-once episodes (25% to 15%),
a KL limit through the whole fresh run, and picking the final policy between the last policy and the average of the last three checkpoints.

## 3. What the code does (all default off: older runs and replays are unchanged)

| Lever (`g2_profile.LEVERS`) | Settings | What it does |
|---|---|---|
| `v5_course` | `G2E_FR_SPLIT_SIDE`, `G2E_FR_BOUNDS`, `G2E_FR_IGNORE_CAPS`, `G2E_FR_SLOPE_SHARE`, `G2E_FR_SLOPE_DECK`, `G2E_FR_BACKGROUND_TILT_DEG`, `G2E_FR_MAX_HAZARDS`, `G2E_FR_COMBO`, `G2E_FR_ANCHOR_LONG`, `G2E_FR_PASS`, `G2E_RANDOM_PUSH`, `G2E_RANDOM_PUSH_PROB`, `G2E_IMPULSE_PUSH_PROB`, `G2E_PUSH_NO_HARD_SCALE`, the 0.25 / 0.12 curriculum gates | the course decisions in section 2 |
| (in `v5_course`) `G2E_BALANCED` | | the equal-parts dealing above (`OpenCatGymEnv._deal`); the episode recorder saves the decks so replays stay exact |
| `kl_limit` | `G2E_TARGET_KL` 0.03 | PPO stops an update early when it moves the policy too far, through the whole fresh run |
| `cross_bonus` | `G2E_FAC_CROSS` 200 | one-time reward for getting the body 10 cm past the last object of the field (split over its pieces) and past a ledge edge; positions from the sim, reward only |
| `haz_speed` | `G2E_HAZ_SPEED_RELAX` 0 | no speed-tracking penalty while on a hazard (touched an object or ledge in the last 0.5 s, on a slope of 4 deg or more, or at a ledge edge) |
| `haz_posture` | `G2E_HAZ_POSTURE_RELAX` 0.5 | on a hazard, the imitation and residual-size terms cost half for the same deviation |
| `heading_blind` | `G2E_HEADING_BLIND`, `G2E_PRIV_YAW`, `G2E_FAC_HEADING` 10 | the actor's quaternion has no yaw; the critic gets sin / cos of the heading error; heading penalty doubled (it can only shape a walk with no built-in turn). On the Pi, a policy whose sidecar says `heading_blind` is fed yaw 0 (`residual_policy.heading_blind_for`, `run_gait.py`); `export_onnx.py --heading-blind` writes it |

Benchmark: `benchmark_v4.py` gained cells `SL10` (T3.2's mirror), `SR8` / `SL8` and the ledge split `LU15` / `LD15` / `LU25` / `LD25` / `LU35` / `LD40`.
`benchmark_v5.py` adds the size ladder (each hazard alone at four sizes up to its training top, 7.5 s, "largest size passed" = at most 20% falls at it and every smaller
size, plus crossing rates). `report_v5.py` builds the report against the scripted walk with the Holm correction. Tests: `test_v5.py`, `pi_pipeline/tests/test_residual_scale.py`.

## 4. The plan, as `phase_v5.py run` executes it

| Step | What | Time |
|---|---|---|
| 1 baseline | the scripted walk on benchmark V5 (100 episodes per cell, 40 per ladder size) | about 15 min |
| 2 screens | control (the V5 recipe: `mirror_strong, frontier, cmd_forward, opt_bundle, privileged_critic, lr_half, hazard_long, v5_course, kl_limit`), then `cross_bonus`, `haz_speed`, `haz_posture`, `heading_blind`, each on top of the control; two seeds (42, 43) x 3M each, scored on benchmark V5 (30 episodes, 20 per ladder size) | about 70 min per screen, about 6 h |
| 3 preflight | `preflight.py` on the adopted recipe (tests, wiring, audits, smoke run, replays) | about 15 min |
| 4 the 20M | fresh, adopted recipe, plateau stop on; a tracker line every 1M (calm walk heading / asymmetry / roll / speed, side-hill 8 deg both ways, ladder falls for both side-hills, rubble, step-up, mirror gap) in `trained/v5_20m_curve.jsonl`; stops itself only if G2 falls on flat ground at the 3M / 5M / 10M checks | about 3.5 h |
| 5 pick | the final policy and the average of the last three checkpoints, both scored in full; the one with no flat-ground falls and fewer hazard falls is exported as `trained/V5cand_ppo.onnx` (+ sidecar). Not promoted, not deployed | about 35 min |
| 6 report | `trained/v5_report/report.html` | a minute |

## 5. Screen decision rules (automatic, against the control's two-seed average)

- **Never allowed (a regression):** T1.1 / N1 falls above max(0.05, control + 0.05); N1 path speed under 95% of the control's; any hazard's ladder falls more than 0.10
  above the control's; any listed hazard cell more than 0.15 above.
- **Targets:** `cross_bonus` crossing rate +0.03 with ladder falls no more than +0.02; `haz_speed` / `haz_posture` ladder falls -0.02, or crossing +0.03 with falls no more
  than +0.01; `heading_blind` no cost (ladder falls no more than +0.03, calm-walk heading change no more than 3 deg worse).
- Target met and no regression: **adopted**. Target missed: **rejected**. Target met but a regression: **DECISION NEEDED** (the runner stops). A lever whose run does not
  learn (health stop) is rejected; a control that does not learn, or falls on flat ground, stops the plan.
- Screens are independent (each against the control); the adopted levers are combined in the 20M, and the 20M's own tracker is the check that they work together.

## 6. Win criteria for the final report (V5 against the scripted walk)

1. No falls on flat ground (T1.1, N1, N2, L1).
2. Fewer hazard falls than scripted across all hazard tests, and no hazard test significantly worse (Holm-corrected).
3. Side-hills even both ways: left vs right within 0.10 in fall rate on the ladder and at 8 deg, same largest size passed. **Secondary (user, 2026-10-09: slopes and tilts are scored and shown but are not a primary trait, only some exposure; they sit outside the win count); a slope or tilt result only counts against a policy (screen regression or report) when it falls 0.30 or more above the control / scripted walk.**
4. Calm walk as smooth as scripted and within 3 deg of straight (user 2026-10-09; the scripted heading is biased so it is not the bar) (roll sway within 10%, heading change within 3 deg).

## 7. Open questions noted while building

- **Step-downs of 20-25 mm fall 60-85% for every gait tested, the scripted walk included** (benchmark V5 trial run, 20 episodes). Either a real limit of the blind
  low-clearance trot or a sim geometry artifact; if V5 does not improve on it, look at the step-down geometry before training more on it.
- The size ladder's terrain sizes are severities of the level-1 sizes without the x1.10 hard scaling training applies to rubble and box heights.

## 8. Decision log

| Time | Event | Decision |
|---|---|---|
| 2026-10-09 9:30 AM | V4 evaluation presented (section 1) | the user's decisions in section 2 |
| 2026-10-09 9:45 AM | plan revised for the user's feedback | approved ("the plan is approved, proceed"), with the automation and documentation requirements |
| 2026-10-09 10:20 AM | before the start: user asked for equal parts for every variation, a live view of the actual run, and a bug sweep | built (`G2E_BALANCED`, `watch_live.py`); sweep fixes: two voice tests rephrased for the new local walk command; preflight re-run |
| 2026-10-09 12:08 PM | `cross_bonus` met its target; flagged T2.2 and LU15 regressions | adopted by decision (user agreed: "the risk is acceptable"); the flags were mostly one seed |
| 2026-10-09 2:00 PM | user: slopes and tilts are secondary (scored, not a showstopper, stop only on a large regression) | screens: slope / tilt cells flag only at +0.30 (core hazards keep 0.10-0.15); report: a scored "Secondary" line outside the win count |
| 2026-10-09 2:15 PM | user: cap step-up and step-down at 30 mm so they stay passable if the policy learns (tackle, not avoid); the 35 / 40 mm tops were beyond leg reach at 40 mm (full leg extension plus about 13 deg pitch) | lever `ledge30` for the preflight and the 20M (tops 30 mm), the ladders at quarters of 30 mm, the scripted walk's ledge ladders re-scored once at those sizes (`trained/v5_scripted_ledge40.json` keeps the old); the screens ran with 35 / 40 mm |
| 2026-10-09 2:15 PM | user: `g2watchrun` hung and loaded the Mac | `watch_live.py` now reads the scene twice a second, joins near the end of the stream, and draws the newest frame at most 20 times a second |
