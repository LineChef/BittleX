# How It Works

A high-level tour of the five parts of the project — **walking, voice, memory,
vision, link** — enough to understand the shape of each without reading the code.
For specifics see each area's own README and `docs/project-plan.md`.

The guiding design choice: these are **independent systems**, not one "brain."
Voice, memory, vision, and the robot link are separate modules that don't reach
into each other except through small, deliberate seams. Walking (the RL policy)
is a separate effort again. This keeps each piece testable and replaceable on its
own.

---

## Walking

**The goal:** get a four-legged robot to walk without hand-authoring every joint
movement, so the gait can *adapt* rather than replay a fixed animation.

**The approach — reinforcement learning.** Instead of writing "move this joint to
40°," you build a physics simulation of the robot, define a *reward* (points for
moving forward, staying upright, matching a clean trot rhythm, not jittering),
and let a training algorithm (PPO) try millions of times, keeping the behaviour
that scores well. Training runs in a PyBullet simulation on the laptop — about 40
minutes per run.

**What comes out** is a *policy*: a small neural network (~3 MB file). Many times
a second it reads the robot's state — body tilt from the IMU, the last few joint
positions, a rhythm clock — and outputs a small adjustment to each of the 8 leg
joints. It's reactive by construction: it re-decides every fraction of a second
based on what the body is actually doing, which is why it corrects its balance
continuously and rarely falls.

**On the real robot** the policy would run on the Pi, reading the IMU and
streaming joint commands to the BiBoard over the serial *link*.

**What it can and can't do.** It makes constant tiny corrections (good balance,
straight tracking, handles small obstacles and light shoves). It **cannot** do
dramatic saves or get back up after tipping over — the robot physically lacks the
joints for that (no roll-axis actuation, weak leg servos). So the learned walk is
**paused** until it can be compared head-to-head against Petoi's built-in scripted
walk on real hardware; if it holds up, work resumes to feed *vision* into it so
the robot can anticipate terrain rather than just react to it.

---

## Voice

**The goal:** talk to G2 and have it talk back, powered by Claude, with the robot
also able to move in response.

**One conversation turn, start to finish:**

1. **Wake word** — G2 listens locally and cheaply for "hey gee two." Nothing else
   happens until it hears that, so it isn't constantly recording or calling the
   network.
2. **Listen** — it records what you say and transcribes it to text on-device
   (Vosk).
3. **Think** — the text goes to Claude via the API, together with any relevant
   *memory*. Claude replies with something to say, and optionally an instruction
   to perform a physical skill.
4. **Speak** — the reply is turned into speech on-device (Piper, currently the
   "Alan" British voice) and played.
5. **Act** — if Claude asked for a skill (sit, wave, walk), that goes out over
   the *link*.

Only step 3 uses the cloud. Listening and speaking are fully local.

**How Claude triggers movement:** it's given a tool called `perform_skill` with a
menu of things G2 can do. When it wants G2 to move it calls that tool; its spoken
reply comes back as ordinary text in the same response. A second tool,
`remember`, is how *memory* gets written (below).

**Where it runs today:** end-to-end on a laptop — you type instead of speaking,
and it replies through the laptop speakers. Moving to the Pi's real mic, speaker,
and the robot is a configuration change, because every hardware-specific step
sits behind a swappable interface with a mock version.

---

## Memory

**The problem:** Claude has no memory between calls. Every API request starts
blank.

**The fix:** a small local database (SQLite) on the Pi that holds two things —
the full log of every exchange, and a short list of durable *facts* worth keeping
("their name is Mark," "they have a cat named Biscuit").

**How it's used:** before each message to Claude, the memory system assembles a
little context block — the current facts, plus any older conversations that look
related to what you just said (a keyword relevance search over the log) — and
prepends it to the prompt. Claude effectively "remembers" without us resending
the entire history every time.

**How facts get created:** Claude decides. When you say something durable, it
calls the `remember` tool. No extra API call, no separate summarisation step.

**Keeping it tidy:** a fact you haven't come up in a while quietly drops out of
the injected list once it fills up — it stays in the database, just isn't sent
every turn. A command-line tool (`python -m pi_pipeline.memory …`) lets you view,
search, add, or prune what G2 knows.

---

## Vision

**The hardware:** a small camera module that runs object detection *on itself*,
not on the Pi. It sends the Pi a running list of what it sees — object labels and
bounding-box positions — over serial. It cannot send actual images (the robot's
control chip can't handle that), so everything downstream works from the
detection list.

**Two things are done with that stream:**

1. **Obstacle avoidance** — a fast, local reflex. It watches the detection boxes;
   a box that is large and centred means something is close and dead ahead, so it
   decides *stop*, *back up*, or *steer around*. This has to react within a few
   frames, so it uses no Claude and no network. It's debounced so a flickery
   detection doesn't make it twitch, but a genuinely urgent hazard overrides the
   debounce.
2. **"What do you see"** — the detections are summarised into a sentence and
   handed to Claude (through the voice layer's callable), so G2 can describe its
   surroundings out loud when asked.

**Where it runs today:** against a mock detection feed — a scripted "obstacle
approaching" scenario — so the avoidance logic and the description path are fully
testable now. The real camera's message format has been confirmed and the parser
for it is written.

**Later:** once vision is working on hardware, feed the detections into the
*walking* policy so the robot can plan around obstacles it sees rather than only
reacting to ones it bumps. That is the main thing a learned gait can do that a
scripted one cannot.

---

## Link

**What it is:** the plumbing between the Pi and the robot's control board (the
"BiBoard," running Petoi's OpenCat firmware). They communicate over a serial
cable using short text commands — `kwkF` = walk forward, `ksit` = sit, `d` = lie
down and relax.

**Why it's its own module:** *voice* needs it to send skills, *vision* needs it
to send avoidance moves, and RL deployment would need it to stream joint angles.
Rather than each reinventing serial handling, there is one shared link.

**What it handles:** opening the connection and reconnecting if the cable is
pulled — without crashing whatever is using it; building the command strings
correctly; and refusing dangerous commands (calibration, factory reset). It also
ships a diagnostic tool to list serial ports, ping the board, send a single
command, or cycle through every skill as a hardware bring-up test.

---

## How they fit together

- **Memory → Voice:** one function call. The voice loop asks memory for context
  before each Claude turn and hands it the result afterward.
- **Vision → Voice:** vision produces a plain-text scene summary and calls an
  injected "ask Claude" function; it never imports the voice code.
- **Voice / Vision → Link:** both send the robot commands through the one shared
  serial link.
- **Walking** stands apart: its own training project, and on the robot it would
  be a process streaming joint commands through that same link.
- A future integration layer (Phase 10) runs these together — the voice loop
  listening, the vision reflex watching for obstacles and occasionally narrating,
  memory persisting across it all — sharing the link to the robot.
