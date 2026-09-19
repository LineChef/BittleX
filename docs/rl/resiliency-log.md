# Resiliency campaign log

Queued third, after the resid30 campaign and gait-friction testing, and
followed by `docs/rl/final-synthesis-plan.md` once this campaign (and the
other two) are done -- that's where findings across all three campaigns
turn into an actual fresh-20M-run recipe. This doc stays scoped to
resiliency testing itself. Folds
together two things: the new testing this session planned (long-duration
drift, aggressive command transitions, latency, servo-miscalibration, plus
the fall-hunting list) **and** a prior systematic campaign
(`docs/rl/robustness-backlog.md`, the "R-series," Sept 3-7) that already
tested most of the same ground months earlier and reached a conclusion
worth leading with.

## The reframe: stalling, not falling, is the dominant failure mode

Found while checking the robustness backlog for prior art before building
new test infrastructure — should have been the first thing checked, not
the last. A 300+ rollout probe batch against the frozen base (`run20m_ppo`)
found **1 fall**. Everywhere else, the robot didn't tumble — it stopped:

| Scenario | Result |
|---|---|
| Carpet, 90s episode | speed decayed to 0.00 m/s by 60s |
| Side-hill, 10-15deg sustained tilt (R12a) | -73% speed |
| Stepped split, one side raised 15-25mm (R12b) | -92% speed (under left feet specifically -- a real left/right handedness asymmetry) |
| Thin raised lip, 15mm (R4) | 0/16 crossed, just recoils |
| Pick-up/set-down (R3) | 31/32 re-acquire fine -- no problem here |

This matches everything found independently this session too (lateral
pushes, terrain roughness, one-sided steps -- none produced falls) from the
other direction: this gait is hard to knock over, but gives up very easily
under sustained resistance. **"How do we make it fall" was the wrong
primary question; "how do we make it stop giving up" is the one the
project's own prior work already answered was real.**

A fix was already designed and implemented for exactly this:
**`FAC_NOSTALL`** (dense window-speed bleed while stalled below
`NOSTALL_FLOOR_FRAC` of commanded speed, plus a per-0.15m breakthrough
bonus while resisted) -- currently `FAC_NOSTALL = 0.0`, **off** in both
`run20m_ppo` and the resid30 checkpoints. It was validated once (Phase D,
vision-vs-blind A/B) but scoped narrowly to that experiment and never
folded into the main walk recipe. Design note from when it was built: "only
makes sense trained WITH the forward terrain feature" -- worth confirming
whether that constraint still holds or whether it can activate without the
vision terrain feature too, since `features.vision` is currently gated off
project-wide.

## What's already answered vs. genuinely open

Mapping everything discussed this session against the R-series backlog,
so nothing gets rebuilt from scratch:

