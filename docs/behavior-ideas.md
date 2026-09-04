# Learned Behaviors — Backlog

A living list of behaviors to explore and implement for G2. "Learned" here spans
three kinds:

- **RL-trained** — a policy trained in simulation (the `rl_training/` pipeline).
- **Keyframe-authored** — hand-built joint sequences (Petoi's Skill Composer),
  saved as OpenCat skills.
- **Composed** — software behaviors that stitch skills + Claude + memory + vision
  together (mostly `pi_pipeline/`).

Nothing here is started. Add freely; when one gets picked up, note it in
`docs/project-plan.md` under the relevant phase.

---

## Locomotion / gait

### B1 — On-MCU gait policy (Decision Transformer)
Explore shrinking the trained gait policy so it runs on **Bittle's own ESP32
(BiBoard V1), not the Pi** — following the "Tiny RL for Quadruped Locomotion
using Decision Transformers" work ([arXiv 2402.13201](https://arxiv.org/pdf/2402.13201)),
which trained gait controllers small enough for the Bittle microcontroller.
Directly bears on the open Phase 6 question of whether a Pi Zero 2 W can run
inference fast enough — if the policy fits on the MCU, the Pi is freed for
voice/vision/memory. Research-heavy; a distinct approach from the PPO + PyBullet
pipeline.

### B2 — Specialty RL gaits
Short RL runs (or Skill Composer sequences) for gaits beyond the forward walk:
turn-in-place, sidestep, slow "sneak", backward. The turn and sidestep gaits
directly improve later autonomy modes (person-following, obstacle steering,
go-to-object).

**Update:** for **turning specifically**, if we ever train it, the better path
is a single **command-conditioned policy** (yaw-rate + speed command in the
observation, reward tracks the command) rather than a separate turn gait. But
it's **not scheduled** — OpenCat firmware turn gaits (`wkL` etc.) work today and
the vision pursuit layer can use them. Build the RL version only if firmware
turns oscillate in visual pursuit or fail on terrain — decision gate after the
drift-fix loop + Decathlon; see
`docs/rl-runs/auto-iteration-log-survive-loop.md`. Sidestep / sneak / backward
still fit the separate-run framing here.

### B3 — Skill Composer authoring
Stand up a workflow around **Petoi's Skill Composer** (the no-code desktop tool
for authoring keyframe skills — puppet the robot over USB, loop/sequence poses,
export to an `Instinct*.h` array). This is the authoring capability that B4
(expressive body language) and B10 (teach-me-a-trick) build on. Needs hardware.

### B9 — Vision + servo-resistance obstacle traversal
When the **vision module** spots an obstacle it judges walkable-over (small box,
close, low), use **servo-resistance / position-feedback divergence** (command vs.
actual angle on the front joints — see `docs/research/hardware-specs.md` "Servo
position feedback") as a **secondary confirmation signal** that a foot has
actually made contact, then trigger one of two responses:
- a dedicated **step-over gait** (exaggerated front-leg swing) for low obstacles, or
- a **climbing protocol** (front feet up onto the obstacle, shift weight, pull
  the rear up) for taller ones the step-over can't clear.

Two independent signals gating the action — vision says "something's there and
it's small", feedback says "I'm touching it now" — should be far more robust than
either alone (vision at 192×192 / short range misses thin things; blind feedback
alone can't tell a jam from normal stance load). Layered as a reflex outside the
learned gait, like the `vision/avoidance.py` pattern. Firmware-side for the
feedback read (skips the serial round-trip). **Needs vision + hardware;** revisit
once the vision module is installed and working. Related: the blind-clearance
tradeoff (rejected as a standalone — costs speed/stability every step for an
occasional benefit) and the front-foot **jam reflex** (feedback-only version of
the same idea).

### B13 — Climb as a separate skill policy
Real climbing — surfaces taller than G2's standing height: full stairs, a curb it
can't walk up, onto a low platform — is **its own RL skill policy**, not part of
the command-following walk policy. It needs a different motion (rear the front up,
plant the front feet, shift weight, pull the rear up), a different reward (get
up-and-over, not maintain a gait), a different terminal condition, and a posture
repertoire the flat-trot residual can't express. Folding it into the walk policy
would give a multi-modal policy that's worse at both.

Architecture (matches the rest of the project): a **library of low-level
policies** — the walk policy plus discrete skills (get-up, climb, later high-step)
— with **Claude as the selector**. Vision spots a step too tall to walk over →
Claude decides "invoke climb" → the low-level runs the climb policy → hands back
to the walk policy. This is the trained version of the "climbing protocol"
sub-bullet in **B9** (which framed it as a vision-gated reflex without saying
scripted vs. learned).

Tier split from the 2026-09-03 discussion:
- **< ~25 mm (slopes, small steps):** already the walk policy's job (rough-terrain
  DR). Nothing new.
- **~25–70 mm (curbs, thresholds, single steps, up to leg reach):** an *extension*
  of the walk policy — add a "terrain difficulty / high-step" conditioning input,
  same network, wider envelope. The **Phase 4 stance-recovery / ledge work** is
  the on-ramp (a "step up onto a lip and keep going" is the same primitive,
  rewarded for progressing over rather than only recovering).
- **> standing height (this idea, B13):** separate skill policy.

Highest sim2real risk of anything on the roadmap — contact-rich, posture-
dependent. **Defer until there's a concrete need** (does G2 actually need to
change floors / get on furniture?). Get Tier 2 for near-free out of Phase 4;
schedule B13 only when the use case is real. Needs hardware to validate.

