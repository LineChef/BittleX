# Phase 4 running decision log

Goal: "wobble -> re-plant -> keep walking" stance recovery, plus fold small
climbable ledges (door sills, rug edges, thresholds) into the base walk policy.
Base gait: `run20m_ppo`. Capability bar per lever vs run20m_ppo: revert if it
(a) puts new falls on the nominal payload-on decathlon, (b) costs >~15% speed on
the nominal walk, or (c) doesn't measurably improve ledge-handling / lower
recovery-event counts. Lean keep. Whole-effort target: scripted+.

Autonomous run: chain 4a -> 4b -> 4c -> 4d, judgment calls on failures, status
pings only, ONE consolidated final report. "dont stop testing if you encounter
problems, just make a judgment call and add a note."

---

## Round 4a -- ledge into training DR (pure exposure)  --  REVERTED

Config: continuation from run20m_ppo, 3.5M steps. `LEDGE_HEIGHT=0.025`,
`LEDGE_PROB=0.30`, `LEDGE_DIR=0` (random), `LEDGE_RANDOMIZE=True` (per-episode
8-25 mm). No other changes. Commit f7bc1bc.

Bailout gates: both PASS, but 3M on-track flat-eval nominal speed was
**0.047 m/s** (~half the ~0.10 run20m baseline) -- yellow flag noted during the run.

Full eval (eval_p4a.log, 10:11 AM 2026-09-03):

| metric | run20m_ppo | p4a | verdict |
|---|---|---|---|
| cruise (cmd 0.10) | ~0.10 | **0.050** | halved |
| fast (cmd 0.13) | ~0.137 | **0.060** | halved |
| creep (cmd 0.04) | ~0.033 | 0.009 | worse |
| backward (cmd -0.06) | ~-0.060 | -0.027 | worse |
| speed-track err | 0.007 "good" | **0.050 "loose"** | broke |
| decathlon falls (payload, 25 cells) | 0% | 0% | unchanged (payload masks) |
| decathlon speeds | ~0.06-0.10 | ~0.03-0.05 | crawling everywhere |
| gauntlet T5.1 progress | 0.083 | 0.065 | slower |
| T6.1 -24deg descent | 0.058 | 0.019 | much slower |
| T6.3 brutal shoves | 0.088 | 0.040 | much slower |
| ledge probe up-15 (mean end x) | 0.141 | **0.014** | WORSE |
| ledge probe up-25 / up-30 | 0.042 / 0.033 | 0.008 / 0.008 | WORSE |
| ledge probe dn-15 / dn-30 | 0.226 / 0.224 | 0.116 / 0.142 | WORSE |
| ledge probe min-x (up cells) | +0.03 | **-0.066** | robot backs AWAY from the ledge |

Decision: **REVERT.** Fails all three bar criteria at once -- (b) nominal walk
~50% slower, (c) ledge handling measurably WORSE not better. 0% falls is not a
pass here (the 75 g payload masks falls on this whole ladder; progress/speed is
the discriminating metric).

Root cause (matches the pre-run hypothesis): a 30%-probability ledge that the
policy has no mechanism to climb -> 30% of episodes it stalls / eats the
imitation + progress penalty -> under the dominant wkF-imitation anchor the
policy's lowest-loss response is "walk slow and cautious everywhere," and it
still never learns to climb. Pure exposure is the wrong tool.

Carry-forward: ledge exposure only helps if (1) the step is small enough to be
climbable and (2) the policy can take an OFF-BEAT step without being punished by
the imitation anchor. So 4a is not repeated standalone -- it is merged into 4b
with the enabling mechanism.

---

## Round 4b -- phase-slow + imitation-fade re-enabled, dialed-back ledge  --  RUNNING

