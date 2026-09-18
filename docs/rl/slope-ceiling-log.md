# Slope-ceiling campaign log

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

## Rounds

(none yet -- queued behind resid30 and creep-friction)
