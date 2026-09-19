# Gait-friction campaign log

Queued to run immediately after the resid30 campaign's Stage 3 benchmark
report is generated (`docs/rl/resid30-log.md`), same branch
(`auto-gait-iteration`), same automated-testing-loop.md methodology.

**Reprioritized 2026-09-18:** the primary target is now friction in
*normal, everyday walking* (flat ground, ordinary cruise speeds) — not just
the extreme creep-speed case. The creep-band fix below is still worth
doing, but as a secondary, lower-effort piece, not the main event.

## Context

Investigating why the residual policy spends a meaningful share of its
degree budget even on flat, undisturbed ground (found while building the
action-trace visualization for the resid30 side-question): **mean residual
usage sits around 7-8 degrees out of the 22-30 degree budget continuously,
even in calm cruise-speed walking**, not concentrated in disturbance
moments. The reward-term breakdown shows why: fine-grained terms (balance,
height, clearance, joint-limit) all sit at ~0 during normal walking, while
`r_imitation` and the speed-tracking terms (`r_speed`/`r_speed_track`)
dominate. The residual's main day-to-day job is reconciling "match the
`wkF` reference closely" against "hit the commanded speed" — not standing
by for emergencies.

Measured the *pure open-loop scripted gait* (`wkF`, action forced to 0)
against its commanded speed across the full command range:

| Command | Actual speed | Error |
|---|---|---|
| 0.02 m/s (creep-low) | 0.001 m/s | -93% |
| 0.04 m/s (creep-mid) | 0.040 m/s | 0% |
| 0.10 m/s (cruise, the phase-rate calibration point) | 0.095 m/s | -4.6% |
| 0.115 m/s (fast-low) | 0.109 m/s | -5.0% |
| 0.15 m/s (fast-high, max) | 0.139 m/s | -7.5% |

**The shared root cause, relevant to both the creep case and the general
case:** `wkF`'s phase-rate scaling (`PHASE_RATE_NOM_CMD`,
`PHASE_RATE_MIN`/`MAX` in `opencat_gym_env.py`) only changes *cadence*
(steps per second) — it never changes *stride length*. The scripted
reference matches the commanded speed closely only at exactly its one
calibration point (0.10 m/s); at every other commanded speed, even within
the ordinary "cruise" sampling band (`0.08-0.12`, not pinned to exactly
0.10), there's a real gap between what the reference alone would produce
and what's asked for — the residual has to cover that gap continuously,
which is the likely explanation for the ~7-8 degree baseline usage at
cruise speeds, not just the much larger creep-band gap. Confirmed two
speed-reward terms (`FAC_SPEED`/`r_speed`, `FAC_SPEED_TRACK`/`r_speed_track`)
both track the *actual sampled command* (`self._cmd_fwd`), not a separate
fixed target — so this is not a reward-contradiction bug, it's a real
mechanical gap between what gets commanded and what the scripted reference
alone can physically execute at any speed away from its one calibration
point.

## Approach

### Primary: scale stride amplitude with commanded speed, not just cadence

**Hypothesis:** if the scripted reference's per-joint amplitude (not just
its phase-advance rate) scales with `_cmd_fwd`, the reference itself would
track the commanded speed much more closely across the *whole* range
(cruise and fast included, not just creep), reducing how much the residual
has to continuously compensate during ordinary walking — the actual target
of this reprioritization.

Concretely: `_ref_pose(phase)` currently returns a pure keyframe lookup,
independent of `_cmd_fwd`. The fix would scale the reference's deviation
from a neutral/rest pose by a factor derived from `_cmd_fwd /
PHASE_RATE_NOM_CMD` (the same ratio already used for phase-rate scaling),
so a slower command produces a *smaller-amplitude* gait cycle, not just a
slower-cadence one, and a faster command produces a larger-amplitude one.

