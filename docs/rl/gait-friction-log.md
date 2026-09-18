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

(none yet — queued to start after the resid30 Stage 3 report)
