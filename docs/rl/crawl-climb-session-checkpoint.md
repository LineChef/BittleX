## SESSION PAUSE NOTE (2026-09-19): resume-here summary

Session paused after UPDATE 12 below. User is confident this is gettable and
wants to resume without re-deriving anything already learned. Read this note
first, then UPDATE 12/11 for full detail.

**Current committed state**: `crawl_climb.py` == commit `9de2f06` on branch
`auto-gait-iteration`. This is the "quality over raw reliability"
lead-margin checkpoint: front-leg pull uses a geometric under-body-margin
stop (`UNDER_BODY_MARGIN_M = 0.04`), rear legs use SYNCHRONIZED (not
alternating) TUCK->SWING->EXTEND. Reliable (4/4) on seeds 7000/7002/7003;
KNOWN to flip on 7005/7006 -- this is a deliberate, user-approved trade
(motion quality over raw pass rate). Do not "fix" this by reverting to an
earlier, more-reliable-but-worse-looking version without asking first --
see UPDATE 11's quality-over-reliability decision.

**Comparison replay GIFs published as a web page** (so no local file-path
issues): https://claude.ai/artifact/QSof1bujRj3NPMf1LDZC2B -- seed 7005
(succeeds under the walking+lead-margin combo) and seed 7000 (flips under
the same combo at cycle 3). Underlying local files, if needed again:
`/Users/markjohnson/Desktop/crawl_climb_combo_success.gif` and
`crawl_climb_combo_fail.gif`.

**What's actually unresolved, i.e. where to pick back up**:
1. The user's direction ("back legs walking forward while front legs pull
   forward, in concert, at the right speed") has been tried twice and is
   NOT yet a clean win -- see UPDATE 12, point 1. It's a genuine trade
   (fixes 7005/7006, breaks 7000/7002), not an improvement, in both the
   sequential and concurrent-timing forms tried so far.
2. Concurrent (same-physics-step) timing of the front pull and rear tuck
   has failed decisively TWICE on two different baselines (0/5 total
   failure once, 1/4 and 2/4 incomplete the second time) -- see UPDATE 12,
   point 2, for the specific suspected causes (ad hoc shared force value of
   1.5; possible force interference between the two motions on
   overlapping/adjacent joints within one physics step). Don't retry the
   same merged-loop implementation without addressing one of those first.
3. **Untried lever, flagged directly by the user and never yet varied in
   isolation**: step SPEED / phase duration timing. Every experiment so far
   varied amplitude (how far the rear leg tucks/swings) or leg-selection
   logic (which leg steps when), never how FAST each phase executes. The
   user's own words: "the speed at which this step takes place is gonna be
   what makes or breaks this approach." This is the most promising next
   thing to try that hasn't been tried yet.
4. Standing practices to keep following: validate any change against the
   full 5-seed set (7000/7002/7003/7005/7006) before trusting it, not a
   subset (see `feedback_seed_testing_breadth` memory); always keep a
   verified checkpoint to revert to; quality (does it visually match the
   reference climb) beats raw pass-rate as the deciding factor when the two
   conflict (see UPDATE 11); give the user any new replay link FIRST, before
   reviewing frames myself (see `feedback_review_replay_myself` memory).

---

## UPDATE 12 (same resumed session): rear-leg walking + concurrent pull/step timing, tried on the promoted checkpoint -- both negative

Two more direct user-requested experiments tried on top of UPDATE 11's
promoted checkpoint (lead-margin front pull):

1. **Rear-leg walking gait** (true alternation, 0.75x per-step amplitude,
   same as tried before but now layered on the lead-margin baseline instead
   of the 5-seed-reliable one): genuinely interesting but NOT a clean win --
   it's a real trade, not an improvement. Seeds 7005/7006 (which FAILED
   under lead-margin alone) now SUCCEED with this combination. But seeds
   7000/7002 (which succeeded reliably under lead-margin alone) now FLIP.
   Different failure pattern, not strictly better. Replays saved for
   comparison: `/Users/markjohnson/Desktop/crawl_climb_combo_success.gif`
   (seed 7005, succeeds) and `crawl_climb_combo_fail.gif` (seed 7000,
   flips at cycle 3) -- both on Desktop.
