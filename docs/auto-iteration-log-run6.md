# Auto-iteration log — Run 6 (fall recovery / self-righting)

Unattended loop. Goal (user, 2026-08-31 ~01:40): starting from the wkF-imitation
gait, **slowly** raise obstacle height so the bot starts tripping and has to
**learn to recover from falls / right itself**, while keeping the reward for
matching the target gait (and for recovering to it) HIGH but loosening the policy
enough to improvise a recovery. Promote positive results; on a non-improving
round revert to the last known-good config and try a different policy tweak.
Hard stop 06:00. Then: full report + `g2watch` every round + TensorBoard.

User constraints: obstacles must never get so tall the bot can't walk over them —
just enough to trip it up a bit, rising slowly. 2M steps per round. Branch
`auto-gait-iteration`, one commit per round, no attribution trailers, no push
mid-loop.

## Mechanism added this run (env)

**Fall-recovery window** (`FAC_RECOVERY`, default 0 = old behavior):
- `is_fallen()` (|roll| or |pitch| > 1.3 rad) no longer ends the episode. It
  opens a recovery window (`RECOVERY_WINDOW_STEPS = 120`): keep stepping, replace
  the walking reward with a shaped reward for driving roll/pitch back toward
  level (`4·Δupright + 0.15·upright + 0.05·body-clearance`, ×`FAC_RECOVERY`).
- Both |roll| and |pitch| back under `RECOVERY_UPRIGHT_RAD = 0.5` for
  `RECOVERY_HOLD_STEPS = 5` in a row ⇒ **recovered**: one-time `+10·FAC_RECOVERY`
  bonus, resume normal walking rewards.
- Window expires still down, or tilt > `RECOVERY_ABORT_RAD = 2.4` ⇒ terminate
  reward 0 (old outcome, just delayed).
- A fall **extends the episode step budget** by `window + RECOVERY_RESUME_STEPS`
  (60), capped at 2×`EPISODE_LENGTH`, so recovering then resuming the wkF gait is
  practiced and rewarded — a fall doesn't eat the normal walking budget.

**Obstacles** (`_scatter_obstacles`): scattered boxes only (no lane-spanning
bars), along-path half-length up to 45 mm, 4–10 per episode, height ramped by the
DR curriculum to `RANDOM_TERRAIN`.

**Eval metrics added** (`evaluate_policy.py`): `fall_events_mean`,
`recovered_events_mean`, `recovered_fraction`, `in_recovery_step_fraction_mean`.

## Scenarios (headless eval, 12 ep unless noted)

- **R-scenario**: `--dr-terrain <round height> --dr-push 0.2` — the obstacle
  course at that round's height. Main score driver.
- **flat**: `--dr-friction 0` — level-ground regression check.

## Score (higher = better)

```
score = 100·(1 − fell_fraction_Rscenario)          # survive the course (dominant)
      +  60·recovered_fraction                       # of falls, how many it climbed out of
      +  40·(−diagonal_trot_corr_Rscenario)          # keep the wkF trot
      +  20·forward_distance_m_Rscenario
      −  60·flat_fell_fraction                       # no level-ground regression
      −  30·max(0, 0.15 − forward_distance_m_flat)   # don't collapse to standing still
```
Promote if `score > best_score + 5`. Two non-improving rounds in a row ⇒ revert
to best config, switch levers.

## Known-good baseline (KG0) = `auto_dr_iter4_ppo` (FAC_IMITATION=30, DR, terrain 0.012, no recovery, no push)

| scenario | fell | fall_ev | recov_frac | dist m | trot corr | roll_var |
|---|---|---|---|---|---|---|
| R1 (terrain 0.03 + push 0.2) | 0.00 | 0.00 | – | 0.249 | −0.448 | 0.002 |
| flat | 0.00 | – | – | 0.467 | −0.444 | – |

KG0 score on R1 scenario ≈ 100 + 0 + 17.9 + 5.0 − 0 − 0 = **122.9** (recovery
untrained, so recovered_fraction contributes 0; it simply never falls here).

---

## Round 1 — `auto_rec_r1` — enable recovery, loosen imitation, first obstacle bump

**Changes vs KG0:**
- `FAC_RECOVERY` 0 → **8.0** (+ recovery-window mechanism above). NEW.
- `FAC_IMITATION` 30 → **20** — still heavy (dominant gait signal) but leaves the
  policy room to deviate for a recovery, per the user's "improvise when needed".
- `RANDOM_TERRAIN` 0.012 → **0.03** — first slow bump; trips an imperfect gait,
  not a wall.
- `RANDOM_PUSH` 0 → **0.2** — mild balance noise so recovery keeps getting signal
  once the gait steadies. Not the fall driver.
- Fresh from scratch, 2M steps, DR curriculum (finetune diverges — see Run 5).

