# Creep-speed friction campaign log

Queued to run immediately after the resid30 campaign's Stage 3 benchmark
report is generated (`docs/rl/resid30-log.md`), same branch
(`auto-gait-iteration`), same automated-testing-loop.md methodology.

## Context

Investigating why the residual policy spends a meaningful share of its
degree budget even on flat, undisturbed ground (found while building the
action-trace visualization for the resid30 side-question). Measured the
*pure open-loop scripted gait* (`wkF`, action forced to 0) against its
commanded speed across the full command range:

| Command | Actual speed | Error |
|---|---|---|
| 0.02 m/s (creep-low) | 0.001 m/s | -93% |
| 0.04 m/s (creep-mid) | 0.040 m/s | 0% |
| 0.10 m/s (cruise) | 0.095 m/s | -4.6% |
| 0.115 m/s (fast-low) | 0.109 m/s | -5.0% |
| 0.15 m/s (fast-high, max) | 0.139 m/s | -7.5% |

The mismatch is concentrated almost entirely at very slow "creep" commands,
not spread evenly across the speed range. Root cause: `PHASE_RATE_MIN =
0.35` (opencat_gym_env.py) clamps how much the gait's phase-advance rate
can slow down. Phase-rate scaling only changes cadence (steps/second), not
stride length, so below roughly 0.035 m/s commanded (0.35 x
`PHASE_RATE_NOM_CMD`=0.10), the scripted gait physically cannot slow down
enough to match — the residual has to cover the entire gap by itself, on
the ~20% of training episodes that sample a creep command (`_sample_command`,
band currently `(0.02, 0.055)`).

Confirmed two speed-reward terms (`FAC_SPEED`/`r_speed`,
`FAC_SPEED_TRACK`/`r_speed_track`) both already track the *actual sampled
command* (`self._cmd_fwd`), not a separate fixed target — so this is not a
reward-contradiction bug, it's a real mechanical gap between what gets
commanded and what the scripted reference can physically execute.

## Approach

**Option chosen: narrow the creep sampling band**, not touch gait timing
mechanics. Change `_sample_command()`'s creep band from
`np.random.uniform(0.02, 0.055)` to approximately `np.random.uniform(0.04,
0.055)` (or similar, tuned to what `PHASE_RATE_MIN` can actually reach with
a small margin) — training on commands the scripted base can realistically
execute, instead of on ones with a built-in ~90%+ open-loop failure the
residual has to fully absorb every time.

Rejected for this round: lowering `PHASE_RATE_MIN` itself (touches core
gait timing mechanics for every speed band, not just creep, and risks
interacting with foot-phase/contact-timing terms — higher risk, needs its
own isolated test if the sampling-band change alone doesn't fully resolve
it).

## Testing plan

1. **Baseline measurement** (done above) — pure open-loop speed-tracking
   error across the command range, already establishes where the gap is.
2. **Change**: narrow the creep band in `_sample_command()`.
3. **Short diagnostic round(s)**, 2-3M steps each, fresh run off whichever
   recipe wins the resid30 campaign (i.e. either `run20m_ppo`'s original
   recipe or the resid30 recipe, whichever the Stage 3 benchmark confirms as
   the better base) — matching `automated-testing-loop.md`'s standard round
   size.
4. **Evaluate**: `evaluate_policy.py` fall/speed metrics as usual, plus
   `action_trace.py` runs pinned at a few points across the (narrowed)
   creep band and at cruise/fast, comparing mean residual usage before vs.
   after the band change — the specific thing being tested is whether
   creep-band residual usage drops toward cruise/fast levels, not just
   whether overall metrics look fine.
5. **Decision gate**: promote if creep-band residual usage drops
   meaningfully without regressing fall rate or cruise/fast speed tracking;
   revert after two non-improving rounds, per standard loop discipline.
6. Log each round here, one entry per round, same format as
   `resid30-log.md`.

## Rounds

(none yet — queued to start after the resid30 Stage 3 report)