**Already tested, real findings, no need to re-derive:**
- R10 (long-duration drift, this session's #1 priority) -- confirmed
  severe (0 m/s by 60s on carpet). What's still open: re-verify against
  the *current* checkpoints (run20m_ppo confirmed pre-resid30; resid30 and
  any future recipe need their own check), since the original probe used
  `run20m_carpet`, an intermediate checkpoint from that era.
- R12a/R12b (uneven terrain / stepped split) -- confirmed severe stalling,
  essentially the same test as the one-sided-step idea from earlier this
  session, already done properly with real numbers.
- R4 (thin raised lip / threshold) -- confirmed severe (0/16), a very
  realistic home-robot scenario (rug edges, door thresholds).
- R3 (pick-up/set-down) -- confirmed fine, no action needed.
- R11 (lateral link collision), R1 (single weak/dead servo), R7 (servo
  backlash/deadband) -- explicitly `DROPPED` in the prior campaign. Not
  re-opening without a specific reason to.

**Flagged for reopening, status changed since the original triage:**
- **R2 (IMU bias & mount tilt)** -- was `DEFERRED` pending "how solid is
  the real Pi<->PiSugar connection." That's now answered: confirmed solid
  tonight (correct pogo-pin orientation found and verified). Worth
  reopening.
- **R9 (within-episode degradation -- latency ramp, thermal/battery sag)**
  -- already flagged "revisit after the 20M run," which is what's
  in-flight right now (Stage 3). Directly covers this session's
  latency/servo-miscalibration priority, but frames it as *ramping during
  an episode* rather than fixed-per-episode -- more realistic than a
  static offset, worth using this framing instead of a simpler static test.
- **R8 (aggressive command dynamics)** -- explicitly `DROPPED` in the
  original triage (no detailed reasoning recorded in the log for why,
  unlike some other drops). This session's #4 priority matches R8
  directly. Flagging the conflict rather than silently overriding the
  prior call: worth a quick check of *why* it was dropped (git history
  around 2026-09-03 may have the reasoning even though this doc's entry is
  terse) before re-running it, in case there was a real reason, not just
  triage bandwidth.

**Already-built mechanisms to reuse instead of building new ones:**
- **`RUBBLE`** (not `RANDOM_TERRAIN`, which this session tested and found
  nothing) is the actual primary discrete-obstacle hazard, `RUBBLE_N`
  up to 560 / `RUBBLE_MAX_H` up to 0.020 already used in the hardest
  existing gauntlet cells. Use this, swept past those values, for "dense
  obstacle field" testing instead of building something new.
- **`LEDGE_HEIGHT`/`LEDGE_PROB`/`LEDGE_DIR`** (`LEDGE_DIR=-1` = step-down
  only) is literally the drop/pit mechanism from this session's list --
  already built, currently retired/inert. Real history worth knowing:
  Phase 4a tried training on it at 25mm/30% DR and made ledge handling
  *worse* ("robot backs away from steps") while halving nominal walk speed
  -- a documented negative result for training on it carelessly, still
  fine to use for held-out eval/characterization.
- **`STUCK_FOOT_PROB`** -- confirmed still just a knob in the `_ZERO`
  reset list, matches this session's stuck-foot idea, still untested.

**Genuinely new, not covered by prior work:**
- Static per-episode servo zero-offset (`JOINT_OFFSET_DEG`) -- R9 covers a
  *ramping* version, not a fixed miscalibration from episode start; worth
  testing both.
- Aggressive command transitions as this session specifically framed them
  (sudden stop, sudden reversal, rapid oscillation) -- pending the R8
  reopening-reasoning check above.
- The combined "gnarly course" (multiple stressors at once) -- the prior
  campaign tested axes individually; compounding effects specifically
  weren't the focus there.

## Queue reorder (2026-09-18): FAC_NOSTALL jumps ahead of the rest of this list

User watched it happen directly in the Stage 3 report's leg-tinting GIF
(`run20m_resid30_ppo` backing away after hitting an obstacle) and asked
about FAC_NOSTALL's status. Confirmed it's still off and asked whether to
pull it into the in-flight `gaitfriction_r1` round or keep it isolated.
Recommendation (approved): keep it isolated -- `gaitfriction_r1` is testing
a different, unrelated hypothesis (cruise-speed friction via amplitude
scaling) and bundling would confound both reads, the same
already-documented lesson this campaign's own R-series backlog raised
about combining unproven changes blind. But re-sequence step 2 below to run
immediately after `gaitfriction_r1` finishes and is evaluated, ahead of
steps 3-7 (R2, R9, R8, `RUBBLE`/`LEDGE` characterization, `STUCK_FOOT`,
`JOINT_OFFSET_DEG`) -- direct visual confirmation of the dominant failure
mode moves it up the priority list, even though the underlying plan already
had it right.

## Revised plan

1. **Re-verify R10/R12/R4 against the current checkpoints** (run20m_ppo,
   then whichever wins resid30) -- cheap, the test methodology already
   exists, just needs re-running. Confirms the stalling problem is still
   present in the current frontier, not just the older checkpoint it was
   originally found on.
2. **Re-instate `FAC_NOSTALL`** -- confirmed priority (user, 2026-09-18),
   not just a "try it" item. Deliberately **not** touching the in-flight
   Stage 3 run for this (too far in -- 11M+/20M steps -- to change the
   recipe mid-run); this is queued as the first real reward change in the
   resiliency campaign's own training round instead. This is the
   already-designed, already-partially-validated fix for the actual
   confirmed dominant failure mode (the gait stopping when it hits
   resistance, e.g. an obstacle), higher leverage than inventing new
   stressor axes blind. Check whether it needs the terrain-feature
   dependency it was originally scoped with, or works standalone.
3. **Reopen R2 (IMU bias)** now that the hardware precondition is met.
4. **Run R9 properly** (within-episode latency/thermal/battery ramp) --
   covers this session's latency + servo-miscalibration priorities in a
   more realistic form than a static test.
5. **Check R8's drop reasoning** before deciding whether to re-run
   aggressive command transitions as originally proposed or in some
   modified form.
6. **Characterize `RUBBLE` and `LEDGE_DIR=-1`** properly (dose-response
   sweep, past the values already used in existing gauntlet cells) --
   reusing existing mechanisms, not building new ones.
7. **`STUCK_FOOT`**, static `JOINT_OFFSET_DEG`, and the combined gnarly
   course last, as originally planned -- these remain genuinely new.
8. Build `benchmark_resiliency.py` (dose-response sweep tool, composite
   score, as originally planned) once the above informs what it actually
   needs to measure -- better to design the tool around real findings than
   guess at its shape first.

## Final scope for this pass (2026-09-18) -- supersedes the "Revised plan" list above

Went through the whole plan item by item with the user once tooling was
built and the ledge investigation was done. Final scope:

- **R10 (item 1, carpet half)** -- **deferred to hardware**, not re-run in
  sim. Sim carpet is an unvalidated guess (see `hardware-gated-backlog.md`
  H10) -- a sim-only re-verification of a carpet-stalling finding would
  carry the same fidelity risk the original result did. Bundled into H10's
  existing hardware-gated sysid work instead of a separate sim test.
- **R12 (item 1, uneven-terrain half)** -- kept, but reframed: no separate
  slope-specific incentive gets built. `FAC_NOSTALL`'s mechanism (penalize
  insufficient net progress in the commanded direction, regardless of
  cause) is direction- and terrain-agnostic, and R12a/R12b's stalling
  (-73% to -92% speed) is the same "gives up under resistance" pattern
  `FAC_NOSTALL` exists to fix generally. R12 re-verification is now one of
  the cells that confirms whether `FAC_NOSTALL`'s round actually worked,
  not a separate reward-design task. Only build something slope-specific
  if R12 *still* fails after `FAC_NOSTALL` clears its bar.