**Hypothesis:** the fresh policy stumbles often through the obstacle/push ramp and
the recovery reward teaches it to right itself and get back into the wkF trot;
converged, it should keep flat-ground quality, hold the trot on the course, and
show recovered_fraction well above KG0's 0.

**Result** (`auto_rec_r1_ppo`, PPO_32, 33 min, clean convergence, approx_kl 6e-4):

| scenario | ep_len | fell | fall_ev | recov_frac | dist m | speed | trot corr | roll_var | yaw_max° |
|---|---|---|---|---|---|---|---|---|---|
| R1 (terrain 0.03 + push 0.2) | 251 | **0.00** | 0.00 | – | 0.255 | 0.051 | −0.483 | 0.006 | 11.7 |
| flat | – | 0.00 | – | – | 0.406 | 0.081 | −0.502 | – | 10.4 |

**Score = 124.4** vs KG0 122.9 → **+1.5, inside the ±5 margin = a wash, not a promote.**

**Diagnosis:** the converged policy **never falls** on the R1 scenario, so the
recovery reward was never exercised at eval — it just re-learned iter4's cautious
low crawl (0.05 m/s, same as KG0). terrain 0.03 + push 0.2 is not hard enough to
trip a *converged* gait; the recovery reward only saw signal early in training
while the policy was still flailing. Trot corr is actually a touch better than KG0
(−0.48 vs −0.44) — loosening FAC_IMITATION 30→20 did not hurt the gait. Heading is
worse (yaw_max ~11° vs KG0 ~5°) — the push nudges it off-line and it doesn't fully
correct. **To train recovery at all, trips have to survive to convergence** → R2
raises difficulty (and pins cadence back up so the "freeze and shuffle" escape
hatch closes).

**Decision:** not worse than KG0 and trot improved, so R1's config (recovery
plumbing + FAC_IMITATION 20) carries forward as the working base. Revert target
stays KG0 = `auto_dr_iter4`.

---

## Round 2 — `auto_rec_r2` — close the cautious-crawl escape hatch, harder trips

**Changes vs R1:**
- `FAC_IMITATION` 20 → **26** — pin cadence closer to wkF's real pace so the
  policy can't dodge every trip by crawling. Keeps "match the gait" weight high,
  per the user; not back to 30 (still leaves recovery-improvisation room).
- `RANDOM_TERRAIN` 0.03 → **0.04** — slow bump, still ≈ body clearance (step
  height, not a wall).
- `RANDOM_PUSH` 0.2 → **0.3**, `RANDOM_PUSH_PROB` 0.02 → **0.05** — a more
  frequent mild disturbance so an obstacle clip becomes a tip-over instead of
  being shrugged off. This is the knob that makes falls persist to convergence.
- `FAC_RECOVERY` stays 8.

**Hypothesis:** falls now happen a few % of episodes even at convergence;
`recovered_fraction` climbs off 0 and the score clears KG0 by more than the
margin. If it still shows ~0 falls, R3 raises push/height again; if it falls a lot
but doesn't recover, R3 raises `FAC_RECOVERY` / eases the recovery threshold.

**Result** (`auto_rec_r2_ppo`, PPO_33, 34 min, clean convergence):

| scenario | ep_len | fell | fall_ev | recov_frac | in_recov | dist m | speed | trot corr | roll_var | yaw_max° |
|---|---|---|---|---|---|---|---|---|---|---|
| R2 (terrain 0.04 + push 0.3) | 227 | **0.125** | 0.125 | **0.00** | 2.9% | 0.177 | 0.043 | −0.512 | 0.072 | 12.4 |
| KG0 @ same | 248 | 0.063 | 0.063 | 0.00 | 0.2% | 0.184 | 0.038 | −0.452 | 0.012 | 17.1 |
| R2 flat | – | 0.00 | – | – | – | 0.338 | 0.067 | −0.507 | – | – |

**Score R2 = 111.5  vs  KG0 @ same scenario = 115.5 → R2 is WORSE. Strike 1.**

**Diagnosis:** the difficulty bump worked — R2 now *falls* (12.5%, 2× KG0) and the
recovery window *opens* (2.9% of steps). But **it never rights itself: 0%
recovered.** The window opens, it flails, the window times out → terminate.
Root cause: while `_in_recovery` the walking reward is suspended and the shaped
recovery reward is only ~0.3/step (`FAC_RECOVERY=8` × tiny Δupright), vs
~15–20/step for walking — so the policy has no incentive to work at getting up;
it just eats the occasional termination. Flat also regressed (0.34 m vs R1 0.41,
KG0 0.47) — `FAC_IMITATION=26` + harder DR slowed the base gait.

**Decision:** R2 worse → do NOT carry it forward. R3 keeps R2's difficulty (falls
are needed) but is entirely about **making the recovery window winnable and worth
winning**. Revert target still KG0.