2. **Concurrent pull+rear-tuck timing** ("in concert," merging the front
   pull and the stepping leg's tuck phase into one shared loop instead of
   fully sequential) -- tried TWICE now on two different baselines. First
   attempt (on the narrower 25mm-margin, non-alternating baseline): 0/5,
   total failure, every seed ended with the body flush against the ground.
   Second attempt (on THIS update's walking+lead-margin combination):
   1/4 and 2/4 on the two seeds tested (not even flips -- just incomplete,
   legs never all secured). **Concurrent timing has now failed decisively
   twice, on two different baselines -- this specific "merge the loops"
   implementation approach has a real structural problem, not a tuning
   issue.** Not recommended to retry the same merged-loop approach again
   without first understanding why concurrent execution breaks things that
   sequential execution (with the same underlying targets) doesn't -- likely
   candidates: the merged loop uses a softer force (1.5) than either the
   pull's own 2.5 or the tuck's own 1.0-2.0, which was an ad hoc choice, or
   the two motions' forces interfere with each other when applied to
   overlapping/adjacent joints within the same physics step in ways that
   don't show up when they're strictly sequential.

**Reverted both.** Current committed state remains `9de2f06` (the promoted
lead-margin version, no rear-leg walking, no concurrency) -- confirmed
still 4/4 on seed 7000 after both reverts.

**Bug fixed along the way (already committed, part of `9de2f06`)**: flipped
runs previously never saved their GIF at all (only captured extra frames,
then exited without ever calling the save code) -- fixed so a flip now
saves a reviewable replay, which is how `crawl_climb_walking_fail.gif` and
`crawl_climb_combo_fail.gif` were produced.

---

## UPDATE 11 (same resumed session): quality over raw reliability -- promoted the lead-margin version despite its lower pass rate

Important correction to UPDATE 10's framing. After reverting to the
5-seed-reliable `af6cb44` state and trying (and reverting) three more
experiments -- a slower/less-aggressive rear-leg walking gait, and a
concurrent front-pull+rear-tuck merge (0/5, total failure, reverted
immediately) -- the user pushed back on the premise directly: **the crude
"N/4 paws on top" + "did it flip" pass/fail check is not the same thing as
quality**, and shouldn't be treated as the automatic tie-breaker between
candidate mechanisms. Their own recollection of watching the replays: the
lead-margin version (`15df366`, reverted in UPDATE 10 for failing 2 of 5
seeds by the flip check) was subjectively the BEST-LOOKING attempt so far
-- front legs stay ahead of the body as it pulls forward, the body
genuinely stabilizes standing on the ledge for a moment, even though it
then eventually loses that stability. That's real, visible progress toward
a controlled climb that the current "reliable" checkpoint doesn't show
(the current checkpoint's front knee still collapses to ~90deg and looks
belly-down the whole time -- it just happens to keep satisfying the
numeric check while looking bad, exactly the same category of problem as
the tail-jump and the tilt-blind-to-height issues earlier this session).

**Decision, made directly by the user, not inferred**: promote `15df366`'s
content back to `crawl_climb.py` as the working baseline, ON TOP OF the two
independent safety fixes from UPDATE 10 (the `None`-anchor crash guard, and
a new fix -- flipped runs previously never actually saved their GIF, just
captured frames and exited; fixed so a flip can be reviewed too, which is
how the walking-gait failure video was produced for the user to inspect).
This is a DELIBERATE trade: known to fail (flip) on 2 of the 5 established
seeds (7005, 7006), in exchange for visibly better motion quality on the
seeds that do succeed. Re-verified 7000/7002/7003 still succeed with this
combination (tilt 19.1-19.9deg, consistent with `15df366`'s own original
numbers).

**Process lesson, stated plainly**: UPDATE 10's "always keep a 5-seed-
verified checkpoint" instinct was sound and stays the standing practice
for CATCHING regressions and knowing exactly what's safe to fall back to
-- but pass rate alone should not be the sole deciding factor for which
candidate becomes the working version going forward. When a lower-pass-
rate version is visibly closer to the actual goal (a controlled, stable
climb) than a higher-pass-rate version that "succeeds" in a way that still
looks wrong, that's worth weighing directly with the user rather than
auto-selecting on the crude metric. Keep validating broadly and keep
detailed records of exactly which commit does what (as this doc already
does) so an earlier, better-quality candidate can always be recovered and
promoted, like this update just did.

Replays for comparison: `/Users/markjohnson/Desktop/crawl_climb_leadmargin_best.gif`
(seed 7000, this promoted version, verified clean, 858 frames) and
`/Users/markjohnson/Desktop/crawl_climb_walking_fail.gif` (seed 7002, the
reverted walking-gait experiment, showing exactly how that one fails --
flips at cycle 5, tilt 179.3).

---

## UPDATE 10 (same resumed session): IMPORTANT -- reverted to the last 5-seed-verified checkpoint; testing-breadth lesson

**Critical process lesson, stated plainly because it nearly caused real
damage**: UPDATE 8 and 9's front-leg geometric-pull-stop / lead-margin /
active-replant changes were only tested on 3 seeds (7000/7002/7003) before
being committed as reliable. When the user asked for an always-available
working checkpoint (prompting a wider re-check), testing against the FULL
5-seed set this session has used throughout (adding 7005/7006) revealed
**both of those commits actually flip on 2 of 5 seeds** (166-178deg tilt,
outright failures) -- a real reliability regression that the narrower
3-seed check simply didn't catch. Bisected directly (checked out each
commit, re-ran the 5-seed set): `af6cb44` ("Investigate the full-fix
direction...", i.e. the state right after UPDATE 6's stand-up push, BEFORE
any of the front-leg pull-stop work) is confirmed 100% reliable across all
5 seeds, tilt tightly clustered 17.5-20.0deg. `cc598b9` and `15df366` (the
geometric-stop and lead-margin commits) are NOT reliable at this broader
seed set, despite passing their own narrower validation at the time.

