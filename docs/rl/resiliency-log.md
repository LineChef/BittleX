# Resiliency campaign log

Queued third, after the resid30 campaign and gait-friction testing. Two
phases: (1) build a proper resiliency-measurement tool and use it to
characterize every candidate stressor, (2) once characterized, design and
run a fresh 20M training run explicitly targeting resiliency, willing to
trade some cadence/speed-matching quality for it.

## Why a new measurement tool, not just more `evaluate_policy.py` runs

Today "resiliency" is measured ad hoc — `fell_fraction` on whatever single
scenario a script happens to set up, or a decathlon cell's fixed-severity
pass/fail. That's good enough for a one-off "does X cause falls" check
(which is how we found the rough-terrain and slope results), but it can't
answer the actual question this campaign needs answered: **is a candidate
policy more resilient than the last one, and by how much, in a way that's
comparable across training rounds.**

A proper resiliency benchmark needs three things the current tools don't
give in one place:
1. **A dose-response sweep per stressor**, not one fixed severity — so
   improvement shows up as "fall rate at severity X dropped from 40% to
   15%," not just a binary pass/fail that can't track partial progress.
2. **Recovery quality, not just fall/no-fall** — peak tilt reached, whether
   it recovered without falling even if it wobbled hard, time-to-recover.
   Two policies that both "don't fall" at a given severity aren't equally
   resilient if one is visibly closer to the edge.
3. **A long-duration axis** — every test run in this campaign so far used
   ~250-step (~3s) episodes. Real G2 operation is continuous for minutes;
   small per-step imperfections (the friction campaign's whole subject)
   could compound very differently over 60+ seconds than over 3.

## Plan: `benchmark_resiliency.py`

New script, modeled on `benchmark_decathlon.py`'s structure (matched
per-episode seeds, JSON output, `tools/build_decathlon_report.py`-style
HTML reporting) but organized around dose-response sweeps instead of fixed
graded tiers. For each stressor axis: run N episodes at each of several
severity levels, record fall fraction, peak tilt distribution, recovery
time for survived-but-disturbed episodes, and forward progress (to catch
"gave up and stood still" as a soft failure, not just literal falls).
Output: a per-axis dose-response table/chart for diagnosis, plus a single
composite resiliency score (e.g. mean fall rate across all axes at a fixed
"moderate-hard" severity) for at-a-glance tracking across training rounds.

This tool gets built once and reused for every future resiliency check,
not just this campaign.

## Stressor axes to characterize (testing rounds, after gait-friction)

Priority order per the user's steer: #1 and #4 first, then
latency/servo-miscalibration, then the rest already discussed.

1. **Long-duration continuous-walk drift** (highest priority). Extend
   episodes well past the standard 250 steps (e.g. 2000+ steps, ~25s+) and
   check whether fall rate or drift increases over the course of a single
   long episode, not just across many short ones. Tests whether the
   friction-campaign's ~7-8 degree baseline residual usage compounds into
   real trouble over realistic operating durations.
2. **Aggressive command transitions** (highest priority). Sudden stop,
   sudden reversal, rapid alternating forward/backward commands — a fixed
   set of transition "scripts," not a static disturbance. Tests whether
   the gait handles its own commanded behavior changing abruptly.
3. **Command latency** (`CMD_LATENCY_STEPS`, currently 0/untested).
   Sweep 0, 1, 2, 4, 8 control-steps of lag. Directly relevant to hardware
   transfer -- sim runs at 80Hz, the real BiBoard control loop is ~48-50Hz,
   a real, already-documented gap this axis has never been trained against.
4. **Servo zero-point miscalibration** (`JOINT_OFFSET_DEG`, currently
   0.0/untested). Sweep 0, 2, 5, 10 degrees per-joint offset. Also directly
   relevant to hardware transfer -- real servos are never perfectly
   zeroed.
5. **Rough terrain** (`ROUGH_TERRAIN`, proven to cause real falls at
   T8.2's setting, never properly swept). Amplitude sweep past the current
   default, same "characterize past the trained range" logic as slopes.
6. **Drop/pit** (new mechanism, not yet built). A sudden drop-away under
   one foot, not just a raised step -- overextension/loss-of-support is a
   different failure mechanic than anything tested so far, and specifically
   matches "a steep step down on one side."
7. **Dense/sharp obstacle field**, sized to intersect swing-foot
   trajectories specifically, pushed well past the range already ruled out
   (0.006-0.060 with no effect).
8. **`STUCK_FOOT`** (built, never tested). Sweep probability/duration.
9. **Already-randomized-but-uncharacterized DR knobs**: `RANDOM_FRICTION`
   (+/-30% default), `TORQUE_CUTBACK` (up to 35% torque loss),
   `PAYLOAD_MASS_RAND` (43-79g) -- find their actual failure thresholds
   the same way, rather than trusting the training default is well-matched
   to where things break.
10. **Combined gnarly course**, last, once the individual axes are
    understood -- rough terrain + dense obstacles + latency together. This
    is where the compounding effect (the actual pattern behind why
    isolated pushes failed but rough terrain succeeded) is expected to
    show up most clearly.

Explicitly deprioritized per user steer: steep slopes past 14 degrees
(real, confirmed, but not a realistic scenario for G2's actual
environment) -- kept as a documented finding (`slope-ceiling-log.md`), not
pursued as a training target.

## Phase 2: a resiliency-focused 20M training run

Once the axes above are characterized, design a new training recipe and
run it fresh (20M steps), explicitly trading some of the current gait's
cadence-matching/speed-tracking tightness for resilience under the
stressors that actually proved meaningful. Concrete levers, to be finalized
once real dose-response data exists rather than guessed now:

- **Curriculum**: enable/increase DR probability and amplitude for
  whichever axes showed a real dose-response (expected: rough terrain,
  drop/pit, dense obstacles, latency, servo offset; expected NOT
  meaningful: more of what's already ruled out, e.g. plain lateral pushes).
- **Reward rebalancing**: likely loosen `FAC_IMITATION` and/or
  `FAC_SPEED`/`FAC_SPEED_TRACK` somewhat -- a resiliency-focused gait may
  need to deviate further from the exact scripted reference and exact
  commanded speed when survival is at stake, and today's tight imitation
  anchor may be actively fighting that. This is the "willing to sacrifice
  some other stats" tradeoff made concrete.
- **Residual authority**: worth revisiting `RESIDUAL_SCALE_DEG` again with
  real data this time -- the resid30 campaign found no saturation under
  easy conditions, but a genuinely harder curriculum might exercise the
  wider ceiling for real, which would be the first real evidence either
  way (vs. today's speed-only motivation).
- **`FAC_RESIDUAL_COST`/`FAC_RESID_SMOOTH`**: may need loosening too, so
  the policy doesn't get over-penalized for large corrective motions in
  genuine crisis moments.
- Final evaluation: the new checkpoint gets scored on
  `benchmark_resiliency.py` (did it actually get more resilient) AND the
  standard `benchmark_decathlon.py`/`evaluate_policy.py` metrics (did it
  regress catastrophically on ordinary walking) -- both matter, this is a
  tradeoff being made deliberately, not blindly.
- Compare against both `run20m_ppo` and whichever recipe wins the resid30
  campaign, not just one baseline.

## Rounds

(none yet -- queued behind resid30 and gait-friction)
