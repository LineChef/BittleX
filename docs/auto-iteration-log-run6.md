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

**Result:** _pending_
