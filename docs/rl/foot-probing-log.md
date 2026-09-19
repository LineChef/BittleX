# Foot-probing (B13) feasibility campaign log

Queued after the checkpoint summary (`docs/rl/final-synthesis-plan.md`), per
the plan in `docs/behavior-ideas.md` B13's "deliberate foot-probing" option.
Approved plan: validate the sensing mechanism and the physical motion in sim
before any training investment; build as a discrete skill (Phase E pattern),
not trained into the continuous walk policy, if it works.

**All work in this campaign is sim-only, scripted/kinematic puppeteering on
top of the frozen `run20m_resid30_ppo` walk -- no training happened.**

## Starting point

Two things already validated before this round:
- **Sensing signal**: commanded-vs-actual joint tracking error under
  position control reliably reveals real ground contact -- confirmed against
  `p.getContactPoints()` ground truth at 27mm/30mm ledge depths in the
  original, simpler prototype (reactive trigger, straight-down search only,
  no forward-reach phase).
- **Trigger timing**: the original trigger was reactive (freeze only after
  the paw crosses the ledge edge), which let the body already be mid-topple
  (17-30° tilt observed) before the probe even ran -- fixed with a proactive
  trigger (freeze while the paw is still approaching and the body is level,
  <5° tilt).

This round's job: get the *combined* motion (proactive trigger -> freeze ->
lift -> reach past the edge -> search down) actually working end to end.

## Finding 1 -- lifting one leg toppled the body; root cause was a real
center-of-mass problem, not IK or force

Freezing the walk's natural pose and lifting the front-left (FL) paw caused
steadily growing tilt (0° to 12.6° over just the 15-step lift, before any
reach) -- independent of how much force the other three legs were commanded
with (tested 0.2 Nm up to 5.0 Nm, identical result every time, ruling out a
torque/tracking explanation).

Measured directly: at the trigger moment, the robot's full-body center of
mass sits **outside** the remaining 3-leg (FR-RB-LB) support triangle by
~2.5mm. Lifting FL is geometrically guaranteed to tip the body toward the
missing corner, regardless of leg strength -- this is a real quadruped
weight-shift problem, not a bug in the probe script.

**Fix**: an explicit weight-shift phase before lifting -- bend the three
stance legs' hip/shoulder joints ~15° to lean the body back over the
remaining support triangle. Confirmed directly: this pulls the COM inside
the triangle and the subsequent lift recovers almost completely (18-19mm of
the intended 20mm, vs. the paw actually *dropping* -10.8mm without the
shift).

## Finding 2 -- the weight-shift creates a reach deficit it then has to pay for

Shifting weight backward moves the whole body (and the FL shoulder) away
from the edge by roughly the same amount -- so the same absolute forward
reach target got *harder*, not easier, after the fix that made lifting work.
Separately, the proactive trigger's "unloaded and level" condition is always
satisfied early in the gait cycle, roughly 25-30mm before the true edge (see
Finding 4) -- so the reach phase has to cover that gap *plus* whatever
margin past the edge is wanted, a bigger ask than originally assumed.

With patient, many-increment IK (aim past the actual target and stop once
the desired point is reached, rather than one coarse per-increment jump),
the leg reliably reaches **~12-15mm past the edge** from this shifted stance
-- a real, repeatable improvement over the pre-shift ~0mm, but well short of
the original 35mm design target.

## Finding 3 -- after weight-shift + reach, the leg has almost no downward
search budget left, and this isn't fixable by tuning the search alone