- **R4** -- unchanged, still queued as cheap re-verification.
- **R2 (IMU bias)** -- **dropped.** Script stays built (smoke-tested,
  ready if reopened later) but not run this pass.
- **R9 (episode ramp)** -- **dropped**, same as R2.
- **R8 (command dynamics)** -- unchanged, still queued.
- **Dose-response sweep (`resilience_dose_response.py`), trimmed:**
  - `LEDGE` cells -- **dropped**, redundant now. Today's direct
    investigation (contact-point check + visual GIF review, the 24-27mm
    recoverable band) already covers this more thoroughly than the
    dose-response cells would.
  - `STUCK_FOOT_PROB` -- **cut entirely**, not even as a diagnostic.
    Reasoning (user, 2026-09-18): a genuinely stuck/jammed foot (motor
    holds position regardless of command -- a servo fault or physical
    entrapment, distinct from obstacle *resistance*, which the foot can
    still move against) should make G2 **stop immediately**, not have the
    gait learn to compensate and keep walking on the other three legs --
    continuing to command a jammed joint risks servo burnout (the same
    tracking-error-under-load signal `docs/hardware/servo-thermal.md`
    already uses as its heat proxy). That behavior belongs in a
    behavior-layer safety reflex, not the RL reward function -- see
    `jam_guard.py` below, which already exists for exactly this.
    `FAC_NOSTALL` interaction risk noted: its general "penalize
    insufficient progress" pressure could actively push a policy toward
    *more* effort against a genuine jam if the two were ever combined --
    another reason not to train this into the gait.
  - `RUBBLE` (past current max severity) -- **dropped** (updated
    2026-09-18, was "deprioritized"). Weakest remaining item once R2/R9/
    `STUCK_FOOT`/`LEDGE` were already cut -- envelope-characterization of
    an already-tested mechanism, not a new question.
  - `JOINT_OFFSET_DEG` -- check `robustness_sweep.py` (existing tool)
    before building anything new; it already sweeps `joint_offset_deg` as
    one of its axes and may already cover this.
- **`benchmark_resiliency.py`** -- **moved to backlog, not built this
  pass** (2026-09-18). With `RUBBLE`/`LEDGE`/`STUCK_FOOT`/R2/R9 all cut,
  what's actually left to synthesize (`FAC_NOSTALL`'s result, the
  flooring-transition/ledge result, R4, R8) is small enough to write up
  directly in the final synthesis doc rather than justify a dedicated
  composite-scoring tool. May revisit if a later campaign's scope grows
  back into something that actually needs it.
