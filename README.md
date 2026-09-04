# Robotics Project with Bittle X

A robotics project where I teach a quadruped robot to:

- walk using reinforcement learning
- perceive its environment through an onboard AI camera that runs vision models on-device (Grove Vision AI V2)
- hold natural voice conversations powered by Claude
- build persistent memory of its interactions over time

The full roadmap and decision log are in
[`docs/project-plan.md`](docs/project-plan.md).

## Project Goals

- **Locomotion**: a *command-following* walking policy trained by reinforcement
  learning (simulation → sim-to-real), rather than switching between hand-scripted
  gaits. It takes a speed and heading command and produces the gait — stand,
  start/stop, forward, backward, turn — and stays upright across slopes,
  obstacles, rough ground, shoves, and the weight shift from the mounted Pi/camera
  payload.
- **Recovery**: detect a fall from the IMU, run the firmware get-up skill for the
  falls the hardware *can* recover from, and know when it needs a human.
- **Perception → navigation**: an onboard AI vision module for obstacle detection,
  and vision-guided movement — pick a visible target, head toward it, and correct
  course along the way.
- **Voice**: natural spoken conversation powered by the Claude API (speech-to-text
  → Claude → text-to-speech), with movement used as body language.
- **Memory**: persistent context across conversations, and a sense of place
  (which room it's in) built up over time.
- **Autonomy**: Claude as a slow deliberative layer on top of the reactive
  control — deciding where to go, what to look at, and whether to approach
  something, from what it sees and remembers.

## Hardware

| Component | Notes |
|---|---|
| Petoi Bittle X V2 (alloy servos) | Core quadruped platform, built on OpenCat / BiBoard V1 (ESP32) |
| Raspberry Pi Zero 2 W | Runs the voice / memory / vision / Claude pipeline |
| PiSugar S 1200 mAh | Independent Pi power, not shared with the servo battery — see [`docs/research/pi-power.md`](docs/research/pi-power.md) |
| Petoi AI Vision Camera Module | Grove Vision AI V2, onboard neural processor for on-device inference |

Full parts list, costs, and vendor-doc specs: [`docs/project-plan.md`](docs/project-plan.md)
and [`docs/research/hardware-specs.md`](docs/research/hardware-specs.md).

## Project Status

The Pi Zero 2, PiSugar S, microSD card, and power supply have arrived; the Bittle
X and camera are still a few weeks out. Everything runs software-only or with the
hardware mocked for now.

- **RL locomotion** (`rl_training/opencat-gym/`) — a PyBullet + Stable-Baselines3
  pipeline. The gait is a learned *residual* on Bittle's scripted `wkF` walk,
  IMU-corrected every control step, conditioned on speed/heading commands and the
  mounted Pi/camera payload. The frozen deployment base is **`run20m_ppo`** (20 M
  steps from scratch: tracks speed commands to 0.007 m/s, walks a −24° descent,
  0 % falls on the payload-on decathlon). It's exported to ONNX and sim-validated
  bit-for-bit against the on-robot control loop. A pre-hardware probe batch
  (2026-09-03) found the gait is *fall-proof but stalls* on terrain it can't
  perceive — root cause: no forward vision. The next gait training is
  **perception-in-the-loop** (Phase 8); the sim + Pi plumbing for the policy's
  own forward terrain feature is now in place. See
  [`docs/rl-runs/robustness-backlog.md`](docs/rl-runs/robustness-backlog.md) and
  [`docs/rl-runs/`](docs/rl-runs/) for history.
- **Companion pipeline** (`pi_pipeline/`) — voice conversation, persistent memory,
  vision / obstacle-avoidance, the BiBoard serial link, and a fall-recovery state
  machine are all scaffolded and run on a dev machine with the hardware mocked;
  **51 tests passing**.
- **Pre-hardware prep** — a headless Pi Zero 2 W bring-up runbook, an idempotent
  provisioning script, a model fetcher, and a voice-pipeline benchmark harness are
  ready to run the moment the SD adapter and robot arrive:
  [`docs/research/pi-bring-up.md`](docs/research/pi-bring-up.md).

For a plain-language tour of how each part works, see
[`docs/how-it-works.md`](docs/how-it-works.md). For the pre-hardware state and the
day-1 checklist, see [`docs/hardware-readiness.md`](docs/hardware-readiness.md).

## Walking policy

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
  to ±10°; the policy generalizes well past that — it walks a −24° descent
  *forward* at ~0.06 m/s, climbs to +15°, and holds a straight line across a
  cross-slope, at 0 % falls.
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
- **Result:** 0 % falls across the full easy→brutal test ladder (to −24°
  descent, 85 mm obstacles, 1.0-impulse shoves, a 20° compound gauntlet) with the
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
than falls**, and it cannot deliberately step over or route around an obstacle it
hasn't touched. That is the Phase 8 perception-in-the-loop work; the
terrain-feature plumbing is built and training waits on hardware. It also does
not self-right, climb stairs, or jump (a jump is planned as a separate
on-command skill, [`docs/behavior-ideas.md`](docs/behavior-ideas.md) B14).

## Repo Structure

```
rl_training/opencat-gym/   # Simulation-based RL training (based on ger01d/opencat-gym)
pi_pipeline/
  voice/    # Speech-to-text, Claude API integration, text-to-speech
  memory/   # Persistent conversation memory / retrieval
  vision/   # Camera integration, obstacle avoidance, scene description
  link/     # BiBoard serial link + fall-recovery state machine
tools/      # Report generators and other standalone utilities
docs/       # Project plan, run logs, research notes
```

## Setup

**RL training**: requires Python ≥ 3.10 (macOS ships an EOL 3.8, so this project
uses a `.venv` built with Homebrew's `python@3.11`). See
[`rl_training/README.md`](rl_training/README.md) for setup, including a required
macOS build workaround for `pybullet`.

**Companion pipeline**: `pi_pipeline/requirements.txt` for the core (text-mode)
deps, `requirements-audio.txt` for the voice backends. Pinned to versions verified
to have prebuilt ARM wheels so the Pi install compiles nothing.