**This is a bigger, more structural change than the creep-band fix** — it
touches how the reference itself is generated, not just what commands get
sampled during training. Real open questions before committing to a
specific implementation:
- What's the right "neutral pose" to scale around (standing pose? per-joint
  mean over the gait cycle?) — a bad choice could produce an unnatural or
  unstable-looking gait at the amplitude extremes.
- How this interacts with `FAC_IMITATION` — the imitation reward compares
  against the *unscaled* reference today; if the reference itself starts
  moving (scaling with command), the imitation target needs to move with
  it, which changes what "matching wkF" even means at a non-nominal speed.
  Likely needs retuning alongside this change, not independently.
- Whether amplitude scaling should be linear in the speed ratio or
  something gentler (e.g. sqrt) — needs a quick sweep, not a guess.

**Direct success metric, not just aggregate reward:** does mean residual
usage at cruise speeds (measured via `action_trace.py`-style traces, pinned
commands across the speed range) actually drop after the fix, compared to
today's ~7-8 degree baseline — not just "did fall rate stay flat," since
this change is about reducing unnecessary correction, not about survival.

### Secondary: narrow the creep sampling band

Lower-effort, lower-risk complementary fix for the specific extreme-low-speed
case, kept from the original plan: change `_sample_command()`'s creep band
from `np.random.uniform(0.02, 0.055)` to approximately `np.random.uniform(0.04,
0.055)` — training on commands the scripted base can realistically execute
via phase-rate scaling alone, rather than ones with a built-in ~90%+
open-loop failure. Doesn't address the general cruise-speed friction (the
primary target above), but cleanly worth doing regardless since it's cheap
and the creep-band mismatch is real on its own terms.

Still rejected: lowering `PHASE_RATE_MIN` itself as a standalone fix — same
concern as before (touches core gait timing for every speed band, risks
foot-phase/contact-timing interactions). The amplitude-scaling approach
above is a more complete answer to the same underlying limitation.

## Testing plan

1. **Baseline measurement** (done above) — pure open-loop speed-tracking
   error across the command range, and the 7-8 degree cruise-speed residual
   baseline from the action-trace work.
2. **Primary change**: implement amplitude scaling on the reference pose,
   tied to `_cmd_fwd / PHASE_RATE_NOM_CMD`. Retune `FAC_IMITATION` alongside
   it if the crawl-regression signature (from the resid30 campaign)
   reappears — expect this may need its own short sub-round to land.
3. **Secondary change**: narrow the creep band (independent, can go in the
   same or a separate round — low interaction risk with the amplitude
   change).
4. **Short diagnostic round(s)**, 2-3M steps each, fresh run off whichever
   recipe wins the resid30 campaign — matching `automated-testing-loop.md`'s
   standard round size.
5. **Evaluate**: `evaluate_policy.py` fall/speed metrics, plus
   `action_trace.py` runs pinned across the full speed range (creep,
   cruise, fast), comparing mean residual usage before vs. after — cruise-speed
   reduction is the primary pass/fail signal, creep-band reduction is
   secondary confirmation.
6. **Decision gate**: promote if cruise-speed residual usage drops
   meaningfully without regressing fall rate, speed tracking, or the
   imitation-match quality; revert after two non-improving rounds, per
   standard loop discipline.
7. Log each round here, one entry per round, same format as
   `resid30-log.md`.

## Rounds

### Round 1 — gaitfriction_r1

- **Started:** 2026-09-18, 3M steps, PID 73506. Base: `run20m_resid30_ppo`'s
  recipe (30deg ceiling, `FAC_IMITATION=16`, `FAC_RESIDUAL_COST=2.8`,
  `FAC_RESID_SMOOTH=8.2`), promoted to the frozen base same day -- see
  `docs/rl/resid30-log.md`'s promotion entry. Fresh run, not a continuation.
