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

## Rounds

(none yet -- queued behind resid30 and gait-friction)
