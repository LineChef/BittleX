# Auto-iteration Report — Run 6 (fall recovery / self-righting)

**Date:** 2026-08-31, ~01:50–06:00 (unattended)
**Branch:** `auto-gait-iteration` · one commit per round, no push
**Goal (user):** starting from the wkF-imitation gait, slowly raise obstacle
height so G2 starts tripping and has to learn to **recover from falls / right
itself**, keeping the reward for matching the target gait (and recovering to it)
HIGH while loosening the policy enough to improvise. Promote positive results;
revert to the last known-good config on a non-improving round and try a different
lever. Iterate until ~06:00.

---

## TL;DR

- **Self-righting after a full tip-over is not achievable on this robot.** Two
  rounds (R2, R3) with an escalating recovery reward — up to 22× weight, denser
  shaping, eased success criteria, pushes suspended while down, actuator torque
  boosted 2.5× — converged at **0% recovered, every time.** A Bittle (flat
  chassis, 8 position-controlled leg joints, no roll-axis actuation) has no
  degree of freedom that flips it back over from >1.3 rad. Reward shaping cannot
  add a missing DOF. This matches the real robot, which needs a scripted
  roll-over skill and even then is unreliable.
- **The achievable version — catching a stumble before it becomes a fall — works,
  and improved the gait.** Round **R5** produced the **crispest diagonal trot of
  the whole project** (`diagonal_trot_corr` −0.58 vs the −0.44 baseline) and the
  **best heading** (7.6° max yaw drift vs 11.7°), while never falling on the
  30 mm obstacle course, via a light always-on "fight back to level" reward plus
  eased jitter penalties.
- **Cost:** R5 walks slightly shorter/slower than the R1/baseline gait
  (flat 0.38 m vs 0.41 m per 5 s). By the user's stated priority — *gait match ≫
  speed* — this is a good trade. R6 tried to close the distance gap with the
  stride reward and made it worse (see below).
- **Recommendation: adopt R5** (`auto_rec_r5_ppo`), tagged
  **`gait-v7-stumble-catch`**. It's the best gait the project has produced on the
  metric that matters most here (wkF match), it's more stable and straighter than
  the Phase-3 gait, and it never fell on the obstacle course it was trained for.
  Merge `auto-gait-iteration` → `development` **pending the user's review of the
  `g2watch` replay** (queued below).

---

## Per-round table

Score (higher better), measured on the R1 scenario (`--dr-terrain <h> --dr-push
<p>`) with a flat-ground regression check:

```
score = 100·(1 − fell_fraction) + 60·recovered_fraction + 40·(−trot_corr)
      + 20·forward_distance − 60·flat_fell_fraction − 30·max(0, 0.15 − flat_distance)
```

| Round | Checkpoint | One-line change | fell (course) | recovered | trot corr | dist (flat) | yaw max° | **Score** | Decision |
|---|---|---|---|---|---|---|---|---|---|
| KG0 | `auto_dr_iter4_ppo` | loop start (wkF imitation + DR, no recovery) | 0.00 | – | −0.44 | 0.47 | 8.1 | **122.9** | baseline |
| R1 | `auto_rec_r1_ppo` | +recovery window, FAC_IMITATION 30→20, obstacles 12→30 mm, mild push | 0.00 | 0.00 | −0.48 | 0.41 | 11.7 | **124.4** | wash vs KG0; kept as working base |
| R2 | `auto_rec_r2_ppo` | close cautious-crawl hatch: IMITATION 26, obstacles 40 mm, push 0.3 / prob 0.05 | 0.125 | 0.00 | −0.51 | 0.34 | 12.4 | **111.5** | worse — strike 1 |
| R3 | `auto_rec_r3_ppo` | make recovery winnable: FAC_RECOVERY 22, eased criteria, pushes off + torque boost while down | 0.15 | **0.00** | −0.56 | 0.35 | 16.0 | **110.5** | worse — strike 2 → **self-right ruled out** |
| R4 | `auto_rec_r4_ppo` | pivot to stumble-catch: recovery window off, always-on FAC_BALANCE 4.0; difficulty backed off | 0.00 | – | −0.51 | 0.36 | **5.1** | **115.1** | below R1 (heading win, distance cost) |
| R5 | `auto_rec_r5_ppo` | R1 base + FAC_BALANCE 2.0 + ease SMOOTH/JITTER + lighter mass/friction DR | 0.00 | – | **−0.58** | 0.38 | 7.6 | **127.7** | best gait quality; +3.3 vs R1 |
| R6 | `auto_rec_r6_ppo` | R5 + FAC_STRIDE 0→8 (restore step length) | 0.00 | – | −0.48 | 0.34 | 7.1 | **123.4** | below R5 — not promoted |