- **`jam_guard.py` (behaviour-ideas B9a)** -- checked its actual state
  before assuming it needed new testing: **the decision logic is already
  fully built and tested** (`pi_pipeline/gait/jam_guard.py`, 181 lines,
  pure logic/no I/O; `pi_pipeline/tests/test_jam_guard.py`, 12/12 passing,
  0.08s -- `test_sustained_front_divergence_backs_off` directly covers "a
  jam makes it stop," plus the full backoff->turn->resume sequence and
  edge cases). What's genuinely not done: it isn't wired into
  `pi_pipeline/gait/run_gait.py` yet (confirmed -- zero references), and
  the threshold constants (`jam_deg`, `min_jammed_joints`, etc.) are
  placeholders that need real servo-feedback data to calibrate (normal
  carpet load, leg-on-leg brushing, and stepping a bump could all produce
  similar divergence, per the module's own docstring). **Wiring + a
  mock-level integration test deferred to hardware bring-up**, per the
  user's call -- consistent with the module's own original design note,
  not a new deferral.

## Tooling built ahead of time (2026-09-18)

Built and smoke-tested (2 episodes/checkpoint, not full runs -- just
confirming each script runs correctly and produces plausible numbers)
while `gaitfriction_r1` trained in the background, so the remaining
campaign has real per-checkpoint timing instead of estimates by analogy,
and a concrete plan is in place before any of this actually runs for real.
Full-run estimates below are extrapolated from smoke-test wall-clock while
CPU-contended with the in-flight training round -- real numbers once run
standalone will likely be faster, not slower.

- **`resilience_imu_bias.py`** (R2) -- sweeps a new `IMU_BIAS_DEG` env
  constant (persistent per-episode roll/pitch bias, observation-only,
  reward stays clean -- distinct from `RANDOM_GYRO`'s existing zero-mean
  per-step noise). Required an `opencat_gym_env.py` change: the existing
  IMU-noise injection point (`obs_ang`/`tnorm`) now applies the bias first,
  before the noise layer, consistently across `obs_ang`, the derived
  `proj_grav`, and `tilt_history`. Default off (`IMU_BIAS_DEG = 0.0`), so
  no behavior change for any existing script. Smoke test (2 eps x 2
  levels) ran clean in ~4s contended -- **est. ~10-15 min/checkpoint** for
  a real sweep (20 eps x 6 levels).
- **`resilience_episode_ramp.py`** (R9) -- reframed from a static offset to
  an actual within-episode ramp per the plan's own note ("more realistic").
  Ramps `env._torque_scale` (battery/thermal sag proxy) and `env._act_buf`
  length (latency) linearly over one long (800-step) episode, entirely from
  outside the env -- no training-code changes needed, since both are
  already per-step-mutable state. Splits results into quarters to see
  *when* degradation shows up. Smoke test already shows a real signal even
  at n=2: severe-level speed goes from +0.053 m/s (Q1) to -0.004 m/s (Q4,
  net backward drift) vs the no-ramp baseline's -18% Q4-vs-Q1 (ordinary
  noise). **Est. ~2 min/checkpoint** for a real run (12 eps x 4 levels).
- **`resilience_dose_response.py`** -- dose-response sweep for `RUBBLE`
  (past the existing gauntlet's max severity), `LEDGE_DIR=-1` (step-down
  only), `STUCK_FOOT_PROB`, and static `JOINT_OFFSET_DEG`, plus a combined
  "gnarly course" cell stacking all four. Reuses
  `benchmark_decathlon.py`'s cell/knob-override infrastructure directly
  (`_apply`, `_bench`, `ScriptedGait`, `_load_learned`) rather than
  reinventing it. Payload deliberately OFF for the whole sweep
  (`--extra-dr clean`), matching this session's own T5.1b/T6.*b finding
  that payload mass masks real stance weakness. Smoke test (2 eps/cell, 9
  cells) already surfaced a real, severe finding: **`D-ledge-2`/`D-ledge-3`
  (30mm/45mm step-down) hit 100% falls for BOTH learned and scripted at
  n=2** -- worth flagging even this early; needs the real episode count to
  confirm it's not a seed artifact, but a clean 100/100 split at the first
  check is a strong signal either way. **Est. ~3.5 min/checkpoint** for a
  real run (20 eps x 9 cells).
