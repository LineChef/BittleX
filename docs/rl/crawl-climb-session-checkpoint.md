## UPDATE 3 (same resumed session): BREAKTHROUGH -- drag+probe rear-leg mechanism, tail push eliminated

This is the biggest architectural change of the whole session, driven by a
sequence of increasingly specific user observations from watching the
reference climb closely:

1. "Use the front legs to drag the back legs forward like the scripted gait
   does" -- decoupled rear-leg stepping from every cycle; front-pull alone
   drags the body (rear legs held firm/extended) between steps.
2. "If they are bent when the front legs try to drag them forward it will
   destabilize the stance... they need to be almost fully extended" --
   confirmed the rear legs already stay extended during drag (pull phase
   never touches rear joint angles; held at firm force 2.5).
3. "After the back legs are dragged forward, one leg kicks forward till it
   encounters the ledge and plants there, then the other foot is now close
   enough to step up" -- this is the single biggest insight: the rear legs
   shouldn't do an invented "stepping shape" at all. They should use the
   SAME validated probe-and-plant mechanism the front legs already use
   (reach forward, search down, confirm real contact) once close enough.
4. "After the second leg steps up... one front leg on the same side that
   just swung forward steps forward too, to gain more leverage" -- added:
   once a rear leg plants, immediately advance the same-side front leg
   (naming convention: PAW_LF/RF/RB/LB = Left-Front/Right-Front/Right-Back/
   Left-Back, so pairs are (LF,LB) and (RF,RB)).