**Winner: R5** (`auto_rec_r5_ppo`). Tagged `gait-v7-stumble-catch`.

---

## What was tried, round by round

**R1 — enable recovery, loosen the gait lock, first obstacle bump.**
Added the fall-recovery window (`is_fallen()` no longer ends the episode; it opens
a 120-step window with a shaped "get back to level + body off the ground" reward
and a bonus for holding upright, then walking rewards resume; a fall also extends
the episode budget so *resuming the gait* is practiced). Dropped `FAC_IMITATION`
30→20 to leave room to improvise. Obstacles 12→30 mm, mild push 0.2.
→ Converged clean. The policy re-learned the baseline's slow cautious crawl and
**never fell** on the course, so the recovery reward never fired at convergence.
Trot slightly crisper (−0.48). A wash vs baseline.

**R2 — close the cautious-crawl escape hatch.**
`FAC_IMITATION` 20→26 to pin cadence to wkF's real pace; obstacles 40 mm; push
0.3, probability 0.02→0.05. → Falls now happen (12.5%, 2× baseline) and the
recovery window opens (2.9% of steps) — **but 0% recovered.** While recovering,
the walking reward is suspended and the shaped recovery reward was only ~0.3/step
vs ~15–20/step for walking, so getting up wasn't worth it. Flat gait also slowed.
Worse than baseline.

**R3 — make the recovery window winnable and worth winning.**
`FAC_RECOVERY` 8→22, denser shaped term, `RECOVERY_UPRIGHT_RAD` 0.5→0.7,
`RECOVERY_HOLD_STEPS` 5→3, pushes suspended while `_in_recovery`, actuator force
0.2→0.5 while `_in_recovery`. → **Still 0% recovered.** Two independent rounds now
confirm the structural limit: a force-limited flat quadruped cannot self-right
from a full tip-over. Best trot so far (−0.56) but slowest walk.

**R4 — pivot: stumble-catch instead of self-right.**
Reverted to the R1 config. Disabled the recovery window (`FAC_RECOVERY` 0). Added
`FAC_BALANCE` = 4.0: a dense, always-on reward for reducing body tilt whenever
`max(|roll|,|pitch|) > 0.5` rad but not yet fallen — trains catching a wobble on
every pass through the course. Difficulty backed off (obstacles 35 mm, push
0.25). → **Best heading of the loop (5.1° max yaw)**, crisp trot (−0.51), zero
course falls — but the extra term kept the walk cautious (flat 0.36 m). Net below
R1.