- **`resilience_command_dynamics.py`** (R8) -- reopened; checked git
  history first (`git log`, `robustness-backlog.md`'s 2026-09-03 triage
  commit) and found no specific technical objection survived the doc's
  later restructure, just terse `DROPPED` with a knob sketch -- reopening
  rather than leaving it dropped by default, since it directly matches this
  session's own priority. Four scripted command schedules via the existing
  `env.set_command()` (already built for fixed-command eval, just never
  hammered with a schedule): `reverse-slam` (full forward -> hard reverse),
  `yaw-slam` (cruise + sign-flipping yaw), `stop-start` (walk/stand
  alternating), `sustained-arc` (fixed nonzero yaw held the whole episode,
  measuring heading drift against the commanded rate, not just fall rate).
  Smoke test already shows the expected pattern given `TRAIN_YAW_RANGE=0`
  by default (turning dropped from the curriculum, G4): `sustained-arc`
  drifts ~0.56 rad off the commanded heading even at n=2 -- not a bug,
  confirms known behavior. **Est. <1 min/checkpoint** for a real run
  (12 eps x 4 modes).
- **Not built, deliberately:** `benchmark_resiliency.py` (the composite
  dose-response tool) stays deferred until these four scripts' real
  findings inform its shape, per the plan's own reasoning. R10/R12/R4
  re-verification doesn't need new tooling -- `robustness_sweep.py`
  (existing, covers `joint_offset_deg`/`cmd_latency_steps`/`torque_cutback`/
  `imu_noise` as individual fixed-per-episode axes) plus the decathlon's
  own cells already provide the methodology; only a re-run against current
  checkpoints is needed there.

## Ledge-recovery investigation (2026-09-18) -- a real training round, not just eval

Started from the Stage 3 report's leg-tinting GIF (user noticed
`run20m_resid30_ppo` backing away after an obstacle) and the
`resilience_dose_response.py` smoke test's 30mm/45mm step-down cells (both
100% falls). Investigated with a direct contact-point check before
concluding anything: the stepping foot DOES touch the lower floor in 6/6
episodes at every height tested (20/30/45mm) -- not a floor-less pit, ruling
out the user's first hypothesis. Rendered and visually reviewed GIFs of the
actual falls (published, `https://claude.ai/artifact/MJgxbq7s8RMjquCY2zLAnH`):
the robot falls over the shoulder that dropped unexpectedly -- a real,
sudden one-sided-drop destabilization, not a stuck-foot problem.

**Finer sweep (15 episodes/level, `run20m_resid30_ppo`, bare robot):**

| Height | Learned falls | Scripted falls |
|---|---|---|
| 20mm | 0% | 0% |
| 24mm | 67% | 100% |
| 27mm | 47% | 100% |
| 30mm | 100% | 100% |
| 33mm | 100% | 100% |

