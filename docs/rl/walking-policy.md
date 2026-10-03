> **Reference, moved verbatim from the README on 2026-10-02.** It describes the original frozen base `run20m_ppo`
> (the first 20 M-step policy; ±22° residual, ~200 M steps across 88 runs). The policies that followed (±30° residual,
> training under the real control path, and the one deployed now) are in [`hw1-log.md`](hw1-log.md); which one is
> deployed is in [`../STATUS.md`](../STATUS.md); real-robot results are in [`real-walk-log.md`](real-walk-log.md).

# Walking policy — what the learned gait does

`run20m_ppo`, the frozen gait, is a learned control layer over Bittle's built-in
`wkF` walk. Every control step (80 Hz) it reads the IMU, the gait-phase clock, a
tilt history, and the recent joint-target history, and outputs a bounded (±22°)
correction to the scripted joint angles. The behaviours below accumulated over
**~200M simulation steps across 88 training runs** (run
`python rl_training/opencat-gym/training_steps.py` to refresh the count); only
the changes that measurably helped were kept.

**Gait structure**

- **Diagonal trot.** A contact-based reward locks the front-right / back-left
  pair to swing together, opposite the other diagonal, from the first training
  step so the policy can't settle into a shuffle.
- **Stays a recognizable walk.** A dense 8-joint match to the `wkF` reference
  trajectory anchors the gait; the policy deviates from the scripted pose only
  where it earns something.
- **Foot clearance.** Swing feet lift to a ~20 mm target — added after the rear
  feet were found dragging once the heading term made the body front-heavy.
- **Holds a ride height.** A target body height is enforced, killing the
  crouch-and-collapse failure mode; joints are also pushed off their end-stops
  where they'd lose authority.

**Command following**

- **Speed set-point.** The `wkF` phase clock advances in proportion to the
  commanded speed, so the imitation target *is* a slow gait for a creep and a
  fast gait for a sprint. Tracks commands from ~0.03 (creep) through 0.09
  (cruise) to 0.14 m/s (fast), and backward to −0.06, to within ~0.007 m/s.
- **Heading hold.** Nulls *accumulated* yaw error, not just yaw rate — drift
  stays ~0.1° over 90 s.
- **Stand.** Freezes the gait phase and holds a stance when the speed command
  is ≈ 0.

**Terrain**

- **Inclines.** Every episode the ground is tilted a random roll *and* pitch up
  to ±10°; the policy generalizes well past that — it climbs a 24° slope
  *forward* at ~0.06 m/s, walks down steep descents, and holds a straight line
  across a cross-slope, at 0 % falls. (A 2026-09-23 re-measure with corrected
  slope labels found its limits are side-hills past ~8° and climbs past ~20°;
  see `docs/rl/hw1-log.md`.)
- **Scattered obstacles.** Every episode drops 4–10 small boxes (to ~45 mm,
  short along-path, never spanning the lane) in the walking path. The policy
  never sees them coming, so what it learned is to *clear or deflect over* them
  reactively — the ~20 mm foot-clearance plus the balance catch when one trips a
  foot. It clears the evaluation obstacle cells up to 85 mm at 0 % falls. It does
  **not** step over things deliberately (see *Limits*).
- **Side-slope trade-off.** On a lateral tilt it drops to roughly a quarter of
  cruise speed and locks its heading — an emergent choice, not a rewarded one:
  slowing lowers the instability cost.
- **Rough footing.** Feet ride over small bumps rather than catching an edge; it
  traverses a dense bump course at ~0.05 m/s without falling.

**Balance and stumble recovery**

- **Active catch.** Once body tilt passes ~0.5 rad (short of the ~1.3 rad fall
  line), a dense reward rewards three things at once: leaning the tilt *angle*
  back down, damping the tilt *rate* so the wobble loses velocity, and getting
  more feet onto the ground. It fights the wobble, it doesn't wait it out.
- **Off-beat corrective step.** While tilted, the catch reward outweighs the
  stay-on-the-stride-beat penalty, so the policy can throw in an unscheduled
  step to re-plant, then re-sync to the gait clock once level.
- **"One more step" gradient.** Every step held upright while near tipping pays a
  flat bonus, plus a scaled bonus for finishing a rough episode on its feet — so
  a partial save still trains.
- **Trained against:** small continuous nudges every step, occasional hard
  velocity kicks (~0.55 m/s) at a random gait phase and direction, a sustained
  shove, and a briefly pinned foot. The kick magnitude runs on an **adaptive
  curriculum** — it escalates only while the policy is surviving most recent
  episodes and backs off when it isn't, so it masters the catchable range before
  the pushes get harder.
- **Result:** 0 % falls across the full easy→brutal test ladder (to a 24°
  climb, 85 mm obstacles, 1.0-impulse shoves, a 20° compound gauntlet) with the
  payload on. Lifted, held, and dropped at an angle, it re-acquires the gait 31
  of 32 times.

**Load and hardware tolerance**

- **Payload-conditioned.** A rear mass and a forward camera mass (~76 g total)
  are present every episode, with the total swept 40–110 g, so the policy
  compensates for the offset load and its variation without over-fitting one
  exact inertia.
- **Weak / hot servos.** Random per-joint torque cutback in training (modelling
  the P1S overheat protection) — the policy redistributes effort and keeps
  walking.
- **Efficiency.** A penalty on summed joint power pushes toward a gait that draws
  less current — less servo heat, more runtime.

**Motion quality**

- Penalties on 1st- and 2nd-order joint jitter, on the residual's frame-to-frame
  jerk, on feet reversing direction in place, on paw slip, and on crawling on the
  elbows — together these keep it taking real steps instead of scrabbling or
  vibrating to game the speed reward.

**Sim-to-real robustness**

- Domain randomization every episode: ground friction ±30 %, per-link mass
  ±18 %, IMU noise on the observation only (the reward stays clean), joint-history
  noise, and a perturbed start pose. Command latency and a joint zero-point
  offset are wired in and inert, ready for a transfer-hardening pass.

**Approaches tried and dropped** — self-righting after a fall (impossible on this
hardware — no roll-axis joint, even with boosted torque; replaced by the
always-on catch); a stride-length reward (gamed by fast foot-flicks, shortened
the real stride); slowing the phase clock under tilt (destabilised the gait three
separate times); fading the imitation reward mid-wobble (PPO diverged on the
discontinuity); a scripted mid-walk brace reflex (net wash); folding curbs /
ledges into the walk (bred timidity — it backed away from steps).

**Limits.** No forward perception — the policy reacts only *after* a foot makes
contact. Against a curb, a thin lip, or sustained rough ground it **stalls rather
than falls**, and it cannot deliberately step over or route around an obstacle
it hasn't touched. Folding "see it → step over it" into the trained gait itself
was tried and closed (Phase D, the `smoke_vfix3` retry) — it just plows through
or stalls; the accepted fix is a *discrete* reaction layered outside the walk
policy (vision picks a scripted response, not a learned one), built and
sim-validated but waiting on a real forward sensor. It also does not self-right
or jump (a jump is planned as a separate on-command skill,
[`docs/behavior-ideas.md`](docs/behavior-ideas.md) B14), and does not climb —
though unlike the others, climbing a single ledge is now a **confirmed,
scheduled** goal (B13) once the body arrives, not a maybe: Phase F's sim
attempt hit a contact-physics wall, not proof the real robot can't do it.