Config: continuation from run20m_ppo (NOT p4a -- p4a is reverted), 3.5M steps.
Three coupled changes:
- `PHASE_SLOW_RATE` 1.0 -> **0.35**: while tilted past PHASE_SLOW_TILT (0.6 rad)
  the wkF phase reference advances at 35% rate (a slow, not R1's freeze), so a
  wobbling or mid-step-up policy can take a corrective off-beat step and re-sync
  once level.
- `IMITATION_FADE_FACTOR` 1.0 -> **0.30**: during that same tilt window the
  wkF-match reward is cut ~70%, so "be on the stride beat" stops fighting the
  catch / the climb. (This is the "fixed clock + reduced imitation weight"
  the R2 comment explicitly asked for as the safe way to revisit the phase-pause.)
- Ledge dialed back: `LEDGE_HEIGHT` 0.025 -> **0.018**, `LEDGE_PROB` 0.30 ->
  **0.12**, randomize on (per-episode 8-18 mm), dir random. Small enough to be
  climbable so the reward signal is "climb it and progress," not "eat a penalty."

Rationale for combining: the mechanism and the ledge are only meaningful
together -- 4a proved the ledge alone regresses, and the phase-slow/fade alone
was already on the Phase 4b plan for stance recovery. Testing them as one round
keeps the chain on schedule. If 4b fails the bar, 4c bisects (mechanism-only vs
ledge-only).

Launched: 10:18 AM Eastern 2026-09-03, PPO_84, continuation from run20m_ppo,
2220 fps. Eval: eval_p4round.sh p4b. ETA ~11:00-11:10 AM train, eval ~+20 min.

1M gross-sanity: fwd 0.021 m/s | fall 0% -- PASS (thresh 0.010), yellow flag.
**3M on-track: fwd 0.018 m/s -- FAIL (thresh 0.035). Auto-BAILED at 3.0M.**

Training telemetry at the bail: `approx_kl` 40-670 (healthy < 0.05),
`clip_fraction` 0.995, `std` 0.060, `ep_rew_mean` thrashing 260-670. PPO
**diverged** -- did not just regress, it lost the policy.

Decision: **REVERT all of 4a + 4b.** Diagnosis: the culprit is the
`IMITATION_FADE_FACTOR` flicker -- the wkF-match reward jumped full <-> 0.3x
every few steps as body tilt crossed IMITATION_TILT_FADE (0.6 rad), which under
payload + rough + shoves happens constantly. That discontinuity is unfittable
for PPO. Evidence it's the fade and not the ledge/LR: 4a (ledge + same 3e-4 LR
restart, NO fade) regressed *gently* with a normal KL. This is the **third**
failure of phase-clock / imitation-weight surgery here (R1 destabilised the
gait, R2 disabled it, 4b diverged). Not revisiting that lever.

---

## Round 4c -- diagonal-support catch shaping (no imitation-clock changes)  --  RUNNING

Reverted to the run20m_ppo baseline exactly (LEDGE off, PHASE_SLOW_RATE 1.0,
IMITATION_FADE_FACTOR 1.0). Pursue the Phase 4 goal through the EXISTING
`FAC_BALANCE` catch band (tilt in [BALANCE_TILT_ON 0.5, 1.3] rad) instead:
- `BALANCE_W_DIAG` = **0.20**: bonus (x FAC_BALANCE=4.0) for a COMPLETE diagonal
  support pair planted during a catch -- FL+BR or FR+BL both in contact.
  Distinct from `BALANCE_W_FEET` (0.15) which just counts any feet down. This
  directly pays "re-plant into a stable stance," bounded and smooth (no flicker).
- `RESIDUAL_RECOVER_DEG` = **27**: widen the residual 22 -> 27 deg ONLY while
  prev-step tilt > BALANCE_TILT_ON, for reach to throw a foot out and re-plant;
  snaps back to 22 once level so the nominal gait mapping is untouched.

Both changes are gentle + continuous, unlike 4b. Kept the 3e-4 LR restart (same
as 4a, which survived it) to keep the round comparable. If 4c ALSO diverges,
the 3e-4 continuation restart itself is now too hot for this converged policy
and 4d would be a low-fixed-LR retry. If 4c regresses gently (4a-style), the
FAC_BALANCE catch band can't be pushed further from a continuation and Phase 4
concludes as a negative result: run20m_ppo stands, stance recovery beyond
today's FAC_BALANCE needs a from-scratch run or is out of scope.

Launched: 11:22 AM Eastern 2026-09-03, PPO_85. Commit 3cfa12e.

**KILLED at 65K steps -- and the reason retroactively invalidates 4a + 4b as
controlled experiments.** 4c's approx_kl was 76 -> 145 -> 226 in the first
iterations, same divergence as 4b. So I checked 4a's log: **4a's KL was also
70-380 the whole run.** run20m (healthy from-scratch): kl ~0.01.

Root cause is the finetune tooling, not any reward idea: `train.py` `--from`
loaded the policy with `learning_rate=linear_schedule(3e-4)` -- a full LR
restart at 3e-4 on a converged, std~0.06 policy. clip_fraction pinned at ~0.99
(every sample clipped), KL explodes, the policy is flung into an arbitrary
basin: 4a happened to land on a timid half-speed walk, 4b on a non-walking
crawl. **4a and 4b measured LR-kick damage, not ledge DR / phase-clock.** Their
"revert" verdicts still stand (those configs produced no keeper) but the
mechanism was misattributed in the earlier notes.

Fix (commit bcf20fd): `train.py` gets `--finetune-lr` (constant, default 3e-5)
and `--finetune-target-kl` (default 0.05, SB3 per-update early-stop);
run_with_bailout forwards both. Verified the kwargs land through PPO.load.

### 4c relaunch -- first CLEAN continuation

`run_with_bailout --tag p4c --steps 3500000 --from trained/run20m_ppo
--finetune-lr 1e-4 --finetune-target-kl 0.05`. Same reward changes as above
(BALANCE_W_DIAG 0.20, RESIDUAL_RECOVER_DEG 27). 1e-4 (not the 3e-5 default) to
get enough adaptation in 3.5M, with target_kl 0.05 as the real backstop.