24-27mm is a genuine partially-recoverable band -- the learned policy
already beats scripted here (incidentally, not by design). 30mm+ is
saturated (confirms the user's visual read that 30mm is at or past the max).

**Key architecture point raised by the user, confirmed by reading the
observation code directly:** the gait has no foot-contact or ground-reaction
force sensing -- PyBullet drives each joint to its commanded angle
regardless of contact, so a missed step produces no distinct joint-angle
signature. The only available signal is downstream body-tilt (IMU/tilt
history), *after* weight has already shifted onto the unsupported leg. So
whatever partial recovery shows up above is purely reactive (borrowed from
general stumble-catch training), not a learned "foot didn't land" reflex --
that ceiling is architectural, not a tuning problem.

Two options discussed: (1) train on the existing reactive signal only --
cheaper, no observation changes; (2) add real per-foot contact sensing to
the observation (`p.getContactPoints()`, technically feasible, gated like
`TERRAIN_FEATURE`/`GOAL_MODE`/`CLIFF` so existing checkpoints are
unaffected) -- bigger, path-altering, and needs checking whether real G2
hardware could ever actually provide this signal (Bittle likely has no
foot-force sensors -- would risk the same sim/real mismatch category that
closed learned vision-in-the-policy, if not checked first).

**Decision: option 1 only, reactive-based recovery training.** Contact
sensing tabled as a real future option, not pursued now.

**Sequencing, given the Phase 4a precedent:** Phase 4a (25mm/30% DR) already
tried almost exactly this and made ledge handling *worse* -- "robot backs
away from steps" while halving nominal walk speed -- the textbook stalling
failure `FAC_NOSTALL` exists to fix. Training ledge exposure before
`FAC_NOSTALL` is in place risks reproducing that exact result. So this
round runs **after** `FAC_NOSTALL`'s round, not before it or bundled with
it, same isolation reasoning as the gaitfriction_r1/FAC_NOSTALL sequencing
decision earlier today.

**Planned config, when this round comes up:** `LEDGE_HEIGHT=0.027`,
`LEDGE_RANDOMIZE=True` (trains across the whole 8-27mm range each episode,
not a single fixed depth -- a natural curriculum from trivial to the
genuinely-challenging point found above), `LEDGE_DIR=0` (**updated
2026-09-18, was `-1`** -- randomized per episode, both step-down and
step-up, not step-down only). Change folds R4 (thin raised lip / step-up
threshold, "0/16 crossed" on an older checkpoint) into this same round
instead of treating it as a separate open question: a real doorway sill or
rug edge gets crossed in both directions in daily use, and training only
step-down would leave step-up completely untested even after this round
completes. Costs nothing extra -- same training round, same compute, just
covers both directions instead of one. R4 becomes verification of the
trained result rather than a standalone probe. Built on whatever recipe
`FAC_NOSTALL`'s round produces.

### Reframe: this is flooring-transition traversal, not drop survival (2026-09-18)

Raised in light of the same session's proprioception-limitation finding
(G2 has no real-time contact/torque sensing, only reactive IMU-based
recovery) -- worth checking whether that finding undercuts this round too
before spending a round on it.

**It doesn't, but for a specific reason, not by default.** The
proprioception gap blocks *proactive* sensing -- detecting a missed step
before weight commits, which continuous blind climbing or the
foot-probing idea (B13) would need. Ledge recovery relies on a different,
already-present mechanism: *reactive* recovery off the IMU tilt signal,
the same one the gait already uses for shove/stumble recovery -- and
already shows 33-53% incidental success at 24-27mm with zero dedicated
training. `FAC_NOSTALL` + exposure training asks whether that *existing*
mechanism can get more reliable, not whether the robot can develop a new
sense it doesn't have.

That said, checked honestly whether it's still worth the round: the
recoverable band is narrow (24-27mm, saturates hard to 100% failure by
30mm) and most *real hazard* step-downs -- stairs, curbs, furniture edges
-- exceed it. Training reliability into an already-narrow, already-capped
band looked like a poor match for the actual risk profile, especially
with `B16` (`CliffGuard`, ledge/desk-edge avoidance, highest priority in
the behavior backlog) already the planned answer for dangerous drops via
avoidance rather than survival.

**The reframe that changes this:** the target isn't "survive a dangerous
drop" at all -- it's routine flooring-transition traversal (rug edges,
doorway sills, tile-to-hardwood lips), which a home robot crosses dozens
of times a day, not occasionally, and which mostly falls in exactly the
5-25mm range this investigation already measured. That's not a
speculative new use case either -- it's the gait-level half of a problem
already flagged as a real priority gap (`project_carpet_mode` memory: G2
stalling on carpet, `CarpetDetector` built but not fully wired). Avoidance
(`CliffGuard`) and gait-level traversal training aren't competing
approaches to the same problem -- they're the right tool for two
genuinely different size regimes: avoid what's dangerous, learn to
reliably cross what's routine.

**Decision: kept in the queue, sequencing unchanged** -- still gated on
`FAC_NOSTALL` clearing its stalling-reduction bar first, same reasoning
as before (Phase 4a's negative result on training this kind of exposure
without the anti-stall fix in place).

## Rounds

### Round 1 — nostall_r1

- **Started:** 2026-09-18, 3M steps, PID 87446. Base: clean resid30
  recipe -- gait-friction campaign's cadence-recalibration attempt
  (`PHASE_RATE_CORRECTION_ENABLED`) reverted to off first (also
  regressed, see `gait-friction-log.md`), so this round starts from the
  unmodified resid30 baseline, not a carryover experimental change.
- **`FAC_NOSTALL=22.0`** (re-enabled from 0/off) -- not a fresh guess,
  the one real validated precedent (`G2E_FAC_NOSTALL=22`, Phase D
  vision-vs-blind A/B, 2026-09-07). `FAC_NOSTALL_BONUS=8.0` unchanged
  (already matched that precedent).