5. "The back legs tuck the lower leg in tight, THEN the top part swings
   forward, THEN only then does the lower leg swing down to propel the
   body forward" -- replaced the cmh-swing-shape blend entirely with an
   explicit 3-phase sequential motion: TUCK (knee flexes in tight, hip
   fixed) -> SWING (hip rotates the still-tucked leg forward, knee fixed)
   -> EXTEND (knee straightens back out, the actual power stroke, held at
   2x force since it's doing real work against the ground).

**Bug found and fixed along the way**: the swing-hip direction was
initially backwards -- body_x DECREASED through tuck/swing/extend every
cycle, getting worse each time (traced directly via phase-by-phase
diagnostic prints, exactly as the user asked -- "work through each part one
by one"). Flipping the sign (`--swing-hip-deg` default changed from +28 to
-28) immediately reversed this: body_x began climbing steadily every phase.

**Also found**: the probe-attempt check only ran at the TOP of each cycle
using the PREVIOUS cycle's position, so the very last cycle's progress
(which finally closed the gap) never got checked before the loop exited.
Added one more probe attempt right after the main loop, on the final
position, as a fix.

**Also found**: `--rear-step-every 3` (matching "drag mostly, step
occasionally" literally) never let the body get close enough to trigger the
probe-attempt threshold (80mm) at all within `n_cycles` -- pure front-pull
drag alone plateaus far short (~145mm, WORSE than the old swing-shape
stepping) because the rear legs are still bearing real weight/friction after
the extend phase and actively resist being dragged. Stepping EVERY cycle
(`--rear-step-every 1`) is what's actually needed; "drag" happens within
each step's tuck+swing phases (foot lifted, not gripping), and the
propulsion comes from the extend phase's power stroke, not from passive
dragging between separate steps.

**Result: this is the best outcome of the entire session.** 5/5 test seeds
(7000, 7002, 7003, 7005, 7006) all converge to 4/4 within exactly 3 cycles
(RB plants at cycle 2, LB at cycle 3), tilt tightly clustered 9.5-9.7 deg,
**the explosive tail push is skipped entirely** -- both rear legs plant via
genuine probe-verified contact (37-41mm past the edge, real margin) before
the tail phase ever runs. This directly solves the core "looks like a jump"
problem that's been the session's central open issue since it was first
quantified (the 130-160mm pre-tail gap). The whole climb is also much
faster now: replay dropped from ~150s (40 cycles of swing-shape stepping)
to ~55s (3-4 cycles of tuck-swing-extend).

**New defaults set**: `--rear-step-every 1` (was 3), `--n-cycles 15` (down
from 40 -- real safety margin above the observed 3-4 cycle convergence,
without wasting runtime on a now-unnecessary large cap). New CLI args:
`--tuck-knee-deg` (default 45), `--swing-hip-deg` (default -28).

Replay regenerated and verified (`/Users/markjohnson/Desktop/crawl_climb.gif`,
seed 7000, 909 frames, 0 corrupted, tilt 9.6, 4/4, no tail).

**Not yet re-tried on this new mechanism**: the 60mm reach margin, -8deg
initial RB lean (both still pending, now on top of an entirely different and
much better baseline than when they were last tried). Also not yet checked:
whether `TUCK_KNEE_DEG=45`/`SWING_HIP_DEG=-28` are actually tuned optimally,
or just the first values that happened to work -- there may be room to
smooth the motion further or reduce tilt below 9.5 deg with a proper sweep.

---

## UPDATE 2 (same resumed session): jerkiness root-caused + fixed, seed 7003 plateau resolved as a side effect

User's diagnosis: jerky transitions between movements were knocking already-
solid front footing off the platform, forcing the sequence to restart. Two
fixes:

1. **`_with_front_ik` rate-limited** (`RATE_LIMIT_DEG=4.0` per call): even
   though the anchor target is static, PyBullet's IK solver can jump between
   qualitatively different joint solutions near some configurations -- a
   real discontinuous snap despite a continuous cartesian target. Clamping
   the per-call change to 4deg keeps convergence (still reaches the true
   anchor, just gradually) without permitting the snap.
2. **Root cause of the shallow-footing vulnerability, separately diagnosed
   by the user**: our footholds land right at the edge (many contacts under
   15mm past the edge, several outright negative/marginal) while the
   reference gait plants noticeably deeper -- a shallow foothold has almost
   no margin before ANY perturbation (jerky or not) knocks it loose. Added a
   post-contact "slide deeper" step to `probe_leg_onto_platform`: once first
   contact is found, explicitly slide the foot forward
   `SLIDE_DEPTH_M=0.025` (25mm) along the now-known-safe surface (stops
   early if it detects sliding off the platform edge) instead of settling
   for wherever first contact happened. This directly counteracts the
   earlier-documented "2-DOF IK retreats in x as it searches deeper" effect
   -- first contact was already known to land shallower than intended;
   this recovers depth afterward instead.

**Result, 3-seed validation (step_scale=1.3, n_cycles=40, margin=0.10)**: all
3 now 4/4 with contact margins mostly 10-48mm (vs. many under 15mm or
negative before). **Seed 7003's plateau (previously stuck at 122-131mm
PRE-TAIL regardless of scale/cycles) is resolved as a side effect** -- now
29-47mm PRE-TAIL, tilt 8.8, 4/4. Likely explanation: shallower/failed
footholds were wasting replant cycles on marginal contacts that didn't hold,
so deeper contacts let the crawl loop make more consistent progress.

Replay regenerated and verified (`/Users/markjohnson/Desktop/crawl_climb.gif`,
seed 7000, 2514 frames, 0 corrupted, tilt 16.8, 4/4).

**Note**: the rate limiter was tested once in isolation BEFORE the slide-
deeper fix and caused a flip on one seed + a near-failure on another --
don't assume the rate limiter alone is safe; it's only been validated
together with the slide-deeper fix, not separately. If either needs to be
reverted independently later, re-test both combinations.

**Still not re-tried on this new baseline**: the 60mm reach margin and -8°
initial RB lean (both still pending re-addition, now on top of this even
better baseline).

---

## UPDATE (resumed session, same week): STEP_SCALE sweep resolved

Picked back up from "Next steps" item 1. Exposed `--step-scale` and
`--n-cycles` as real CLI args (were hardcoded). Verified the `STEP_SCALE=1.0`
baseline first (matches this doc exactly: 4/4 x3 seeds, but PRE-TAIL
145-162mm, tilt 23.5 -- confirmed the revert was clean).

Swept `step_scale` in {1.3, 1.6, 2.0, 2.5} x `n_cycles` in {16, 24}, seed
7000. **Counterintuitive finding**: 1.6-2.5 all plateau around a 130-140mm
pre-tail gap regardless of scale -- MORE amplitude doesn't help past a point.
But **1.3 gave by far the smallest gap (58-93mm)**, at the cost of not yet
reaching 4/4 (insufficient distance) at only 16-24 cycles. Extended cycle
count at scale=1.3: 32 cycles -> 46-70mm, tilt 3.7 (4/4); 40 cycles -> 36-61mm,
tilt 9.6 (4/4); 48 cycles -> 22-49mm but tilt climbing to 17.2 (diminishing
returns starting). **`step_scale=1.3, n_cycles=40` is the new sweet spot.**

3-seed validation at 1.3/40: seed 7000 -> 61/36mm, 4/4, tilt 9.6. Seed 7002 ->
61/47mm, 4/4, tilt 7.2. **Seed 7003 plateaus at 122-131mm regardless of more
cycles (tried 32/40) or higher scale (tried 1.4, 1.5)** -- traced directly:
from cycle ~15 onward this seed's per-5-cycle-block net progress is
essentially zero (each replant resets to ~the same position, next block just
regains the same lost ground, no net gain) -- a genuine steady-state specific
to this seed's geometry, not a slow-but-real convergence. Not yet resolved;
not blocking, since 2/3 seeds now show a qualitatively different climb (way
less reliance on the tail's jump: body_x at push-done time dropped from
~0.45-0.56 to ~0.05-0.09 for the converging seeds).

**Set as new defaults**: `--step-scale 1.3` (was hardcoded 1.6), `--n-cycles
40` (was 16). Replay regenerated and verified
(`/Users/markjohnson/Desktop/crawl_climb.gif`, seed 7000, 2452 frames, 0
corrupted). **Not yet re-added**: the 60mm reach margin and -8° initial RB
lean (checkpoint's next-steps item 3) -- still pending, now on top of this
new, better baseline instead of the old one. Seed 7003's plateau is a good
candidate for the NEXT isolated investigation once those are re-added.

---

# Crawl-climb session checkpoint (2026-09-19, saved at 97% weekly usage)

Read this before touching `rl_training/opencat-gym/crawl_climb.py` again. It
picks up mid-iteration -- the mechanism is NOT in its best-known-good state
on disk right now (see "Exact state on disk" below), and the immediate next
step is already identified.

## Where this session landed, in one paragraph

We proved climbing a step-up ledge is simulatable at all (earlier finding:
`cmh`'s own front-leg reach was the blocker, not sim fidelity -- see
`docs/rl/foot-probing-log.md`, though that file's own closing verdict predates
this reversal and hasn't been updated to match). Built `crawl_climb.py`: probe
FL+FR onto the platform (reusing the validated probing skill), then a
periodic front-knee-pull + rear-leg-step crawl loop, then `cmh`'s real tail
(166-171) as a push-off, then probe RB+LB. Got a real, ground-truth-verified
4/4 (all four paws solidly on the platform) repeatably (6/7, then 3/3 seeds
at the best-tuned approach distance). Then spent the rest of the session on
motion QUALITY: the numeric successes looked bad on replay (squatting,
jerky, a "jump" at the end instead of a controlled step) -- user's diagnosis,
confirmed empirically, was that the approach distance was off, which cascaded
into everything else looking wrong.

Tonight's thread (after the last context compaction): user asked for a
"middle ground" between pure scripted `cmh` and our fully-reactive mechanism,
same architecture as the walk gait (scripted base + bounded residual). Then
watched the reference PetoiCamp climb video
(https://www.youtube.com/watch?v=rRkVR3PO1o8) side by side with our replay
and gave five concrete, correct critiques (see below). Iterated hard on
matching those. **Bottom line finding, confirmed with a direct measurement
tonight**: our "successes" have been relying on the tail's explosive push
(`cmh` ticks 166-171, force ramped to 6.5) to do the real work of closing
the front-to-rear gap -- i.e. a jump, not a climb. Measured directly:
**before the tail phase even starts, RB is still 132-162mm behind the edge**
depending on cycle count. The tail closes on the order of 150-185mm of that
in one burst. This is the root of the "looks like a jump" complaint that's
been raised since early in the session, now root-caused precisely.

## The reference-video critique (user's 5 points, verbatim intent)

Watching https://www.youtube.com/watch?v=rRkVR3PO1o8 vs. our replay:

1. It reaches way farther for the ledge before committing (front legs).
2. The rear legs are almost fully extended for the entire first part of the
   climb -- gives leverage.
3. It pulls itself closer to the ledge with the back feet REMAINING
   EXTENDED (not squatting/bending) -- the pull leverage comes from the tall
   stance itself, not from a knee-flex squat.
4. One rear leg stays fully extended (support/height) while the other
   steps, alternating -- not both rear legs moving together.
5. The overall stance is much taller throughout the whole attempt, not just
   briefly.

User's key reframing mid-session: **the tall stance is not cosmetic -- it IS
the leverage mechanism** (an extended leg rotating at the hip is a longer,
more effective lever than a bent one). And: **get both front feet solidly
planted BEFORE standing tall** (sequencing) -- tall stance should be the
thing that gets the rear legs up WITHOUT needing the final tail jump, which
so far is the only way we've reliably gotten all 4 paws on top.

## What was tried tonight, and what happened (all empirically tested, not guessed)

1. **Bounded residual (walk-gait-style) toward `cmh`'s own trajectory,
   replacing full IK override for front-leg anchoring.** Isolated test
   (`crawl_climb_residual.py`, new file) showed this alone is stable but
   gives near-zero body advance -- confirmed directly (also independently,
   via `cmh_flatground_test.py` from earlier in the session): `cmh`'s own
   loop barely advances the body at all (~44mm across the WHOLE 172-tick
   sequence on flat ground). So a bounded residual toward `cmh`'s raw
   trajectory cannot be the propulsion source by itself.
   - Applying the same bounded residual (±30°) to the PROVEN crawl loop's
     front-leg anchoring: broke reliability (2/4, propulsion stalled) during
     the rear-leg swing, and broke it worse (2 of 3 seeds flipped) during the
     tail's high-force push -- a ±30° bound can't track a fast-moving anchor
     requirement tightly enough during dynamic phases. **Verdict: bounded
     residual is not a safe replacement for full IK override anywhere in the
     current pipeline's dynamic phases.** Reverted everywhere.

2. **Rear-leg extension-for-leverage phase**, added right after FL+FR are
   secured (matches user's point 2 + the "plant front feet before standing
   tall" sequencing): rear hip +35°, rear knee +20°, force-ramped in
   (1.0->3.0 over 40 steps, not a snap). **This one is a clean, validated
   win** -- kept it. Result: same 3/3 seeds, but tilt dropped from ~16-22° to
   ~7.6-9.1°, and RB started essentially AT the edge instead of up to 54mm
   behind. This is currently the only unambiguous improvement from tonight
   still active in the pipeline.

3. **Rear legs replay `cmh`'s own real swing shape** (decoded directly from
   `_BASE`: RB_HIP dips ~20->10° / RB_KNEE lifts ~23->41° between ticks
   39-45) instead of the original hand-built flex-30°-then-flex-18°-then-reset
   motion. Two bugs found and fixed along the way:
   - Absolute snap to `cmh`'s raw tick values caused an instant ~40° jump
     (rear-extend phase leaves the legs far from `cmh`'s own baseline) ->
     flipped every seed. Fixed: use RELATIVE deltas from wherever the legs
     currently are.
   - Using the FULL 6->60 loop (includes `cmh`'s "stance/push" portion)
     under a RIGID front anchor reproduced the session's own earlier-logged
     "rigid anchor + rear push rotates the body instead of translating it"
     failure -- flipped by cycle 1, every seed. Fixed: use only the
     swing/place portion (ticks 39-60), and even then only the KNEE returns
     to baseline after each step -- the HIP stays at its swept-forward
     position (matches the ORIGINAL hand-built version's own asymmetry, and
     is what gives a real net step instead of zero net progress -- confirmed:
     a full hip+knee reset left RB 130mm+ BEHIND the edge).
   - Result with this fix (synchronized, both rear legs together, matching
     `cmh`'s own near-in-phase timing): **validated 4/4 across all 3 test
     seeds**, tilt 9.1-9.4°, but with a large (235-315mm) overshoot past the
     edge -- meaning way more propulsion than needed, at the cost of not
     looking much like a controlled step.

4. **Alternating single-leg stepping** (user's point 4: one leg extended
   while the other steps). Implemented (cyc%2 alternation, firm
   `SUPPORT_FORCE` on the planted leg). **Tried extensively, never got it to
   work reliably**, in multiple isolated configurations:
   - Alternating + reduced squat depth (matching "stand taller," point 5):
     propulsion collapsed (net negative body_x, RB ended 116-152mm BEHIND
     the edge -- worse than doing nothing).
   - Alternating + FULL restored squat depth (30°/6°, the proven values),
     original reach margin, no other changes: still only 0-2/4 across seeds.
   - More cycles to compensate for alternating halving each leg's step
     frequency: eventually flips (tilt hits 180°) rather than converging --
     a narrow, brittle window between "not enough" and "flips," not a clean
     tradeoff curve.
   - **Verdict: reverted to synchronized (both rear legs together) as the
     reliable baseline.** Alternating is worth revisiting, but needs to be
     tried as an ISOLATED single change from a clean baseline, not layered
     with 3-4 other simultaneous changes the way tonight did it (a repeated
     lesson this session -- isolate one variable at a time).

5. **Farther front-leg reach margin** (point 1): swept directly.
   45mm (original) works. 60mm is the largest value that still finds
   contact reliably. 75mm exceeds the leg's physical reach envelope
   entirely (zero contact, every time). **60mm is a validated, safe
   increase** but was reverted tonight only because it was entangled with
   the other simultaneous changes during debugging -- worth re-adding once
   the rest of the pipeline is stable again.

6. **Initial single-leg lean during FL's probe** (matches "one leg fully
   extended to lean the body" for the very first foot placement -- a NEW
   observation from the user, distinct from point 4's alternating-during-
   stepping): extend RB_HIP during FL's own probe via the existing
   `weight_shift` mechanism (negative shift_deg = extend, not the existing
   FR-probe usage which tucks legs forward). Swept magnitude: -8° works
   (FL still finds contact), -10° breaks FR/LB later in the pipeline, -15°
   breaks FL's own reach outright. **-8° is the validated safe ceiling** but,
   like the reach-margin change, was reverted during tonight's isolation
   pass and needs to be re-added and re-tested cleanly.

7. **Hip-rotation push** (a direct test of the user's "tall stance IS the
   leverage" reframing): after the rear-extend phase, apply `cmh`'s own
   stance/push delta (ticks 6-21, RB_HIP 31->46°ish) as a ONE-TIME rotation
   with the front rigidly anchored on the now-ELEVATED ledge (reasoning:
   unlike the earlier flat-ground rigid-anchor-rotation failure, rotating
   around an ELEVATED anchor should lift the body, not just spin it).
   **Result: negligible** (body_x moved only ~4mm). The rear leg is already
   too close to its useful range limit after the extension phase for
   further hip rotation to generate real thrust. Removed -- not worth the
   complexity for zero measured benefit. (This doesn't mean the reframing is
   wrong, just that this specific implementation of it didn't pay off --
   see "Next steps" for a better-targeted way to test the same idea.)

## The core open problem (this is the actual thing to solve next)

Direct measurement, current reverted/stable configuration (synchronized
rear-leg stepping, full squat depth, 45mm reach, no initial lean, margin
0.10, 16 cycles): **PRE-TAIL, RB is 152mm and LB is 162mm behind the edge.**
The tail's explosive push closes most of that gap in one burst -- this IS
the "jump" the user has been correctly calling out since early in the
session, now precisely quantified.

Tried extending the crawl loop's own cycle count to close this gap without
the tail's help:
- 16 cycles (baseline): 152mm behind
- 24 cycles: 132mm behind
- 32 cycles: 87mm behind
- 40 cycles: 68mm behind, but tilt starts climbing (16-18° vs ~4-7° earlier
  in the run) -- diminishing returns AND rising instability, not a clean
  path to zero.

Started testing a **step-amplitude scale** (`STEP_SCALE` multiplier on the
relative-delta swing, currently `1.6` in the on-disk file) as a way to close
more distance per cycle instead of just adding more cycles. **First result,
INCOMPLETE**: 16 cycles at `STEP_SCALE=1.6` gave 137mm/139mm behind -- only
marginally better than the unscaled 16-cycle baseline (152/162mm), far less
improvement than hoped. This was the very last thing running when the
session was checkpointed -- not yet concluded, not yet tried at higher
cycle counts or higher scale values, not yet checked for flip risk.

## Exact state on disk right now (important -- do not assume "last good")

`rl_training/opencat-gym/crawl_climb.py` is CURRENTLY in a mid-experiment
state, not the best-known-good state:
- `STEP_SCALE = 1.6` is active in the rear-leg swing (mid-test, inconclusive
  per above).
- Reach margin is back to the original `0.045` default (60mm reach was
  reverted).
- No initial-lean weight_shift on FL's probe (the -8° lean was reverted).
- Rear-leg stepping is SYNCHRONIZED (both legs together), not alternating.
- Squat depth is back to the full proven values (`PULL_DEG_PER_CYCLE=6`,
  `MAX_KNEE_FLEX_DEG=30`).
- `SUPPORT_FORCE=1.0` (soft, matching the original working value -- the
  firmer `2.5` was tried and reverted, see finding 2 above... actually see
  the walkthrough: firmer holding force increased propulsion enough to
  destabilize the tail in a narrow, unpredictable way).
- A new sanity guard was added to the final report: a flip (tilt > 68.8°)
  now always reports `0/4`, even if paw height/x position would otherwise
  have looked like a false-positive "4/4" (this happened twice tonight --
  a robot flipped onto its back can still coincidentally satisfy the
  paw-position check). **Keep this guard permanently regardless of what
  else changes.**
- A `PRE-TAIL` diagnostic print was added right before the tail phase,
  reporting RB/LB distance behind the edge at that point. **Keep this too**
  -- it's the key instrument for measuring whether a change actually
  reduces jump-reliance, not just final on-top count.

**A known-good, fully validated checkpoint (before tonight's reference-video
round) still exists**: `crawl_climb_checkpoint_4of4.py` (first-ever 4/4,
before any style iteration) and the git-uncommitted state reachable by
setting `SUPPORT_FORCE=1.0`, synchronized stepping, `STEP_SCALE=1.0`,
reach=0.045, no lean, squat=30°/6° -- this combination was directly
confirmed 4/4 on all 3 test seeds (7000/7002/7003) with tilt 9.1-9.4°
earlier tonight, before the amplitude-scale experiment started. If picking
this up fresh, set `STEP_SCALE = 1.0` first to get back to that known point,
verify it, THEN resume the amplitude/cycle-count experiment from a clean
baseline.

## Next steps, in priority order

1. **Finish the `STEP_SCALE` experiment properly**: set `STEP_SCALE = 1.0`,
   confirm 4/4 x3 seeds still holds (sanity check the revert was clean).
   Then re-sweep `STEP_SCALE` (try 1.3, 1.6, 2.0, 2.5) x cycle count (16,
   24) together, watching the `PRE-TAIL` diagnostic as the real metric (not
   final on-top count, which the tail can paper over) -- goal is PRE-TAIL
   distance near zero, with tilt staying low, so the tail becomes a gentle
   finishing step instead of the whole mechanism.
2. Once PRE-TAIL distance is small without the tail's help, consider
   whether the tail phase can be weakened (lower `PUSH_FORCE`, or skipped
   entirely and replaced with one more probe-and-step cycle) -- this is the
   actual test of "no more jumping."
3. Re-add the two validated-in-isolation wins that got reverted during
   tonight's debugging: 60mm reach margin, -8° initial RB lean during FL's
   probe. Add them ONE AT A TIME to the STEP_SCALE-tuned baseline, testing
   3 seeds after each, not together.
4. Revisit alternating single-leg stepping (user's point 4) as an isolated
   experiment from the STEP_SCALE-tuned synchronized baseline -- now that
   there's a working amplitude lever, alternating might no longer need to
   sacrifice as much total propulsion to look right.
5. Patch the still-unfixed GIF duration-list bug in `probe_ledge_up.py`,
   `probe_foot_gif.py`, `probe_then_climb.py`, `cmh_flatground_test.py` (only
   `crawl_climb.py` got the byte-distinct-frame + constant-duration fix).
6. Clean up now-vestigial code: `crawl_climb_residual.py` (the isolated
   bounded-residual test, superseded, kept for reference), the dead code
   block after `raise SystemExit` in `crawl_climb.py`.
7. Nothing from this session has been committed. No commit has been
   requested.

## Files from this session (all uncommitted)

- `rl_training/opencat-gym/crawl_climb.py` -- the live, actively-iterated
  script. See "Exact state on disk" above before touching it.
- `rl_training/opencat-gym/crawl_climb_checkpoint_inprogress_20260919.py` --
  literal snapshot of `crawl_climb.py` taken at the moment this checkpoint
  was written (mid-`STEP_SCALE` experiment). Use this to diff against if
  `crawl_climb.py` gets edited further before this is read again.
- `rl_training/opencat-gym/crawl_climb_checkpoint_4of4.py` -- the FIRST
  validated 4/4, before any style iteration (margin=0.085, original fast
  tail). Oldest, most conservative fallback.
- `rl_training/opencat-gym/crawl_climb_residual.py` -- isolated test of
  bounded-residual-toward-`cmh` (walk-gait-style architecture). Confirmed
  stable but insufficient propulsion on its own. Reference only.
- `rl_training/opencat-gym/cmh_flatground_test.py` -- plays raw `cmh` on
  flat ground; proved the sequence itself doesn't flip AND barely advances
  the body (~44mm total), a key finding used repeatedly tonight.
- `docs/rl/foot-probing-log.md` -- earlier session log (probing validation
  through the first working crawl controller + GIF bug). Its own closing
  verdict on B13 predates and is superseded by the actual working crawl
  controller -- not yet corrected in that file.
- Desktop GIFs (`crawl_climb.gif`, `crawl_climb_residual.gif`,
  `crawl_climb_ending.gif`) -- all stale relative to tonight's in-progress
  state; regenerate once a new reliable configuration is confirmed.

## Standing instructions for whoever picks this up

- User has stated firmly, repeatedly, this session: never frame a check-in
  as "should we stop/pause here" during active iterative work. Report
  status, decide the next step, keep executing. (Saved to persistent memory
  as `feedback_never_ask_to_stop`.)
- Isolate one variable at a time. Tonight re-learned this lesson the hard
  way (stacking alternating + reduced squat + firmer force + farther reach +
  initial lean all at once made every failure ambiguous to diagnose).
- Trust the `PRE-TAIL` diagnostic and the tilt-gated final-result guard over
  a bare "N/4 on-top" number -- both false-positive failure modes (a flip
  reading as 4/4, a jump reading as a controlled climb) already bit this
  session once each.