- **Changes this round:**
  - **Primary:** `_ref_pose` now amplitude-scales the reference pose's swing
    around `STAND_POSE` by `clip(cmd_fwd / PHASE_RATE_NOM_CMD, AMP_SCALE_MIN,
    AMP_SCALE_MAX)` (new constants, `0.35`/`1.60` -- reusing the exact ratio
    and clip range `PHASE_RATE_*` already uses, as the round-1 hypothesis
    rather than a new guess). At `cmd_fwd == PHASE_RATE_NOM_CMD` (0.10) this
    is a no-op -- identical to today's fixed reference. Both the residual's
    joint target and the imitation-reward target read the same scaled
    `_ref_pose`, so "matching wkF" now means matching the speed-scaled
    reference, not the fixed one -- consistent with the hypothesis, not an
    oversight.
  - **Secondary:** creep command band narrowed `uniform(0.02, 0.055)` ->
    `uniform(0.04, 0.055)`. Below ~0.035 the ratio to `PHASE_RATE_NOM_CMD` is
    under the 0.35 floor for *both* `PHASE_RATE_MIN` and the new
    `AMP_SCALE_MIN`, so those commands keep a built-in ~90%+ open-loop
    mismatch no reference scaling can close regardless -- confirmed this
    doesn't overlap with what the primary fix already covers before doing
    both in the same round.
- **Smoke test:** passed clean (20k steps, `ep_rew_mean` ~715, no
  NaN/crash) before launch.
- **What to check at completion:** mean residual usage at cruise speeds
  (`action_trace.py`, pinned commands across creep/cruise/fast) vs the
  ~7-8deg baseline this campaign is trying to reduce; fall rate and
  `r_imitation` match quality shouldn't regress; watch for the
  crawl-regression signature (from the resid30 campaign) in case
  `FAC_IMITATION=16` needs to move now that the imitation target itself is
  moving with command, not just cadence.

### Result: clear regression, not the anticipated failure mode

- **Completed:** 2026-09-18, 3,014,656 steps, `approx_kl` settled near 0
  (0.00016), `ep_rew_mean` ~2260. Checkpoint: `trained/gaitfriction_r1_ppo.zip`.
- Built a dedicated pinned-command speed sweep (`gaitfriction_speed_sweep.py`,
  since `action_trace.py` doesn't pin commands) -- flat, calm ground, no
  disturbance, matching this campaign's actual reprioritized target.
- **Residual usage roughly doubled at every band, not reduced:**

  | Band | Baseline RMS | r1 RMS | Baseline speed err | r1 speed err |
  |---|---|---|---|---|
  | creep | 3.69deg | 10.85deg | -0.024 | -0.039 |
  | cruise | 4.98deg | 9.69deg | -0.010 | -0.045 |
  | fast | 5.47deg | 9.25deg | +0.013 | -0.017 (+1 fall) |

  Speed tracking got worse everywhere too, and a fall appeared at the top
  of the fast band that wasn't there before. Visual replay (leg-tinting
  GIFs, published: `https://claude.ai/artifact/NkTMcBhwfJYATn4TsmQb37`)
  confirms it isn't subtle -- visibly heavier tint (more residual
  correction) at both creep and cruise.
- **Diagnostic before deciding the fix:** checked `r_imitation` directly
  (pinned probe at cmd 0.04/0.10/0.13, both checkpoints) rather than assume
  the plan's anticipated failure mode. Result: **not collapsed** -- 13.9-14.2
  (r1) vs 15.2-15.7 (baseline), a real but modest ~9-10% dip, nowhere near
  the crawl-regression signature (`r_imitation` cratering) the decision gate
  was written to catch. That rules out "reference target too hard to hit"
  as the primary story.
- **Actual pattern:** imitation match stays reasonable, but residual usage
  nearly doubles *and* speed-tracking gets worse, **including at cmd=0.10**
  -- the literal calibration point where the amplitude-scaling formula is a
  no-op (`amp = clip(0.10/0.10, ...) = 1.0`, `ref_pose = ref` exactly). If
  the only problem were "the target moved and needs a stronger imitation
  pull," the no-op point should have been unaffected. It wasn't -- worse
  there too. Reads as: training across the *whole* command range against a
  continuously-reshaping reference produced a worse shared policy
  everywhere, not a localized reward-imbalance at the extremes.