- **Fixed before launch, not after:** the breakthrough-bonus half of the
  mechanism only armed off a recent `TERRAIN_FEATURE` obstacle sighting --
  inert under the current recipe (`TERRAIN_FEATURE=False` project-wide,
  vision-in-gait closed), which would have silently dropped the bonus,
  penalty-only. Added a second, standalone "was stalled" trigger (reuses
  the same proprioceptive signal that drives the penalty) so the full
  mechanism actually fires without vision. Vision trigger kept, not
  replaced, for if `TERRAIN_FEATURE` is ever re-enabled.
- **Smoke test:** passed clean before launch.
- **What this round verifies:** the stalling-reduction bar (rubble,
  shoves, low-speed cells) that gates ledge-recovery training, *and*
  R12 (uneven terrain / stepped split) re-verification, folded in here
  rather than as a separate reward-design task -- `FAC_NOSTALL`'s
  mechanism is exactly the "gives up under resistance" fix R12's
  stalling pattern needs, direction- and terrain-agnostic.
- **Completed:** 3,014,656 steps, converged (`approx_kl` ~0.0003).
  Checkpoint: `trained/nostall_r1_ppo.zip`.
- **R12 re-check (side-hill, 12deg sustained cross-slope, 12 episodes,
  payload off) -- serious red flag, not a pass:**

  | Checkpoint | Falls | Mean speed |
  |---|---|---|
  | `run20m_resid30_ppo` (baseline) | 5/12 (42%) | 0.061 m/s |
  | `nostall_r1` | **12/12 (100%)** | 0.072 m/s |

  Fall rate jumped from 42% to 100% under sustained lateral tilt -- a
  large, clear regression, not noise (n=12, both checkpoints tested on
  matched seeds). The reported speed numbers aren't directly comparable
  here since a fallen episode's "speed" is measured only up to the point
  of falling, not a full 250-step episode -- flagging so the 0.072 isn't
  read as "faster and better." Full decathlon comparison (rubble/shoves,
  the stressors `FAC_NOSTALL` actually targets) launched to see the
  intended benefit before weighing the final keep/revert call --
  `docs/rl/gait-friction-log.md`-style "revert if it destabilizes the
  gait" bar is looking live here, not hypothetical.

**Full decathlon confirms it decisively -- clear regression, not a
localized side-hill issue (20 eps/cell, matched seeds):**

- Mean fall rate nearly doubled: 10.7% -> 20.3% (wrong direction).
- Every bare-robot stalling-diagnostic cell got worse: T5.1b 23%->47%,
  T6.2b 12%->37%, T6.3b 50%->63%, T6.4b 55%->70%, T6.5b **5%->68%**.
- T9.1 (18deg slope, beyond training ceiling) -- resid30's own headline
  fix over the 22deg baseline -- completely undone: **0%->68%** falls.
- Payload-on cells mostly held (0% falls both) -- consistent with
  payload masking the real signal; the damage concentrates exactly where
  the true stability picture lives (bare-robot, past-training-envelope
  cells).

**Diagnosis before deciding round 2:** the likely culprit is the fix
built for the `TERRAIN_FEATURE` dependency, not `FAC_NOSTALL`'s core
mechanism. The one validated precedent (Phase D) had the breakthrough
bonus firing only on a *vision-confirmed* obstacle -- rare, specific. The
standalone "was stalled" trigger built this session fires on *any* recent
stall -- far more frequent, plausibly creating a "push hard and risk
falling" incentive through ordinary locomotion generally (breakthrough
pays a real +8 bonus; the penalty was accruing regardless of outcome),
not just at real obstacles the way the validated version was scoped.

**`nostall_r2` launched** -- `FAC_NOSTALL=22` unchanged, `FAC_NOSTALL_BONUS`
`8 -> 0` (penalty only, no breakthrough bonus, isolating the bonus as the
suspected instability source). PID 90156, fresh run, smoke-tested clean.
Round 2 of this lever's two-round budget -- if this also regresses,
`FAC_NOSTALL` reverts to 0 and the resiliency campaign's anti-stall fix
becomes a documented negative result, same standard as every other failed
lever this session. Ledge-recovery training stays gated and un-launched
either way until this resolves.

### Round 2 result: same failure, hypothesis refuted -- FAC_NOSTALL reverted, campaign lever closed

Completed 2026-09-18, 3,014,656 steps, converged (`approx_kl` ~0.0007).
Side-hill re-check (12deg sustained cross-slope, 12 episodes, matched seeds):