**Action taken**: reverted `crawl_climb.py` to `af6cb44`'s content, re-added
only the one-line safety fix from UPDATE 9 (a `None`-check in
`probe_leg_onto_platform`'s `_with_anchors` so a leg that never found the
platform can't crash `calculateInverseKinematics` -- this fix itself
doesn't change behavior when anchors ARE valid, and was re-verified safe
on 3 seeds before committing). **This reverts the front-leg geometric-
pull-stop, lead-margin, and active-replant work from UPDATES 8 and 9
entirely** -- none of it is in the current committed state. The underlying
insights (stop the pull before the leg rotates past useful support;
anticipate the body's forward momentum with a lead margin) are still
believed correct and worth revisiting, but need re-implementing and
re-validating against the full 5-seed set before being trusted again, not
just 3.

**Also tried and reverted this same update**: a "natural walking gait" rear
-leg version (true alternation + smaller 0.55x per-step amplitude, per
direct user request) -- body height preservation was genuinely better when
it worked, but 1 of 5 seeds failed outright (slid off the platform) and
tilt varied 17-50deg across the others. Also tried a "smart" alternating
version that dedicates every cycle to whichever rear leg isn't anchored yet
(rather than blind cyc%2 parity) -- this FLIPPED on all 3 of its first test
seeds outright, worse than either alternative. Both reverted.

**Standing practice going forward, per direct user instruction**: always
keep a verified, working checkpoint to revert to -- test any change against
the FULL seed set this session has established (7000, 7002, 7003, 7005,
7006 at minimum) before considering it validated, not a narrower subset.
When in doubt, `git stash` + checkout a candidate earlier commit + re-run
the full seed set is a fast, cheap way to bisect exactly which commit
introduced a regression, as done here.

Current committed state (after this update): `crawl_climb.py` =
UPDATE 6's stand-up push mechanism (the tuck-swing-extend rear legs, drag
+probe front-leg finish, synchronized/no alternation anywhere, full lunge-
sized single step per cycle) + the one-line anchor-None safety fix. 100%
reliable across 5 seeds, tilt 17.5-20.0deg, front knee still ~90deg
(cosmetic-only issue, UPDATE 6's honest finding still stands).

---

## UPDATE 5 (same resumed session): standing-tilt stability recovered (knee angle still cosmetic-only)

Continued the standing-posture investigation from UPDATE 4, testing five
substantive approaches in sequence (each tested directly, not guessed):

1. Jump straight to flat-ground `STANCE` -> outright flip. Reverted (already
   in UPDATE 4).
2. Multi-stage gradual un-crouch toward a fixed knee target (25deg) ->
   avoided a flip but landed tilted 44-47deg across all 3 seeds. Reverted --
   this was the state committed at the end of UPDATE 4.
3. **Fresh front-anchor re-plant** (re-probe FL/FR with the paw already on
   the platform, `do_slide=False`, instead of trusting the stale anchor
   captured early in the climb): revealed something important -- tilt was
   ALREADY fine (9.4deg) at this point, unchanged from before any un-crouch
   attempt. **The multi-stage un-crouch in approach 2 was itself CAUSING
   the 44-47deg tilt, not fixing a real instability that already existed.**
   The ~90deg front knee is a stable equilibrium for THIS anchor -- forcing
   it to a different angle without an anchor to match is what destabilizes.
4. Tested a single isolated 5deg knee-only reduction from that stable
   baseline -- tilt immediately spiked to 22.6deg. Confirms the ~90deg
   configuration, while numerically stable, is a fragile/marginal
   equilibrium: even a small perturbation to the knee angle alone (without
   moving the foot) knocks it off balance.
5. Tried repositioning the front foot closer to the body via fresh IK
   toward a pulled-back anchor (reasoning: less horizontal reach -> less
   knee fold) -- tilt stayed stable, but knee angle got slightly WORSE
   (90.2 -> 90.8deg). Wrong lever: the real driver isn't horizontal
   distance, it's vertical -- the body sits tall (the rear legs' own
   leverage effect) while the front foot is still near platform height, so
   the knee must fold to bridge that height gap regardless of horizontal
   foot position.
