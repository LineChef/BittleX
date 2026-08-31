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

### B3 — Skill Composer authoring
Stand up a workflow around **Petoi's Skill Composer** (the no-code desktop tool
for authoring keyframe skills — puppet the robot over USB, loop/sequence poses,
export to an `Instinct*.h` array). This is the authoring capability that B4
(expressive body language) and B10 (teach-me-a-trick) build on. Needs hardware.

---

## Expression & personality

### B4 — Expressive body language
A small set of authored skills for emotion/emphasis — happy wiggle, play-bow,
nod-yes, shake-no, moonwalk — added to the `perform_skill` catalogue so Claude
can punctuate spoken replies with body language, not just perform functional
gaits. Low effort once B3 exists; high payoff for how alive G2 feels.

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
vision + avoidance + voice + link together — a good capstone.

### B8 — Go-to-object
"Go to the red cup" → detect the object (a custom SenseCraft model, or the
built-in 80-class COCO classifier) → approach controller (the `Avoider`
bearing/area math, inverted to close distance instead of open it) → stop when
close. Ambitious; a headline demo.

---

## Authoring

### B10 — Teach me a trick
Conversationally record a joint sequence you puppet ("G2, when I say 'spin', do
this…"), save it as a new skill in the memory DB, and expose it to
`perform_skill`. Memory + link + a small authoring flow layered over the Skill
Composer idea (B3).