| Checkpoint | Falls |
|---|---|
| `run20m_resid30_ppo` (baseline) | 5/12 (42%) |
| `nostall_r1` (penalty + bonus) | 12/12 (100%) |
| `nostall_r2` (penalty only, bonus=0) | 12/12 (100%) |

Identical failure with the bonus fully removed -- round 1's diagnosis (the
standalone-trigger fix on the bonus was the culprit) is refuted. Didn't
re-run the full decathlon for round 2: the side-hill result alone already
matches round 1's severity exactly, and round 1's decathlon already
confirmed the same broad pattern (fall rate nearly doubled, T9.1 undone)
-- re-confirming that again wasn't going to change the decision, so
skipped the ~20-25 min it would have cost.

**Real mechanism, on reflection:** `FAC_NOSTALL`'s dense bleed penalty
applies constant pressure against dropping below a speed floor, with no
way to distinguish "giving up unnecessarily" (the actual target failure
mode) from "correctly slowing down to stay balanced under sustained
difficulty" (necessary, safe behavior). R12's own original finding is
that even the *unmodified* baseline gait needs roughly a 73% speed drop
on a sustained side-hill to stay upright -- `FAC_NOSTALL` structurally
fights exactly that legitimate slowdown, regardless of whether the bonus
is present. The problem was never the bonus; it was the always-on penalty
itself being too blunt an instrument for this specific stressor.

**Two non-improving rounds -- `FAC_NOSTALL` reverted to 0
(`FAC_NOSTALL_BONUS` back to its original default 8, moot while
`FAC_NOSTALL=0`).** Documented negative result, same standard as gait-
friction's four failed levers. The R-series backlog's "stalling not
falling" diagnosis stands -- what doesn't hold up is this specific fix
for it, at least not as a blanket, always-on reward term with no way to
tell a real stall apart from a necessary slowdown.

**Consequence for the queue: ledge-recovery training does not unlock.**
It was explicitly gated on `FAC_NOSTALL` clearing this exact bar, per the
Phase 4a precedent (training ledge exposure without a working anti-stall
fix in place already made things worse once). That gate was never cleared
-- ledge-recovery (and the R4 step-up direction folded into it) stays
queued but un-launched, pending either a genuinely different anti-stall
approach in a future campaign, or a decision to attempt it without one
and accept the Phase 4a risk knowingly.

**Remaining resiliency queue, updated:** R8 (command dynamics) and
`JOINT_OFFSET_DEG` (check `robustness_sweep.py` coverage first) are both
still live -- neither depends on `FAC_NOSTALL`. Moving to those next.

### R8 (command dynamics) and JOINT_OFFSET_DEG -- both clear, resiliency campaign wraps

**R8** (`resilience_command_dynamics.py`, 15 episodes/mode, `run20m_resid30_ppo`):
0% falls across all four modes (reverse-slam, yaw-slam, stop-start,
sustained-arc). The gait is robust to aggressive command transitions.
Sustained-arc heading drift (0.56 rad) reconfirms the already-known G4
finding (turning dropped from the curriculum, `TRAIN_YAW_RANGE=0`) --
expected, not a new issue.

**`JOINT_OFFSET_DEG`** -- checked `robustness_sweep.py`'s existing
coverage before building anything new, as planned. Already fully covers
it: 0-8deg (16 seeds), 0% falls at every value, no degradation flagged
(`degrades: false` throughout), only minor speed reduction (~7-9% at
worst). Same sweep confirms `payload_mass_g`, `cmd_latency_steps`,
`imu_noise`, and `torque_cutback` all hold clean too, up to 0.8 (80%
torque cutback) on that last axis -- a broadly reassuring robustness
picture across every axis this tool covers. No new test needed.

## Resiliency campaign status: effectively complete

- `FAC_NOSTALL` -- tried, twice, reverted. Documented negative result.
- Ledge-recovery training -- gated on the above, never unlocked. Stays
  queued, not run.
- R4, R10 (carpet) -- folded into other items (R4 into the un-launched
  ledge round; R10 deferred to hardware, `hardware-gated-backlog.md` H10).
- R2, R9, `STUCK_FOOT`, `RUBBLE` -- dropped this pass, tooling kept.
- R8 -- clear.
- `JOINT_OFFSET_DEG` -- already covered, clear.
- `benchmark_resiliency.py` -- moved to backlog, not built.

Moving to the slope-ceiling campaign next.