6. Tried letting the REAR legs settle down slightly (undoing part of their
   own extension: -15deg hip, -10deg knee) while continuously re-anchoring
   the front feet via fresh IK, reasoning the whole body would genuinely
   lower and the front knee would un-fold as a side effect -- tilt stayed
   great (9.0-9.2deg) but the knee barely moved (90.2 -> 90.5deg). The
   4-point-anchored system is heavily over-constrained; small joint-target
   nudges don't meaningfully change the settled body geometry once all four
   feet are IK-locked in place.

**Net result**: reverted the destabilizing multi-stage un-crouch (approach
2) entirely. Current state = approach 3 (fresh anchor re-plant) + approach 6
(harmless rear settle, kept since it doesn't hurt, though it didn't
meaningfully help either). **Tilt is now consistently 9.0-9.2deg across all
3 test seeds** -- a real, substantial improvement over the 43.8-47.0deg the
previous committed state had, even though the front knee angle itself is
unchanged (~90deg) and still doesn't visually match the reference climb's
natural standing bend (frame 07). Stability is fully solved; the cosmetic
appearance is not.

**Why this is hard, stated plainly**: with all four feet IK-anchored to
fixed world positions simultaneously, the system has very little remaining
freedom -- almost every joint-space degree of freedom is already determined
by the anchor constraints, foot geometry, and gravity. Changing how ANY one
leg looks, without releasing an anchor and genuinely re-planting the foot
somewhere new (accepting a corresponding change in the body's actual
support base), just fights the other three anchors. A real fix likely needs
either (a) never letting the front knee reach ~90deg during the climb in
the first place (attempted directly in UPDATE 4 -- capping it broke anchor
tracking and caused flips, so this needs a subtler approach, e.g. capping
only in the SPECIFIC high-tilt moments where it's not actually load-bearing
rather than uniformly), or (b) a genuine final re-plant of one or more feet
to a new position chosen for a natural stance, not just an in-place angle
adjustment.

Replay regenerated and verified at this state
(`/Users/markjohnson/Desktop/crawl_climb.gif`, seed 7000, 750 frames, 0
corrupted, 4/4, tilt 9.1 -- stable landing, front knee still visually bent).

---

## UPDATE 9 (same resumed session): lead margin + active replant -- works for one cycle, erodes again after

User refined the geometric-stop insight further: stopping right at "under
the body" (the original 15mm margin) isn't enough -- the body's weight
keeps shifting forward after the pull ends (momentum, plus the rear leg's
own next action), so the foot needs to stop with a real LEAD margin still
clearly ahead of the body, the same way a walking gait plants a foot ahead
of the body's center of mass rather than directly under it.

**Two changes**: (1) increased `UNDER_BODY_MARGIN_M` from 0.015 to 0.04 (a
real 40mm lead, not just barely-under), and (2) added an ACTIVE re-plant
check at the END of every cycle (not just during the pull phase) -- since
the pull's own stop can't catch the body advancing past the front anchor
from the REAR leg's own tuck-swing-extend action, which happens after the
pull in the same cycle. If a front foot has fallen behind the margin by the
end of a cycle, it gets a fresh forward re-plant right there instead of
just being left behind.

**Result, validated on 3 seeds**: still 4/4, consistent tilt 19.1-19.9deg
(comparable to before), clearance still ~37.7mm. The lead margin genuinely
works for the FIRST cycle (confirmed in the trace: cycle 0's end-of-cycle
check triggered "FR re-planted forward," and cycle 1's own pull-phase
check showed both feet a healthy 33-42mm ahead, exactly the intended
margin) -- but by cycle 2 the margin has eroded to near-zero/negative
again, and by cycles 3-4 it's clearly negative (-37 to -44mm), with no
further "re-planted forward" messages after cycle 0. **The active replant
isn't firing reliably enough across all cycles to hold the margin
throughout** -- likely because the rear leg's own forward drag happens
continuously through the cycle, not just once, so a single end-of-cycle
check-and-correct isn't enough to keep up over multiple cycles. Reviewed
our own replay frames again post-fix -- visually similar to before,
consistent with the numbers (the final posture is governed more by where
things end up after cycles 2-4, where the margin has already eroded, than
by the correctly-held cycle 0-1 state).