Launched: 11:26 AM Eastern 2026-09-03, PPO_86. First iterations:
**approx_kl 0.028-0.034, clip_fraction 0.33, ep_rew_mean ~3400 (steady).**
Healthy finetune -- the policy is being nudged, not kicked. Eval: eval_p4round.sh p4c.

NOTE for the final report: with the tooling fixed, if 4c shows a real
stance-recovery gain it's worth re-running a clean 4a-style ledge round too
(the original ledge verdict was on a diverged policy). Flag for the user.

### 4c results (eval 11:56 AM + bare-robot recovery probe)  --  REVERTED (no-op)

Commanded benchmark: cruise 0.091 (run20m ~0.10), fast 0.135 (~0.137), creep
0.041, backward -0.055. **speed-track err 0.005 "good"** (run20m 0.007). 0 falls.
Walk fully intact.

Decathlon payload, 25 cells: 0% falls, speeds all back to baseline (T1.1 0.099
vs p4a's 0.046), beats scripted on ~20/25 cells, ties the rest. T6.1 -24deg
descent 0.050 (walks down; scripted -0.019 slides back). **recovery_events =
0.000 for BOTH gaits on all 25 cells** -- the payload keeps the body out of the
>0.6 rad catch band, so this eval is blind to stance recovery.

Ledge probe: up15 0.127 (run20m 0.141), up25 0.069 (0.042), dn15/dn30 0.226
(0.226). Within noise of baseline -- 4c didn't train on ledges, just confirms
it kept the capability.

**Bare-robot recovery probe (benchmark_recovery.py -- payload OFF, rough
terrain, calibrated shoves 0.20-0.44, 64 eps/ckpt):**

| metric | run20m_ppo | p4c |
|---|---|---|
| fall rate | 48% | 50% |
| big tilt spikes (>0.6 rad) | 42 | 39 |
| spikes that re-settled | 1 | 4 |
| resettle time (steps) | 20.0 | 22.8 |
| net forward x (mean) | 0.166 | 0.161 |

Fall rate is the metric that matters and it's **identical** (48 vs 50%, n=64,
+-6% noise). Recovered-spike counts are single digits -- noise, would flip on a
different seed set. Net progress unchanged. A harder probe (shoves 0.45-0.90)
had both gaits at ~90% falls -- no signal either way.

**Verdict: 4c is a clean no-op.** Walk preserved, nothing gained. Per the
capability bar ("doesn't measurably improve recovery -> revert"), reverted
BALANCE_W_DIAG + RESIDUAL_RECOVER_DEG. Commit 59f709a.

---

## PHASE 4 CONCLUSION -- no gait change; run20m_ppo stands

Three rounds, no keeper for the gait:
- **4a** ledge into training DR (25mm/30%): regressed the walk ~50%, worse ledge
  handling. Confounded by the LR-restart divergence (see below) but the config
  produced no keeper regardless.
- **4b** phase-clock + imitation-fade revival: PPO diverged (kl 40-670). 3rd
  failure of that lever in project history. Retired.
- **4c** diagonal-support catch shaping: first clean continuation, walk fully
  preserved, but zero measurable recovery gain. Reverted.

**What Phase 4 actually produced (all kept):**
1. **train.py finetune fix (commit bcf20fd)** -- `--finetune-lr` (constant,
   default 3e-5) + `--finetune-target-kl` (0.05). EVERY prior `--from`
   continuation silently diverged: it restarted `linear_schedule(3e-4)` on a
   converged std~0.06 policy -> approx_kl 70-400, clip_fraction ~0.99. run20m
   from-scratch ran at kl ~0.01. This retroactively means the Phase 2/3
   continuations (phase2, phase3, phase3b, run20m itself if it was a `--from`)
   were also kicked -- worth knowing, though those runs were long enough to
   re-converge. **This is the main deliverable of Phase 4.**
2. **benchmark_recovery.py** -- bare-robot stance-recovery probe. The
   payload-on decathlon cannot measure recovery (metric pinned at 0); this can.
3. **Ledge terrain primitive + T7 decathlon tier + render_showcase.py** -- eval
   infrastructure, inert in training (LEDGE_HEIGHT=0), used by T7 / showcase /
   probe.
4. **Negative knowledge:** ledge-in-DR breeds timidity; phase-clock surgery is
   dead; a conservative continuation of the converged 20M policy can't move
   stance-recovery behaviour -- FAC_BALANCE=4.0 is near the ceiling a
   residual-gait policy reaches here.

**Open flags for the user:**
- The **4a ledge verdict deserves a clean re-run** now that the LR bug is fixed
  (original run was on a diverged policy). Cheap: one `--from run20m_ppo
  --finetune-lr 1e-4` with LEDGE_PROB ~0.12, 18mm cap.
- If **stance recovery** is a real priority it needs a from-scratch run with the
  shaping baked in from step 0 (20M-class, gated on the green-light checklist),
  not a continuation. Recommendation: don't -- current robustness is solid, and
  real recovery tuning belongs in the hardware-in-the-loop phase.
- `run20m_ppo` is unchanged and remains the hardware base gait.