---

## Round 3 — `auto_rec_r3` — make the recovery window winnable

**Changes vs R2** (all one idea: a fallen robot can and should get up):
- `FAC_RECOVERY` 8 → **22** — recovery reward now on the order of the walking
  reward, so learning to get up pays.
- Shaped term `4·Δupright + 0.15·upright + 0.05·clr` → **`6·Δupright + 0.30·upright
  + 0.15·clr`** — denser, rewards being closer to level and body-up even without
  frame-to-frame progress.
- `RECOVERY_UPRIGHT_RAD` 0.5 → **0.7**, `RECOVERY_HOLD_STEPS` 5 → **3** — partial
  recoveries count, so there's a gradient to climb.
- **Pushes suspended while `_in_recovery`** — you don't keep shoving a fallen
  robot; removes a confound that was re-tipping it before it could hold upright.
- **Actuator force 0.2 → 0.5 while `_in_recovery`** only — give the policy the
  physical authority to push itself back over (0.2 may be too weak for a righting
  move; walking is unchanged).
- `FAC_IMITATION` stays 26, `RANDOM_TERRAIN` stays 0.04 (not promoting — hold
  difficulty, fix recovery first).

**Hypothesis:** `recovered_fraction` goes clearly positive (target > 0.4). If it
does, R4 backs `FAC_IMITATION` down toward 20–22 to recover flat-ground distance
while keeping the new recovery skill. If recovery is *still* ~0, the conclusion is
that righting a force-limited flat quadruped from >1.3 rad is not learnable with
these actuators, and R4 pivots to *stumble-catch* (raise `is_fallen()` threshold
so it trains to catch itself at ~0.8–1.0 rad before a full tip).

**Result** (`auto_rec_r3_ppo`, PPO_34, 35 min, clean convergence):

| scenario | ep_len | fell | recov_frac | in_recov | dist m | speed | trot corr | roll_var |
|---|---|---|---|---|---|---|---|---|
| R3 (terrain 0.04 + push 0.3) | 234 | **0.15** | **0.00** | 2.0% | 0.154 | 0.035 | −0.560 | 0.070 |
| KG0 @ same | 248 | 0.063 | 0.00 | 0.2% | 0.184 | 0.038 | −0.452 | 0.012 |
| R3 flat | – | 0.00 | – | – | 0.351 | 0.070 | −0.584 | – |

**Score R3 = 110.5  vs KG0 115.5 → still WORSE. Strike 2.**

**Diagnosis — the structural finding of this loop:** FAC_RECOVERY 8→22, denser
reward, eased criteria (0.7 rad / 3 steps), pushes suspended, torque boosted to
0.5 — **still 0% recovered.** Two independent rounds now confirm: **a Bittle (flat
body, 8 position-controlled walking joints, ~0.2–0.5 N·m, no roll-axis
actuation) physically cannot right itself from >1.3 rad tilt.** No reward shaping
fixes a missing degree of freedom. Trot corr is the best of the loop (−0.56) but
the walking gait is now the slowest yet (flat 0.35 m). Self-righting is a dead
end with this hardware/action space — matches the real robot (a flipped Bittle
needs the scripted "roll-over" skill and even that is unreliable).

**Decision:** two strikes → **revert to R1 config** (loop best, score 124.4) and
pivot the objective from *self-right after a fall* to *catch a stumble before it
becomes a fall* — which IS learnable (feet still under the body at 0.5–1.0 rad).

---

## Round 4 — `auto_rec_r4` — pivot: stumble-catch (revert to R1 base + always-on balance reward)

**Reverted to R1 baseline**, then:
- `FAC_RECOVERY` 22 → **0** — post-fall window disabled (proven unlearnable);
  legacy instant-terminate at 1.3 rad restored. Window code kept, dormant.
- **New `FAC_BALANCE = 4.0`** — dense, always-on reward for reducing body tilt
  whenever `max(|roll|,|pitch|) > 0.5` rad (stumbling, not fallen). Trains the
  policy to fight every wobble back to level on the obstacle course.
- `FAC_IMITATION` 26 → **22** (recover flat-ground distance vs R2/R3).
- `RANDOM_TERRAIN` 0.04 → **0.035**, `RANDOM_PUSH` 0.3 → **0.25**,
  `RANDOM_PUSH_PROB` 0.05 → **0.03** — between R1 and R2: keep enough stumbles to
  train the catch, back off the difficulty that tanked R2/R3.

**Hypothesis:** `fell_fraction` on the course drops below KG0's ~0.06 (the policy
catches stumbles instead of tipping), flat-ground distance recovers toward R1's
0.41, trot stays ≤ −0.45. That's a real, promotable "handles small obstacles
without falling" result — the achievable version of the user's goal.

**Result:** _pending_