**Honest state**: this is real, confirmed, directionally-correct progress
(the lead-margin concept works exactly as intended when it fires), but not
yet a complete fix -- the enforcement needs to be more persistent/continuous
across the whole cycle sequence, not just checked once per cycle boundary.
A natural next step: check and correct the margin more frequently (e.g.
after the rear-leg action specifically, in addition to after the pull), or
raise the trigger threshold so a partial erosion re-triggers a replant
before it goes fully negative, rather than only checking once at the very
end of each cycle.

---

## UPDATE 8 (same resumed session): geometric pull-stop -- real, correct fix; confirms rear-leg cycling is still the dominant lever

User's direct mechanical insight: the front-leg pull rotates the whole leg
backward as the body moves past the anchored foot (like a person pulling
themselves up and past their own planted hand) -- if it keeps retracting
PAST the point where the foot is roughly under the body, the leg stops
providing any vertical support at all and just keeps rotating toward
pointing backward. The old cap (`MAX_KNEE_FLEX_DEG`, a fixed joint-angle
budget) had no idea where the foot actually was in space relative to the
body -- it would keep retracting up to its degree budget regardless of
whether the leg had already rotated past useful support.

**Fix implemented**: a genuine geometric stop, not a joint-angle one. After
each pull sub-step, check whether either front foot's world-x position has
fallen behind (foot_x - body_x < 0.015m) the body -- if so, stop pulling
immediately for that cycle regardless of how much of the per-cycle degree
budget remains. Validated on 3 seeds: still 4/4, consistent tilt
17.2-18.0deg, the stop fires reliably (visible directly in the printed
trace) and does NOT prevent RB/LB from reaching the platform (confirmed
directly: the pull's real job, per the user, is just to move the body
forward enough for the rear foot's swing to reach the ledge, not to hold a
permanent support pose -- this still happens fine with the stop in place).

**Honest result**: the fix is mechanically correct and worth keeping, but
by the time it can trigger (cycle 2+), most of the visible height loss has
ALREADY happened during cycles 0-1 -- which UPDATE 7 already traced to the
REAR leg's tuck-swing-extend cycling, not the front pull. So this fix
prevents the front legs from over-rotating FURTHER in later cycles (a real
problem, now solved) but doesn't address the DOMINANT early-cycle height
loss, which remains open. Tried combining this fix with UPDATE 7's reduced
tuck-swing amplitude (which alone flipped at cycle 7) -- delayed the
failure to cycle 8 but didn't prevent it; weaker rear propulsion still
needs too many cycles and something else gives out eventually. Reviewed
our own replay frames again post-fix (per the now-permanent practice) --
visually similar to before, consistent with the numbers.

**Where this leaves it**: two real, validated, non-destabilizing fixes are
now in place (UPDATE 6's stand-up push, this update's geometric pull-stop),
together worth keeping regardless of what comes next. The genuinely open
question is still UPDATE 7's: how to make the REAR leg's tuck-swing-extend
motion generate the same propulsion without needing as much height-costing
amplitude -- likely needs a shape change, not just a scalar reduction.

---

## UPDATE 7 (same resumed session): investigated the "full fix" (redesign propulsion, not patch the landing) -- real progress, genuine hard tradeoff found

User asked directly for the next step toward a full fix (not another
patch): find WHY the propulsion mechanism loses height in the first place
and address that, rather than continuing to recover height after the fact.

**First hypothesis, disproven directly**: thought the front-knee-PULL
mechanism's own accumulated retraction was the driver, and that the
original `REPLANT_EVERY=5` reset (which never fires within our 3-cycle
convergence) was the missing safety valve. Exposed `--replant-every` as a
CLI arg and tested 1 and 2 -- **the front-leg replant attempts mostly
failed outright ("FL=stuck", no new contact found)** since there's too
little forward progress between attempts this early for a fresh probe to
find new ground, and even when a replant nominally succeeded, **body_z at
the moment RB plants was IDENTICAL (0.0542-0.0546m) regardless of replant
frequency.** Also tested halving `--pull-deg-per-cycle`/`--max-knee-flex-deg`
directly -- again, body_z at RB's plant was unchanged to the decimal place.
**The front-knee pull magnitude is NOT the driver of this specific
collapse.**