Ray-cast ground truth (independent of the leg's own reach) showed the real
floor after a step-down sits much deeper than "ledge height" alone suggests
-- the near-side platform itself sits well above the lower floor, so the
real search depth needed is **32.8mm / 44.8mm / 62.8mm** for the 15mm / 27mm
/ 45mm ledge cases respectively, not 15/27/45mm.

Re-run with the same validated per-increment convergence method that gave
the original 27mm/30mm ground-truth-confirmed results (bounded wait per
increment, checking convergence to that increment's absolute target -- not
a frame-to-frame "plateau" heuristic, which was tried first and shown to be
unreliable at fine step sizes, unable to distinguish "still slowly
converging" from "genuinely stuck"): the search phase now fails at a
consistent **4-5mm** of depth for every ledge height tested (15/27/45mm, 5
seeds each, tight clustering) -- and is **not** ground-truth-confirmed real
contact. Only the flat/no-ledge control finds real, confirmed contact
(correctly, near 0mm).

This is a saturation artifact: after weight-shift + lift + reach, the FL
leg's 2-DOF (hip pitch + knee) chain has essentially exhausted its usable
range, leaving only ~4-5mm of further downward travel before hitting its
own limit -- far short of the 30-60mm needed to tell a traversable step from
a cliff.

## Finding 4 -- the trigger's timing conflict is structural, not a threshold
tuning problem

Traced the full approach gait cycle step by step (tilt, load state, and
distance-to-edge every step). The FL paw has exactly two "unloaded and
roughly level" windows before crossing the edge:
- **Early** (~t=4-8, paw 25-30mm from the edge): level (tilt 3-4°),
  unloaded -- this is what the proactive trigger fires on.
- **Late** (~t=78+, paw 5-18mm from the edge, much closer): also unloaded,
  but tilt has already climbed to 10-18° by then (ordinary within-stride
  postural oscillation, unrelated to the ledge) -- too late for the <5°
  safety condition that makes the trigger "proactive" in the first place.

Tightening the trigger window to fire only when close to the edge does not
produce a better trigger point -- it produces no valid trigger at all until
the unsafe, already-tilting late window. Getting both "close to the edge"
and "still level" simultaneously would need a different approach entirely
(e.g. a deliberate commanded slow-and-settle near the edge, not an
opportunistic freeze of whatever the walk's natural pose happens to be) --
a materially bigger redesign than tuning this prototype's thresholds.

## Conclusion (2026-09-19)

Four independent, compounding mechanical constraints, each confirmed with
direct measurement (COM-vs-support-triangle geometry, ray-cast ground-truth
floor depth, cross-validated convergence methodology, full gait-cycle
tracing) -- not a single bug, and not fixable by further parameter tuning of
this prototype's design:

1. Lifting one leg from the walk's natural pose is geometrically unstable
   (COM outside the support triangle) -- fixable, but the fix costs reach.
2. The fix (weight-shift) trades stability for reach, netting only ~12-15mm
   of forward reach past the edge, versus the ~30-60mm real depth needed.
3. What's left of the leg's kinematic budget after weight-shift + reach is
   only ~4-5mm of further downward travel -- not enough to find real ground
   for anything but a trivial, already-flat case.
4. The only safe (level) trigger point is far enough from the edge (~25-30mm)
   that fixing 2 and 3 further would need a fundamentally different
   approach-and-stop motion, not just more IK tuning.

**Verdict: this specific mechanism (2-DOF front leg, opportunistic freeze of
the trained walk's natural gait pose, scripted lift/reach/search) does not
reliably work for the step-down case, given Bittle X's leg DOF and this
walk policy's approach dynamics.** The core *sensing* signal (tracking
error reveals contact) remains validated and real -- what's not viable is
this particular way of getting the leg into position to use it.

Per the approved plan's Stage 2 decision gate: closing this as a documented
negative result, same standard as every other closed lever this session
(gait-friction, `FAC_NOSTALL`, slope-ceiling). Not proceeding to Stage 3
(discrete skill integration) or to the step-up case, since the plan's own
condition for exploring step-up ("if you find success with probing down")
was not met.

**What would need to change to revisit this**: a deliberate commanded
approach-and-settle motion (rather than freezing the walk's opportunistic
pose) that gets the body stopped, level, and already weight-shifted with
the front leg close to the edge *before* attempting to lift -- a materially
different design, not a tuning pass on this one. Also worth noting for any
future attempt: a rear leg was never tried as the probing leg, and this
campaign only tested the front-left; both are open, untested alternatives
if this is picked up again.

## Round 2 (2026-09-19) -- tried the deliberate stop-and-settle fix; stability
solved, sensing still fails, for a new and more fundamental reason

User's suggestion: replace the opportunistic freeze with a deliberate
commanded stop (`fwd=0`, let the *trained policy itself* settle to a stop --
matches how a real stop command would work in deployment) before starting
the probe sequence, and test on a shorter ledge the leg can plausibly clear.
`probe_foot_settle.py` (new file) implements this.

**Stability: solved, cleanly.** Tilt stays under ~2 deg through the entire
sequence (settle -> weight-shift -> lift -> reach -> search), versus 10-17
deg with the opportunistic-freeze approach. Two further fixes compounded
with the stop-and-settle to get here:
- **Lift**: the settled standing pose has the knee nearly straight (~0-3
  deg) -- a poorly-conditioned start for an IK vertical-lift solve
  (confirmed: IK barely moved the paw, ~1.7mm of 20mm intended, despite
  joints tracking their IK targets fine -- a mechanical-advantage problem,
  not a tracking one). Switched to direct knee-flexion (not IK): -40 deg
  gives ~26mm of clean lift at <2 deg tilt, every trial.
- **Reach**: IK reach done *from* that now well-conditioned bent-knee pose
  (rather than from the near-straight settled pose) reaches a genuine,
  repeatable plateau at +40mm past the edge, tilt still ~1.5 deg -- more
  than double the previous best (~18mm at 10+ deg tilt).

**Sensing: still fails, but for a different, more fundamental reason than
round 1.** Initial validation sweep across 0-45mm ledges showed "confirmed"
contact at a suspiciously identical ~36-40mm depth *regardless of ledge
height*, including the 45mm case (which needs ~63mm of real depth per the
round-1 ray-cast finding) -- a red flag that something other than real
floor-sensing was firing. Checked the actual PyBullet contact **normal**
vector at the moment of "contact" (not just whether `getContactPoints()`
fires, which round 1 already used, but hadn't checked *what surface* it
fired on):

- **Flat/no-ledge control**: normal = `(0.00, 0.00, 1.00)` -- straight up,
  a genuine floor hit. Correct.
- **Every nonzero ledge tested, including the shallowest (5mm)**: normal
  dominated by the X component (`~0.76-0.90` X vs `~0.43-0.65` Z) -- a
  near-vertical surface, not the floor. Checked the contact position
  directly: x sits right at `EDGE_X`, the ledge's own riser (the vertical
  face of the step), not the lower floor at all.

Root cause, traced directly: during the search phase, IK-solving for
"same x, lower z" doesn't actually hold x -- the 2-DOF (hip+knee) solution
naturally retreats in x as it searches deeper (a basic consequence of a
2-link arm's reachable workspace: extending further down from this
leg's already-reached-forward pose isn't possible without giving back some
of that forward reach). Traced one episode step by step: paw went from
+26mm past the edge at the start of the search down to only +6mm by the
time it reported "contact" -- it drifted backward into the ledge's own
wall, not down to the floor. The original search loop only checked Z
convergence, never verified X was actually held -- so this false-positive
was invisible until the contact normal was checked explicitly.

**This is a new, independent confirmation of round 1's core finding, not a
different problem**: the front leg's 2-DOF workspace cannot simultaneously
hold a forward reach position *and* extend deep enough to clear even a 5mm
step's riser -- the same fundamental reach-vs-depth trade-off as round 1,
now shown to persist even after fixing every stability issue that could
plausibly have been the cause instead.

**Updated verdict**: stop-and-settle is a real, valuable fix for stability
and should be kept if this is revisited (tilt <2 deg vs 10-17 deg is a
categorical improvement, not a marginal one) -- but it does not unlock the
sensing task on its own. Two independent implementations (opportunistic
freeze / round 1, and deliberate settle / round 2), using different lift
and reach mechanisms in each, have now hit the same wall: this leg's 2-DOF
reach envelope cannot do both "stay past the edge" and "reach the real
floor" at once. Closing this as a doubly-confirmed negative result.
`docs/behavior-ideas.md` B13 updated to match.
