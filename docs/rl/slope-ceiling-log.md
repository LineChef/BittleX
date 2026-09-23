# Slope-ceiling campaign log

> **Superseded (2026-09-23), see [`hw1-log.md`](hw1-log.md) "Slopes":** the
> benchmark's slope labels were inverted (pitch > 0 is *downhill*), T7.x–T9.x
> ran without the payload (cell-knob leak), and ~35 % of every slope cell's
> episodes were flat rough ground. So "T9.1 18° up" was really 18° downhill,
> "T9.2 20° down" was a 20° climb, and the falls this campaign chased were
> bare-robot results. A clean re-measure found G2 falls on no slope with its
> payload; its real problems are side-hills (stalls by ~8°) and climbs past ~20°.

Queued third, after the resid30 campaign (`docs/rl/resid30-log.md`) and the
gait-friction fix (`docs/rl/gait-friction-log.md`). Same branch
(`auto-gait-iteration`), same automated-testing-loop.md methodology.

## Context

While stress-testing `run20m_ppo` looking for a genuine fall (separate from
the resid30 question), a quick decathlon pass found a real, clear failure
mode that horizontal pushes and terrain roughness never produced:

| Cell | Learned fall rate | Scripted fall rate |
|---|---|---|
| T9.1 -- 18 deg slope up (beyond training's 14 deg ceiling) | **62%** | 0% |
| T8.2 -- rough/uneven + rolling swell | 12% | 0% |
| T9.3 -- denser/taller rubble than training | 22% | 25% |

Extensive testing ruled out other candidate stressors as the "real" weak
point: horizontal shoves (any direction/timing, up to absurd magnitudes),
uniform terrain roughness (0.006-0.060 range), and a sustained one-sided
foot-height mismatch (10-80mm step under only one side, confirmed via
direct contact-point logging, not just placement) -- none of these produced
falls. The actual pattern: this policy is robust to local/momentary
disturbances but brittle specifically at the edges of its trained
terrain-angle envelope.

`SLOPE_MAX_DEG` (`opencat_gym_env.py:365`) has precedent for exactly this
fix already: raised once before from 10 -> 14 (coverage R1, 2026-09-04)
"so the tail reaches into steep territory instead of capping at gentle."
Falling 62% (not 100%) at 18 deg suggests this is "at the edge of / just
past what it learned," not a hard geometric wall -- the kind of gap
curriculum expansion usually fixes.

**Open question, not yet resolved:** whether this is purely a
training-exposure gap (curriculum expansion fixes it) or partly a
sim-traction/fidelity issue at steep angles (this project has hit a
sim-fidelity wall before, on climbing). Treat a clean result as evidence,
not a guarantee going in.

## Approach

Raise `SLOPE_MAX_DEG` 14 -> ~20 (a bit past the 18 deg failure point,
matching the same "raise past what breaks it" logic as the original 10->14
move). Short diagnostic round(s), matching `automated-testing-loop.md`
convention, off whichever recipe wins the resid30 campaign. Check
specifically whether fall rate on the T9.1-style steep-slope cell actually
drops, not just aggregate metrics.

## Update: resid30 Stage 3 changed the shape of this problem

The resid30 campaign's Stage 3 decathlon run (`docs/rl/resid30-log.md`)
found that widening `RESIDUAL_SCALE_DEG` 22->30 fixes T9.1 (this doc's
original finding, 18deg slope up, beyond the 14deg training ceiling)
completely -- 62% fall rate on the 22deg baseline down to 0% on resid30,
with zero dedicated slope training. But the same run found a new, equally
severe failure in the mirror direction: T9.2 (20deg slope down, also
beyond the 14deg ceiling) went from 0% falls (22deg baseline) to 68%
falls (resid30) -- `forward_speed_mps_mean` goes negative, consistent with
tumbling down the slope rather than a controlled stop. Reads as the same
underlying gap (undefined behavior past the trained slope envelope)
showing up on whichever side isn't covered, not two independent problems.

**Consequence for this campaign's approach:** raising `SLOPE_MAX_DEG`
needs to validate *both* directions (up and down) going forward, not just
re-check the original up-slope failure point -- a fix that only chases the
side that failed on the current leading checkpoint risks re-creating the
same asymmetry the next time the residual budget or recipe changes.
Whether this campaign proceeds against `run20m_ppo` (22deg) or
`run20m_resid30_ppo` (30deg) once resid30's promotion decision is made
will change which direction looks urgent -- worth re-confirming both
directions on whichever checkpoint this runs against, rather than assuming
only the previously-known failure point still applies.

## Rounds

### Round 1 — slopeceiling_r1

- **Started:** 2026-09-18, 3M steps, PID 92879. Base: `run20m_resid30_ppo`'s
  recipe (the frozen base) -- `FAC_NOSTALL` stays off (reverted, documented
  negative result in the resiliency campaign), gait-friction's cadence
  correction stays off (also reverted). Fresh run, not a continuation.
- **`SLOPE_MAX_DEG` 14 -> 20**, bidirectional -- past both known failure
  points (T9.1 18deg up, T9.2 20deg down), same "raise past what breaks
  it" logic as the original 10->14 move, now applied to both signs of
  tilt instead of one.
- **Smoke test:** passed clean before launch.
- **What to check at completion:** fall rate specifically on T9.1-style
  (steep up) and T9.2-style (steep down) decathlon cells, not just
  aggregate metrics -- confirms whether the fix actually closes both
  directions of the gap, or just moves which side fails.

### Closed (2026-09-18) -- reverted, inconclusive/negative, user's call

Presented three options after round 1's mixed result: (1) denser sampling
specifically in the 14-20deg band, targeting the diagnosed cause; (2) same
distribution, run longer; (3) revert and close the campaign now, given the
broader pattern this session (8 of 8 attempted changes since the resid30
promotion -- 5 gait-friction, 2 `FAC_NOSTALL`, this one -- failed to
clearly improve anything). User chose (3).

`SLOPE_MAX_DEG` reverted 20 -> 14. `opencat_gym_env.py` confirmed back to
a clean state matching the resid30 baseline across every campaign this
testing cycle touched (`FAC_RESID_CALM_BONUS=0`, `PHASE_RATE_CORRECTION_ENABLED=False`,
`FAC_NOSTALL=0`, `SLOPE_MAX_DEG=14`) -- smoke-tested clean.

T9.1/T9.2 (steep up/down slope, beyond the 14deg training ceiling) remain
open, real, measured weak points -- this campaign didn't resolve them, it
ruled out one specific approach (widen `SLOPE_MAX_DEG` via the existing
triangular sampling, in a single 3M round) without conclusively testing
whether a denser-sampling variant would fare better. Worth revisiting with
that specific fix if this area gets picked back up later, rather than
re-deriving the diagnosis from scratch.