**Real driver, confirmed by elimination**: the striking invariance of
body_z (0.0542-0.0546m) across every front-leg-focused change, combined
with a clear rear-leg-cycling smoking gun (body_z drops specifically during
each tuck-swing-extend cycle in the printed trace: 0.1017 -> 0.0819 across
cycles 0-1, well before RB even attempts to plant), pointed at the REAR
leg's own tuck-swing-extend amplitude instead. Tested directly: cutting
`--tuck-knee-deg`/`--swing-hip-deg` roughly in half (45/-28 -> 20/-15)
preserved height dramatically better through the early cycles (0.1035 ->
0.0887 by cycle 5, vs. the baseline's 0.1017 -> 0.0819 by cycle 1) --
**confirms the rear-leg tuck-swing-extend magnitude is the real driver of
the height loss**, not the front pull as originally suspected.

**But this isn't a free fix -- it's a genuine, sharply nonlinear tradeoff**:
that same drastic reduction took until cycle 6 for RB to even get in range
(vs. cycle 2 at default amplitude) and then FLIPPED at cycle 7 (tilt 127).
A moderate reduction (38/-25, ~15% cut) gave ZERO measurable improvement in
body_z at RB's plant -- identical to the unmodified default. An
intermediate value (32/-22) was tried too and flipped even earlier (cycle
2, tilt 94) -- worse than either the large cut or no cut at all, suggesting
a real nonlinearity/resonance in this parameter space, not a smooth
tradeoff curve. **Small changes to tuck/swing amplitude do nothing; large
changes destabilize; there's no simple scalar sweet spot found yet.**

**Where this leaves the "full fix"**: genuinely understood now, not
guessed -- the rear-leg tuck-swing-extend motion trades propulsion strength
against body height directly and non-linearly, the same way the front-pull
mechanism trades propulsion against height (confirmed back in UPDATE 6,
just not the dominant term here). A real fix likely needs the rear-leg
motion to generate its OWN propulsion more efficiently per unit of height
lost -- e.g. a genuinely different swing shape, or an amplitude that
adapts/ramps rather than a fixed large value throughout -- rather than a
single global scalar tuned by trial and error. This is a well-scoped,
understood research question for next time, not a mystery: "why does a
smaller tuck/swing amplitude fail to propel reliably well before it
meaningfully helps height, with no smooth middle ground?"

**Reverted** all the exploratory parameter changes from this update (none
gave a clean win) back to the validated defaults (`--replant-every 5`
[still exposed as a CLI arg for future experiments], `--pull-deg-per-cycle
6`, `--max-knee-flex-deg 30`, `--tuck-knee-deg 45`, `--swing-hip-deg -28`).
**Kept** UPDATE 6's synchronized stand-up push (the one change that gave a
clean, reliable, if modest, win: +9-10mm across 3 seeds, no regressions).

---

## UPDATE 6 (same resumed session): TRUE root cause found via visual frame review -- height collapse, not tilt

The "sitting on its belly" problem was never actually about tilt or the
front knee's angle in isolation -- both UPDATE 4 and UPDATE 5 were
diagnosing the wrong layer. Found by finally doing what should have
happened much earlier: extracting and looking at frames from OUR OWN
replay (not just the reference video), after the user reported "no change"
across several regenerated GIFs with different unique filenames (ruling out
a caching explanation). A frame at the very end of the sequence showed the
body essentially flush against the platform, legs splayed -- while
`tilt()` (roll/pitch only) read a perfectly fine ~9 degrees the whole time.
**`tilt` measures orientation, not height -- a robot can be dead level while
completely collapsed onto the ground, and every earlier "stability" check
this session was blind to that.**