- **Decision: round 2 diverges from the plan's pre-committed fix.** The plan
  said "adjust `FAC_IMITATION` upward" on a crawl-regression signature --
  that signature isn't present, so that fix doesn't match the diagnosis.
  Instead, narrowed `AMP_SCALE_MIN`/`AMP_SCALE_MAX` from `0.35`/`1.60`
  (matching `PHASE_RATE`'s clip, the round-1 default) to `0.70`/`1.30` --
  testing the diagnosis directly (the reference was moving too far/too
  aggressively across the command range) rather than guessing at reward
  weights the data doesn't implicate. `FAC_IMITATION` left at `16`
  (unchanged) since it isn't the bottleneck the data points to.
- **Launched:** `gaitfriction_r2`, 3M steps, PID 77201, fresh run (not a
  continuation), smoke-tested clean first. This is round 2 of the loop's
  "revert after two non-improving rounds" budget -- if this doesn't clear
  the same speed-sweep bar, the amplitude-scaling approach reverts entirely
  (keeping the independent, low-risk creep-band-narrowing secondary fix)
  and this campaign's primary hypothesis gets logged as a documented
  negative result, same standard as Phase 4a's ledge finding.

## Alternative levers, in case amplitude scaling doesn't pan out

Discussed four options for reducing cruise-speed friction without touching
amplitude scaling. User approved testing #1 and #2, explicitly not #3/#4.

**#1 (cadence-curve recalibration) investigated and downgraded before
building anything.** Hypothesis: fit `_prate` to the campaign's own
open-loop speed-tracking-error measurement instead of the current straight
`PHASE_RATE_NOM_CMD` ratio. Re-measured that curve fresh, at finer
resolution, before trusting the old 5-point table -- and found it doesn't
hold up as a fixed-curve target:
- Clean conditions (no DR): non-monotonic, undershoots 20-30% in the
  0.04-0.08 range, *overshoots* 5-18% above cmd=0.10 -- contradicts the old
  table's "undershoot everywhere" shape.
- Full DR (terrain+push+friction+payload all on): undershoots 30-106%
  across the board, much larger than the old table's -4.6% to -7.5%.
- **Calm-ground DR only (friction/mass/payload on, terrain/push off --
  the actual condition this campaign means by "calm"):** undershoots
  22-79%, but critically, **with real per-episode variance** (std growing
  to 0.055 m/s at cmd=0.13, large relative to the ~0.10 m/s mean) --
  confirmed via 10-episode samples, not noise from a small n.

  The variance is the finding that matters: the open-loop gap isn't a
  fixed function of command alone, it depends on this episode's randomly
  drawn friction/mass/payload, which a static command-only correction
  curve has no way to know. A real chunk of "friction" may be the residual
  doing genuinely necessary closed-loop compensation for randomized
  per-episode conditions -- unfixable by ANY static reference-shape change,
  amplitude-based (already failed) or cadence-based (this option) alike.
  **Downgraded to a secondary/minor tweak at most, not pursued as the
  primary fix** -- reported to the user before writing any code, not
  discovered after burning a training round on it.

**#2 (calm-ground residual-cost bonus) is the primary fix going forward.**
Built and smoke-tested. User raised a real concern before approving: could
extra cost during "calm" episodes make the gait slower to react when it
stumbles? Valid -- the naive version (a per-episode "was disturbance
forced" flag) would have punished the residual for reacting to an *organic*
stumble in an episode nominally labeled calm, since the flag doesn't update
mid-episode. A hard per-step threshold would have avoided that specific
problem but risked a different, already-documented one: Phase 4b's PPO
divergence (`approx_kl` 40-670, reward flickering full<->0.3x as tilt
crossed `IMITATION_TILT_FADE`). Correction (caught on a later re-read, not
by the user at the time): that divergence is real but was measured on a
*confounded* change -- `PHASE_SLOW_RATE`'s own comment on the same event
says it was tried "paired with an imitation-weight fade," i.e. Phase 4b
changed `PHASE_SLOW_RATE` (re-enabling the phase-clock slowdown) *and*
`IMITATION_FADE_FACTOR` (dropping it to 0.30) at the same time. It isn't
cleanly established that `IMITATION_FADE_FACTOR`'s hard threshold alone,
isolated, would cause the same divergence -- only that the combination
did. The design choice (a continuous ramp, not a hard threshold) stands on
its own merits regardless -- a smooth function has no discontinuous jump
to flicker across, full stop -- but the citation overstated how cleanly
that specific history proves hard thresholds on this signal are
dangerous in isolation.

**Implementation:** new `FAC_RESID_CALM_BONUS` (default `0.0`, off),
added to `residual_cost` in the reward function, scaled by a *continuous*
`calm_factor = max(0, 1 - tilt/IMITATION_TILT_FADE)` -- full extra weight
at tilt=0, smoothly ramping to zero extra weight by the same
`IMITATION_TILT_FADE=0.6` rad threshold the existing stumble-fade gate
already uses, then staying at zero beyond it. Reacts in real time to any
destabilization, scripted or organic, with no flicker risk since it's a
ramp, not a switch. Smoke-tested at `FAC_RESID_CALM_BONUS=5.0` -- runs
clean, finite rewards, cost tracks tilt as expected.

**`gaitfriction_r2` result: still a regression, amplitude scaling reverted
entirely.** Completed 2026-09-18, 3,014,656 steps, converged clean. Same
pinned speed-sweep evaluation as round 1:

| Band | Baseline RMS | r2 RMS | Baseline speed err | r2 speed err |
|---|---|---|---|---|
| creep | 3.85deg | 7.45deg | -0.016 | -0.031 |
| cruise | 4.98deg | 7.18deg | -0.010 | -0.024 |
| fast | 5.41deg | 7.52deg | +0.006 | -0.003 (+1 fall) |

Narrowing the clip range (0.35/1.60 -> 0.70/1.30) roughly halved the size
of the round-1 regression (was ~2x baseline, now ~1.5x) but didn't come
close to clearing the bar, and the fall at high speed persisted. Two
non-improving rounds -- per the loop's own discipline, reverted the
amplitude-scaling approach entirely: `_ref_pose` back to the original
unscaled form (docstring updated with the full negative result and a
pointer to this log), `AMP_SCALE_MIN`/`AMP_SCALE_MAX` removed. The
creep-band narrowing (secondary fix) is kept -- independent of amplitude
scaling, justified on its own via the directly-confirmed open-loop
mismatch below ~0.035 ratio, not touched by this revert.

**`gaitfriction_r3` result: also a regression, and a counterintuitive one.**
Completed 2026-09-18, 3,014,656 steps, converged (`approx_kl` ~0.001, no
instability). Speed-sweep result:

| Band | Baseline RMS | r3 RMS | Baseline speed err | r3 speed err |
|---|---|---|---|---|
| creep | 4.08deg | 6.83deg | -0.008 | -0.012 |
| cruise | 4.99deg | 7.85deg | -0.014 | -0.019 |
| fast | 5.18deg | 8.47deg | -0.015 | -0.029 (+1 fall) |

Residual usage went **up**, not down, despite the extra cost specifically
penalizing it -- the counterintuitive direction. Checked reward-hacking
directly before concluding anything (did the policy learn to avoid the
"calm" classification itself, e.g. by staying more dynamic/wobbly, rather
than genuinely using less residual): tilt-probed both checkpoints, 6
episodes, 180 steps. Result: **both spend ~100% of normal walking time well
under the 0.6 rad `IMITATION_TILT_FADE` threshold** (mean tilt 6-7deg,
nowhere near it) -- ruling that out. The real explanation: at typical
walking tilt, `calm_factor` is essentially always ~1.0 for both checkpoints
regardless of the gate design, so this round was closer to testing a flat
~2x `FAC_RESIDUAL_COST` bump (2.8 -> ~5.8) than a genuinely calm-conditioned
effect -- the gate's dynamic range doesn't actually engage during ordinary
locomotion, only near-fall. That a bigger direct residual-cost penalty
produced *more* residual usage, not less, is the real (if strange) finding
here -- not a bug in the gating logic.

**`gaitfriction_r4` launched** (`FAC_RESID_CALM_BONUS=1.0`, much gentler)
-- PID 82721, fresh run, smoke-tested clean. Round 2 of this specific
lever's two-round budget: testing whether round 1's value (3.0) simply
overshot into a regime that destabilizes the existing reward balance,
before concluding the whole approach doesn't help.

**`gaitfriction_r4` called early and cancelled (2026-09-18).** Rather than
run all 3M steps, evaluated the 600k-step checkpoint (~20% through, not
converged) with the same speed sweep: residual RMS already elevated
(5.97-8.88deg vs baseline's ~4-5deg) with a rough fall pattern (1-3 falls
per band at only 4 episodes each) -- the same directional signature every
prior round converged to, visible well before completion. Combined with
the mechanistic explanation already established for round 3 (`FAC_SPEED_TRACK`
at 60.0 dominates `FAC_RESIDUAL_COST` by ~15-20x regardless of the calm-
bonus's magnitude, so the residual's "necessary work" doesn't stop being
necessary just because it costs more -- a gentler value doesn't change
that structural relationship), this was called as a likely repeat without
running to completion. Training killed (PID 82721), no lingering process.

**Conclusion: `FAC_RESID_CALM_BONUS` reverted to 0.0, option 2 abandoned.**
Two independently-reasoned reward/reference interventions (amplitude
scaling, twice; residual-cost calm-bonus, twice -- one confirmed, one
called early on strong partial evidence) have now all regressed in the
same direction. `run20m_resid30_ppo`'s existing ~4-5deg cruise-speed
residual usage looks like a real, load-bearing part of how this recipe
currently reconciles imitation-match against speed-tracking, not
frivolous waste removable by discouraging it after the fact. Moving to
option 1 (cadence recalibration) next -- the one remaining approach that
targets the actual open-loop mechanical gap directly instead of trying to
change the residual's incentives around a gap that's still there either
way.

## Option 1: cadence recalibration (`gaitfriction_r5`)

Re-measured the open-loop (action=0) speed-tracking curve cleanly before
building anything -- n=16/point (vs the earlier 4-6 point samples, which
had real non-monotonic noise), calm-ground DR (friction/mass/payload on,
terrain/push off):

| cmd | 0.03 | 0.04 | 0.05 | 0.06 | 0.07 | 0.08 | 0.09 | 0.10 | 0.11 | 0.115 | 0.125 | 0.13 | 0.14 | 0.15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| actual | .023 | .028 | .032 | .036 | .043 | .045 | .053 | .055 | .056 | .058 | .062 | .062 | .069 | .072 |

Monotonic this time -- the earlier "overshoot at high commands" finding
was small-sample noise, not real. Undershoot grows from ~23% at cmd=0.03
to a plateau around 50% by cmd=0.11 -- **worked out what a full
correction would require: phase rate up to ~3x nominal at cmd=0.15**, an
unreasonable stepping frequency, likely producing a visibly degenerate
gait rather than a fixed one. Same underlying wall amplitude scaling hit,
from a different angle: the fixed-amplitude reference has a real physical
ceiling on ground coverage per unit time that cadence alone can't push
past.

**Implementation: a capped, honest partial correction**, not a full fix --
`PHASE_RATE_MAX` raised `1.60 -> 2.00` (a bounded increase, not the ~3x
full correction would need), plus a new `PHASE_RATE_CORRECTION_CMD`/
`_FACTOR` lookup (measured cmd -> needed rate multiplier, `np.interp`'d)
applied to `_prate` before the existing clip. Captures the real,
achievable correction in creep/low-cruise fully, saturates (partial
benefit only) above ~cmd=0.10 where the physical ceiling bites.

**Verified before committing to a training round** (the same open-loop
measurement, now with the correction active): real improvement across the
whole range, not just the intended low end -- cmd=0.07 nearly closed
(-38.8% -> -5.7%), cmd=0.10 substantially better (-44.6% -> -18.3%), even
the saturated top end improved (cmd=0.13: -52.1% -> -30.8%). This is a
pre-training sanity check on the open-loop mechanism itself, not a
training result -- confirms the correction does what it was designed to
do before spending compute on whether the *trained* policy's residual
usage actually drops.

**`gaitfriction_r5` launched** -- PID 83776, fresh run, smoke-tested
clean. First round of this approach; same two-round budget as every other
lever this campaign.

### `gaitfriction_r5` result: also a regression -- and a real eval bug caught first

Completed 2026-09-18, 3,014,656 steps, converged (`approx_kl` ~0.0002).
First evaluation run showed something suspicious: the *baseline*
(`run20m_resid30_ppo`, unchanged) suddenly read very differently than
every prior measurement of it (speed_err +0.047 to +0.055 at cruise,
vs the consistent -0.010 to -0.018 seen in every earlier round's eval).
Root cause found before trusting anything: the phase-rate correction
built for this round is applied unconditionally in the environment code,
regardless of which checkpoint is loaded -- so `run20m_resid30_ppo`
(trained under the *old*, uncorrected mapping) was being evaluated
through the *new* corrected mapping, a reference it never trained
against. Same category of bug as the `RESIDUAL_SCALE_DEG` per-checkpoint
trap caught earlier in the resid30 campaign. Fixed with the same pattern:
new `PHASE_RATE_CORRECTION_ENABLED` module flag (default `True`), set
per-checkpoint in `gaitfriction_speed_sweep.py` (only `gaitfriction_r5`+
were trained with it), `PHASE_RATE_MAX` falls back to the old `1.60` when
disabled. Re-ran with the fix -- baseline numbers now match every prior
measurement exactly (4.08/4.99/5.18deg), confirming the fix, not just a
different-looking number.

**Corrected, valid result:**

| Band | Baseline RMS | r5 RMS | Baseline speed err | r5 speed err |
|---|---|---|---|---|
| creep | 4.08deg | 9.17deg | -0.008 | -0.020 |
| cruise | 4.99deg | 10.22deg | -0.014 | +0.003 (+1 fall) |
| fast | 5.18deg | 10.31deg | -0.015 | -0.017 |

Also a regression -- residual usage roughly doubled, same magnitude as
the amplitude-scaling failures, plus a new fall at cruise (cmd=0.12) that
wasn't there before. This despite the open-loop correction being directly
verified to work *before* training (confirmed narrowing the true
open-loop gap across the whole range). The fix to the reference was real;
something about training a policy around it still produced a worse
result.

**Conclusion: four independent, differently-mechanismed interventions
have now all regressed in the same direction** -- amplitude scaling
(pose shape, x2), residual-cost calm-bonus (reward weights, x2), cadence
recalibration (reference speed, x1). Not pursuing a second round of
option 1, or a fifth lever. `run20m_resid30_ppo`'s existing ~4-5deg
cruise-speed residual usage reads as a genuine, structurally load-bearing
property of how this recipe currently reconciles imitation-match against
speed-tracking -- not a fixable inefficiency, at least not through any
mechanism tried this campaign. Campaign concludes here; folding into the
final synthesis as a documented negative result across the board, same
standard as Phase 4a's ledge finding.