### B14 — Jump / hop as an on-command skill  🟡  ⚪
A discrete, deliberately-triggered hop — **never** in the walk policy's action
space (so the gait can't decide to launch itself and flip over a bump). Fired
like any OpenCat skill (`k<skill>`) or a `perform_skill` tool call, in a sane
context (clear floor, not near an edge). Same "library of low-level policies +
Claude as selector" architecture as [B13].

Two tiers:
- **Free / now:** expose the firmware's existing scripted `jump` skill as a
  commandable action in `pi_pipeline`. Zero RL; risk is only what Petoi ships.
  Modest lurch-hop — sets the baseline for whether more is worth it.
- **Later, if the scripted hop is too weak:** an RL *jump skill policy*, trained
  separately (approach → crouch → explode → flight → land → hand back to the walk
  policy), its own reward / terminal condition, never merged with the gait.

**Hardware is marginal for a useful jump.** P1S alloy servos peak ~0.29 N·m but
lose most of it at speed (coreless) — jumping needs *power*, not just torque. A
3–4 cm pop of the ~380 g loaded body is near the ceiling; our ~70 g payload
(~20 % of body mass) eats directly into it. A leap that reliably clears a
4–5 cm block is a stretch goal, not a plan.

**Ballistic sim2real is the hard case** — open-loop during flight, high-impact
landing (repeated hard landings on alloy gears strip servos). Any RL version
needs careful hardware validation, landing-force limits, and a low rep budget.
Orthogonal to the "don't-stall / power over a lip" walk-policy work — for
clearing a small obstacle, muscling the *walk* over it is the higher-percentage
bet. Do B14 as a fun on-hardware experiment when the gait work is settled.

---

## Expression & personality

### B4 — Expressive body language
A small set of authored skills for emotion/emphasis — happy wiggle, play-bow,
nod-yes, shake-no, moonwalk — added to the `perform_skill` catalogue so Claude
can punctuate spoken replies with body language, not just perform functional
gaits. Low effort once B3 exists; high payoff for how alive G2 feels. These are
the tokens the `personality` `cues()` channel returns — wire them to real skills
here.

### B5 — Emotive sound (chirp vocabulary)
A vocabulary of short buzzer melodies (`b<tone> <ms> …` over the serial link) for
states: **happy, confused, alert, sleepy**. Cheap, big personality return, and
doubles as the Phase 7 listening/thinking/speaking state cue. Software + link.

### B6 — Mood from memory
Recent events + the memory store bias G2's idle behavior and phrasing. Example: a
long silence → G2 does an attention-seeking wander and delivers a wistful line
when next spoken to. Pure software on top of `pi_pipeline/memory/`; composes with
B4/B5.

---

## Autonomy modes

### B7 — Patrol mode
On command ("G2, keep watch"), G2 walks a short loop; on motion or person
detection it stops, chirps (B5), and describes what it sees via Claude (the
vision `narrate` path). A "mode" the voice loop can enter and exit. Exercises
vision + avoidance + voice + link together — a good capstone. Add it as another
`Mode` in `pi_pipeline/behavior/mode_controller.py` alongside EXPLORE.

**Explore mode + a curiosity trait are built** (`pi_pipeline/personality/` +
`pi_pipeline/behavior/`, 2026-09-03): the `ModeController` (CONVERSE / IDLE /
EXPLORE), the `Explorer` (wander + investigate-novelty intent), `Novelty`
tracking, and the trait framework that steers them. Pure logic, tested against
mocks; the runtime loop that drives the actuator + cues + memory logging is the
Phase 10 integration and needs the camera.

### B8 — Go-to-object
"Go to the red cup" → detect the object (a custom SenseCraft model, or the
built-in 80-class COCO classifier) → approach controller (the `Avoider`
bearing/area math, inverted to close distance instead of open it) → stop when
close. Ambitious; a headline demo.

### B15 — Recognize household members  🟡  ⚪
Train the vision model to detect **specific individuals as their own classes**
(household people and pets), not just generic "person" / "cat" / "dog". Petoi
SenseCraft custom-model pipeline: a few dozen labelled photos of each → YOLOv8n →
deployed on the Grove Vision module. Then G2:
- **knows its household by relationship, not just by label.** A per-individual
  **`bond`** in the `personality` layer, with:
  - a **closeness level** (0..1) that scales warmth, how much G2 seeks that
    person out, greeting intensity, and how much of their memory context gets
    pulled;
  - a **disposition** — `affectionate` / `playful` / `curious` / `wary` /
    `fearful` / `neutral` — that steers the `Explorer`: affectionate → approach
    + greet; playful → follow + try to engage (safety reflex still overrides);
    **`curious` → approach and try to interact**; wary → keep distance;
    **fearful → always avoid, not just react on sight** — invert the approach
    math to open distance and suppress wandering toward that bearing the
    instant it's seen, *and* bias wander headings away from its last-known
    position (the opposite pull from `Novelty`'s curiosity) so exploring routes
    around where it likely still is, not just flinches away after the fact;
    heads for the closest trusted person if cornered.
  Bonds are **seeded** (they don't start at zero for known members) and drift
  with interaction over time. G2 tells Claude who is present so replies and
  behaviour are personalised. `Novelty` already makes a regularly-seen face
  low-interest and one unseen for a while interesting again.
  - **New people default to `curious`, not `neutral`.** A detected person who
    doesn't match any known bond — a guest, a new face — gets a fresh low bond
    at `curious`: G2 approaches and tries to interact (greets, asks who they
    are) rather than staying reserved. New *pets* default to plain `neutral`
    (curious-about-people is specifically a people thing, not carried over to
    every new animal). The bond then drifts from that first interaction, same
    as any other.
- **notes stable patterns, not a timeline** — "the dog likes the kitchen", not
  "saw the dog at 3pm". No dated/timed logging of who was where when (the memory
  layer rejects temporal detail anyway); feeds [B11] place memory;
- optionally a gentle **follow / keep-an-eye-on** behaviour (composes with [B8]).

> **The household roster — names, which pet, seed closeness + disposition per
> member — is per-deployment personal data and lives ONLY in gitignored local
> config** (`G2_BONDS` in `.env`; see `.env.example`). Nothing about a specific
> real person or pet goes in a tracked file.

**On-device only.** The Grove Vision module runs the model on-chip and sends
*detections* (label + box) over serial — no images of anyone or the home leave
the robot. A 192×192 detector recognising one specific person is coarse
(lighting- and angle-sensitive); treat a hit as a guess, not proof, and let the
voice interaction confirm.

Needs the camera + the custom-model workflow (Phase 8 "train a custom detection
model" bullet). The per-individual classes are the only new piece; everything
downstream reuses the personality / behavior / memory layers already built.

### B16 — `CliffGuard`: ledge / desk-edge avoidance  🔴 HIGHEST PRIORITY once the camera lands  ⚪
G2 spends most of its time on the user's desk. It needs to explore and look
around up there (curiosity, [B7]-style wandering) but must **never** walk off
the edge — ranked above general exploring, since it's the precondition for
ever letting explore mode run near one.

**Not trainable into the gait.** Confirmed architectural fact, not a design
choice: the walk policy has no forward perception, and the real Bittle has no
foot-force/torque sensing either, so it can't even feel "no ground" reactively
the way it feels a stumble. By the time a cliff would show up in the policy's
own senses it's already committed. So this has to live entirely **above** the
gait, as a hard reflex that decides whether to command forward motion at all —
same reasoning as why folding ledges into walk-policy training (Phase 4a)
just made it timid.

**Design — a new local reflex, stricter than `Avoider`:**
- **Zero debounce.** `Avoider` waits a couple of consecutive frames before
  reacting (avoids flinching at noise). One confident "not floor" reading here
  is an immediate full stop — no waiting for confirmation. Bias entirely toward
  false stops over a missed edge.
- **Preempts everything** — explore mode, patrol, go-to-object, even a direct
  voice command to keep walking. Sits above the personality/behavior layer, not
  inside it.
- **The light classification path** (`vision/scene.py`'s `classes()`, floor vs.
  edge — no box regression) rather than full object detection: faster, simpler,
  and every frame counts here.
- **On trigger:** hard stop, back away from the triggering direction, re-orient
  toward the confirmed-floor side.

**Making the classifier actually reliable:**
- **Custom-train it on the real desk**, not a generic "table edge" model — the
  camera's actual mounted height/angle, multiple times of day, and deliberately
  including tricky cases (an object near the edge, glare, a shadow crossing the
  boundary).
- **Calibrate the confidence threshold toward paranoia** — anything not
  confidently "floor" counts as "edge." This is the one place in the whole
  project where excess caution is the *correct* failure mode.

**Buying reaction margin, not just accuracy:**
- **Slow to creep speed specifically during desk exploration** — more frames
  pass, less distance covered, before reaching wherever a missed frame put it
  (the detection feed is ~10–30 FPS and holds stale between frames).
- **Use the neck/head DOF to actively glance down-and-ahead** periodically while
  exploring — a level gaze mostly just sees "the floor stopped being visible," a
  weaker cue than actually seeing the drop. Dog-like, in-character for a curious
  personality too.

**The honest limit — vision alone can't promise "never":**
- A physical boundary/lip on the desk as a backstop, at least early on.
- Gate full *unsupervised* desk-roaming to when the primary bond is detected
  present (ties into the `personality` bond work), building trust in the
  reflex under supervision before ever leaving it alone.
- Log every `CliffGuard` trigger, so false-positive rate and any close calls are
  visible before loosening the leash.

Needs the camera + a custom-trained classifier — fully gated, nothing to build
or train on the RL/gait side right now. When the camera lands, this is a day-1
custom-model priority (`hardware-readiness.md` Day-1-with-the-camera checklist),
ahead of [B15].

### B11 — Learn its way around the house (topological place memory)
G2 builds up a sense of *where it is* over time — as **place recognition + a
graph of places**, never a metric floor plan (no depth/lidar, and monocular
VSLAM is out of reach on a 512 MB Pi with a 192×192 low-FPS camera).

- **Places:** at a spot, capture the view and store a scene description in the
  memory DB ("kitchen: checkerboard floor, fridge base on the right, dark
  doorway ahead"). Match a fresh view against stored ones to re-localize.
  Matching, cheapest first: Claude compares descriptions → perceptual hash of
  the thumbnail → image embeddings w/ cosine similarity (if the Grove module or
  a tiny model can emit them).
- **Map:** nodes = recognized places, edges = "walked forward ~15 s from A,
  arrived at B." A graph, not coordinates.
- **Landmarks:** persistent distinctive objects (fridge, couch, a rug, a door)
  as anchors; Claude reasons over the detection list ("couch left, TV ahead →
  living room, facing the hall").
- **Between anchors:** short-range dead reckoning — gait-cycle count → distance,
  yaw-rate integration → heading. Drifts; **resets on every recognized place**
  (topological loop closure).
- **Storage:** extend `pi_pipeline/memory/` with a `places` table (label,
  description, hash/embedding, adjacency, last-seen, associated events). Same
  cross-session mechanism as conversation memory, pointed at location. Needs
  confidence + decay — furniture moves, doors change.
- **Known failure modes:** perceptual aliasing (similar corners) → turn-and-scan
  multi-view + context chaining; lighting/time-of-day drift → several
  observations per place; low camera height → mostly baseboards/chair legs, a
  pitch-up glance helps; no global frame, only "this place connects to that."

Realistic end state: reliably answers "which room am I in?" and "roughly which
way is the kitchen / my charger?", navigates there landmark-to-landmark
re-localizing at each, and occasionally gets lost and has to wander until
something looks familiar. Composes with B7 (patrol) and B8 (go-to-object).
Software on top of vision + link + memory; no new hardware.

**What comes "free" with Claude vs what you build:** the *reasoning* is free —
match this view to a known place, "couch + TV = living room", pick a heading —
and early on you can skip embeddings entirely and let Claude compare text
descriptions. What is NOT free: Claude is stateless per call, so the persistent
`places` store, loading the relevant subset back into each prompt, the
perception pipeline that produces the scene description, a cheap retrieval
pre-filter once the map outgrows the context window (recency / adjacency /
hash), the actuation loop (intent → serial tokens → monitor → re-query), and
the local reactive + safety layers. Same split as the rest of the project:
Claude is the brain on a slow, billed, connectivity-dependent clock; the
scaffolding that makes its decisions actionable and remembered is the work.

---

## Authoring

### B10 — Teach me a trick
Conversationally record a joint sequence you puppet ("G2, when I say 'spin', do
this…"), save it as a new skill in the memory DB, and expose it to
`perform_skill`. Memory + link + a small authoring flow layered over the Skill
Composer idea (B3).

---

## Self-awareness

### B12 — "I'm running low" — power awareness
G2 estimates its own remaining runtime and says so, in character, before it dies.
The PiSugar S has no battery telemetry (only "external power present"), so this
is a **timer**, not a gauge: track uptime since last on the charger, warn once it
passes a threshold learned from real battery-life testing, escalate as it nears
the empirical limit, reset when placed on the charger. Optional later upgrade:
an ADC on a BiBoard Grove analog pin (G3/G4) reading pack voltage for a true
signal. Needs battery-life data first (idle / walking / talking / vision-on runs
to brown-out, repeated). Software on the voice pipeline + memory.
See the "Power awareness" note in `docs/project-plan.md`.