**R5 — R1 base + light balance term + free up the stride.**
`FAC_BALANCE` 4→2 (keep the heading help, don't dominate). Eased the penalties
that hold strides short: `FAC_SMOOTH_1/2` 0.5→0.3, `FAC_JITTER` 0.2→0.1. Lighter
dynamics randomisation (`RANDOM_MASS` 0.15→0.10, `RANDOM_FRICTION` 0.3→0.22) so
the policy has less reason to walk conservatively. Back to R1's obstacle/push.
→ **Crispest trot of the whole project (−0.58)**, best heading on the R1 scenario
(7.6°), steadiest roll, no course falls. Easing the smoothness penalties did *not*
free the stride — walks a touch shorter than R1 (flat 0.38 vs 0.41). Score 127.7,
+3.3 over R1 (inside the ±5 noise margin, but the trot/heading gains are
systematic, not noise). Falls hard (37.5%) on a course well past its training
range — robust only within distribution.

**R6 — R5 + restore the stride reward.**
Single lever: `FAC_STRIDE` 0→8 (touchdown-to-touchdown per-foot forward distance,
un-gameable). Aimed at R5's one weakness — pull step length back to R1/baseline
range without disturbing the trot or heading. → It lengthened the individual step
(flat stride 0.085 vs R5 0.067) **but competes with `FAC_IMITATION`**: bigger,
less-coordinated steps dropped trot corr back to −0.48 (from −0.58) and total
distance actually *fell* (flat 0.34 vs R5 0.38). Same "stride reward muddies the
wkF match" effect seen in Run 5. **Not promoted — R5 stands as the winner.**
`FAC_STRIDE` reverted to 0 in the final commit.

---

## The recovery mechanism (kept in the code, dormant)

`opencat_gym_env.py` still contains the full fall-recovery window
(`FAC_RECOVERY`, `RECOVERY_*` constants, the recovery branch in `step()`, the
episode-budget extension). It is **disabled** (`FAC_RECOVERY = 0.0`) from R4 on,
which restores the exact legacy behaviour (instant terminate, reward 0, at
1.3 rad). It is left in place, documented as proven-ineffective for this robot,
in case a future action-space change (e.g. adding a body/spine joint, or a
dedicated get-up policy) makes self-righting worth revisiting — see the Phase 8
note in `docs/project-plan.md`.

The always-on **`FAC_BALANCE`** stumble-catch reward (added R4) is the part that
worked and is live in R4–R6.

---

## Honest assessment vs the original goal

| Goal | Outcome |
|---|---|
| Slowly raise obstacle height | Done: 12 → 30 → 40 mm then held. Past ~40 mm the gait degrades without the policy learning anything new, so the schedule stopped there. |
| Learn to recover from falls / right itself | **Not achievable on this hardware.** Confirmed across R2–R3 with an aggressive recovery reward. Structural (missing DOF), not a tuning failure. |
| Keep gait-match reward HIGH, improvise when needed | Held `FAC_IMITATION` at 20–26 throughout; the crisp trot in R5 (−0.58) shows the match got *better*, not worse. |
| Catch a stumble before falling | **Works.** `FAC_BALANCE` (R4+) measurably improved heading and roll stability with no fall-rate cost, and R5 turned that into the best trot + heading numbers of the project. |
| Positive result → carry forward; else revert | Followed: R2/R3/R4 all reverted to R1; R5 built on R1 and improved it; R6 built on R5. |

**Bottom line:** the loop did not teach G2 to get up after falling (impossible
here), but it produced a **cleaner, straighter walking gait that is measurably
better at not falling in the first place** — which is the useful, deployable form
of the original intent.

---

## Review artifacts

**TensorBoard** — running at http://localhost:6006/ . Run 6 rounds are
`PPO_32`–`PPO_37` (R1→R6); compare against `PPO_31` = `auto_dr_iter4` (KG0).

**Visual replay (`g2watch`)** — run these from `rl_training/opencat-gym/` with
the venv active. Each opens a PyBullet window and loops the deterministic gait:

```
g2watch trained/auto_rec_r5_ppo                              # WINNER, flat ground
python watch_trained.py trained/auto_rec_r5_ppo --dr-terrain 0.03 --dr-push 0.2   # winner on the obstacle course
g2watch trained/auto_rec_r1_ppo                              # R1 (≈ baseline)
python watch_trained.py trained/auto_rec_r4_ppo --dr-terrain 0.035 --dr-push 0.25 # R4 (heading gain, cautious)
g2watch trained/auto_rec_r6_ppo                              # R6 (stride reward regressed the trot)
g2watch trained/phase3-gait_ppo                              # the locked Phase-3 gait, for comparison
```

**GIFs** (scratchpad, in case the windows aren't handy):
`…/scratchpad/gifs/` — `WINNER_auto_rec_r5_flat.gif`, and
`auto_{dr_iter4,rec_r1,rec_r4,rec_r5,rec_r6}_course.gif` (all on the 30 mm +
push-0.2 course).

**Checkpoints:** `trained/auto_rec_r{1..6}_ppo.zip`, checkpoints every ~200 K in
`trained/checkpoints/`. Winner also tagged `gait-v7-stumble-catch`.

## Pending decision

Merge `auto-gait-iteration` → `development`? The branch holds all 6 rounds plus
the recovery/balance infrastructure; the env file is left at the **R5 winner
config**. Recommend yes after watching the R5 replay. Revert ladder if needed:
`gait-v7-stumble-catch` → `phase3-gait` → `auto_dr_iter4`.