Traced body height (`body_z`) explicitly, tick by tick, through the whole
sequence for the first time: 0.0828 (FR secured) -> 0.1020 (rear-leg
extension raises it, working correctly) -> 0.1017 (cycle 0, still tall) ->
**0.0819 (cycle 1) -> 0.0542 (cycle 2, when RB's probe fires) -> 0.0545
(stays low from here)**. The big drop is real and happens during the crawl
cycles themselves, well before any of the "standing" code from UPDATE 4/5
even runs.

Root cause, now correctly identified: **the front-knee-pull mechanism IS
the propulsion source (folding the knee against a friction-held foot is
what generates the pull), and folding a leg mechanically shortens it,
which necessarily lowers the body.** This is a real, expected side effect
of how the current propulsion works, not a bug -- which is why UPDATE 5's
five approaches (all aimed at the front knee's angle or the anchor-holding
force) either had no effect or destabilized: they were treating a symptom
of the propulsion mechanism as if it were an independent tracking problem.
Confirmed directly that anchor-holding force wasn't it either: added a
firmer `anchor_force` parameter to `probe_leg_onto_platform` for every
probe call after the front legs are already load-bearing (RB/LB plants,
same-side leverage advances) -- identical body_z numbers with or without
it.

**Mitigation implemented**: a synchronized 4-leg "stand-up push" once all
four feet are secured -- front knees straighten and rear hip+knee extend
further, TOGETHER (not one leg in isolation, which is what UPDATE 5's
attempts got wrong), in several small stages with a settle between each.
Reasoning: with all four feet now resting on solid, flat platform ground
(unlike anywhere during the climb itself), a synchronized push is much
closer to how a real quadruped recovers from a crouch than adjusting one
leg while the other three fight it. **Result, validated on 3 seeds: a
real, consistent +9 to +10mm height gain** (clearance above the platform
36-98mm... actually 29mm -> 37-38mm), landing tilt 19.1-19.4deg. Tried
extending this further (more stages, looser tilt tolerance) -- hit a
genuine equilibrium around 20deg tilt that more settle time doesn't
recover from (not a transient spike), so returns diminish fast past the
current tuning.

**Honest assessment after extracting and reviewing our own replay frames
again post-fix**: the fix is real and measurably correct in the
underlying physics, but NOT yet a dramatic visual improvement -- the robot
still looks meaningfully lower/flatter than the reference climb's natural
stand (frame 07 in `docs/rl/reference-frames/`). A full resolution likely
needs a fundamentally different propulsion mechanism for the drag/pull
phase -- one that doesn't rely on progressively folding the front knee for
leverage in the first place, so there's no height deficit to recover from
at the end -- rather than continuing to patch the landing after the fact.
This is a real, well-scoped open problem for next time, not a mystery.

**New standing practice adopted**: extract and look at frames from BOTH
the reference video AND our own replay output whenever verifying a fix,
not just printed numeric diagnostics. `tilt` (or any single scalar) can be
blind to failure modes a human eye catches immediately -- confirmed
directly this session, twice now (once for the reference-video comparison
itself, once for this exact bug).

Replay regenerated and verified multiple times at this state (latest:
`/Users/markjohnson/Desktop/crawl_climb_v4.gif`, seed 7000, 743 frames, 0
corrupted, 4/4, final tilt 19.4, body clearance 37.8mm -- up from ~29mm,
real but modest visual improvement).

---

## STANDING GOAL, added 2026-09-19 (read this first)

Once the climb + standing posture is working reliably (current open item:
the tilted-landing problem in UPDATE 4 below), **the next phase is
robustness, not just a single validated scenario**. So far every result in
this doc is from ONE tuned configuration (fixed ledge height 25mm, fixed
approach margin 0.10, a handful of seeds that mostly just vary the walk
policy's noise, not the actual climb geometry). Before calling B13/H7
sim-validated, test the SAME mechanism across a real range of slightly
different situations, e.g.:
- Ledge height (`--ledge-h`): the 15-30mm sweet band the original foot-
  probing validation found, not just 25mm.
- Approach distance/angle: `--body-target-margin-m` swept wider, and any
  off-axis/non-square approach if the walk policy's own heading noise ever
  produces one.
- Starting body position/orientation variety beyond just RNG seed (seed
  varies the walk policy's noise, not the geometry it starts the climb from).
- Possibly DR/friction variation already built into `benchmark_decathlon`'s
  `_EXTRA_DR` mechanism, if that's relevant to foot-contact sensing.

A mechanism tuned to one exact scenario (current state) is a much weaker
claim than one that degrades gracefully across a family of scenarios. Don't
declare this skill done on the strength of 3-5 seeds at one fixed geometry.

---

## UPDATE 4 (same resumed session): reference frames captured + standing-posture problem diagnosed (not yet solved)

After UPDATE 3's breakthrough, the user pointed out the obvious next problem:
once all four feet are secured, the front legs "go limp" and the body "lays
flat" on the platform instead of standing on top of it -- described directly
as "the front legs just fully pull straight back until the robot is sitting
on its belly."

**Reference frames captured**: downloaded the official PetoiCamp reference
video (yt-dlp, format 134 -- Homebrew's ffmpeg/yt-dlp formulae are blocked
by an outdated Xcode on this machine, worked around with pip-installable
`yt-dlp` + `imageio-ffmpeg`, which ship prebuilt binaries and need no
compilation) and extracted 7 key frames covering the whole climb sequence,
saved permanently at `docs/rl/reference-frames/` with a README describing
each phase. **Caution for next time**: the `pip install` for these tools
upgraded numpy to 2.4.6 in the shared project venv, which silently breaks
`stable-baselines3` (needs numpy<2.0) -- caught and fixed immediately
(`pip install "numpy<2.0"`) but verify `python crawl_climb.py ... ` still
runs before trusting any test after installing new packages into this venv.

The frames confirm real, useful detail: frame 03
(`03-steep-arch-rear-extended.png`) shows the rear legs nearly fully
extended driving the body into a steep mantle position BEFORE any rear
stepping -- direct visual confirmation that "tall stance = leverage" is
real, not a stylistic guess. Frame 07 (`07-final-standing-tall.png`) is the
target for the open problem: the real robot ends up standing tall, level,
and naturally on top, nothing like our sim's collapse.

**Root cause traced precisely** (through several failed hypotheses, each
tested and ruled out directly rather than guessed):
1. First hypothesis: the front knee is over-flexed by the "slide deeper"
   depth fix being applied twice (once at initial securing, again during
   the same-side leverage advance from UPDATE 3). Added a `do_slide` param
   to skip the redundant slide on the advance call -- **did not change the
   result at all** (knee still landed at exactly ~90.1-90.2deg across all
   3 seeds). Ruled out.
2. Second hypothesis: `_with_front_ik`'s rate limiter (RATE_LIMIT_DEG=4/call)
   lets the knee reach an extreme angle during a transient peak-tilt moment
   mid-maneuver (tilt hit 20-46deg at points) and never gets enough
   follow-up calls to walk back down once tilt recovers. Tested directly:
   added 40 extra `_with_front_ik` settle calls after both rear legs plant,
   at which point tilt has already recovered to 9.2deg -- knee STILL landed
   at ~90.5deg. Ruled out.
3. **Actual cause, confirmed by elimination**: the rear-leg extension
   phase and the tuck-swing-extend cycles have genuinely lifted the BODY
   much higher by the time both rear legs plant (that IS their leverage
   effect, working as intended) -- so the OLD front anchor point, captured
   early when the body was still low near platform level, ends up almost
   directly BELOW the shoulder joint by the end. Reaching straight down to
   that point geometrically requires near-maximal knee fold. This is not a
   bug in the anchor tracking -- it's a real, correct consequence of how
   much the body rises during the climb. The mismatch is between "how high
   the body needs to be mid-climb for leverage" and "how high it should
   settle once done" -- nothing currently bridges that gap.
4. Tried capping the knee directly inside `_with_front_ik` (55deg) to
   prevent this -- broke anchor tracking outright (flip by cycle 3, every
   seed, before LB even plants): the knee genuinely NEEDS to reach ~90deg
   at some points during the maneuver to hold the anchor precisely. Capping
   it there is capping something load-bearing, not fixing a bug. Reverted.
5. Tried a direct jump from the ~90deg crouch straight to a flat-ground
   `STANCE` target (imported from climb_env) -- caused an outright flip
   (tilt 180). Too large a correction in one motion from such an extreme
   starting configuration, and STANCE itself is tuned for flat-ground
   walking, not a foot already up on an elevated platform. Reverted.
6. **Current partial mitigation**: un-crouch the front knee gradually in 4
   stages (90deg -> ~25deg target, stopping early if tilt exceeds 40deg)
   instead of one continuous motion. This avoids an outright flip (which
   both single-shot attempts caused) but doesn't reach a clean stand either
   -- all 3 seeds consistently abort at stage 3/4 with tilt settling around
   44-47deg. **Better than a flip, but not yet the fix** -- the robot ends
   up tilted, not standing tall and level like frame 07.

**Where this leaves things**: the climb itself (UPDATE 3's mechanism) is
fully intact and unaffected -- 3/3 seeds still 4/4, converging in exactly 3
cycles, no tail push. The OPEN problem is entirely in what happens in the
~1 second after both rear legs plant. Given the root cause (an anchor point
captured too early, before the body's climb-leverage height increase), a
more promising direction for next time than more uncrouch-tuning: don't
treat the ORIGINAL front-leg anchor as sacred through the whole sequence --
periodically RE-ESTABLISH it (a fresh, shallow probe-and-replant, similar to
the existing `REPLANT_EVERY` mechanism already used earlier in the crawl
loop) as the body rises, so by the time both rear legs plant, the front
anchor already reflects something close to the CURRENT body height rather
than a stale, now-far-below point. That would need each re-plant to also
choose a shallower forward-margin/above-margin appropriate to a taller
body pose, not the original ledge-height-relative values.

Replay regenerated and verified at this state
(`/Users/markjohnson/Desktop/crawl_climb.gif`, seed 7000, 767 frames, 0
corrupted, 4/4, tilt 45.5 at the very end -- visibly tilted in the final
stand, not yet resolved).

---

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
