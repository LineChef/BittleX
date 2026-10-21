# How It Works

A plain-language tour of G2's parts: **walking, voice, memory, vision, behavior and the link**. Enough to understand the shape of each without reading the code. How the modules fit together technically: [`architecture.md`](architecture.md). What is working right now: [`STATUS.md`](STATUS.md).

The guiding design choice: these are **independent systems**, not one "brain." Voice, memory, vision, behavior and the robot link are separate modules that reach each other only through small, deliberate seams. Walking is a separate effort again, trained in simulation. That keeps each piece testable and replaceable on its own.

---

## Walking

**The goal:** a four-legged robot that walks without every joint movement being hand-authored, so the gait can adapt instead of replaying a fixed animation.

**Reinforcement learning, on top of a scripted walk.** G2 does not learn to walk from nothing. Petoi's firmware ships a scripted walk (`wkF`). A policy is trained in a physics simulation (PyBullet, Stable-Baselines3) whose output is a small *correction* added to that scripted walk, bounded to ±30° per joint. The training reward gives points for moving at the commanded speed, staying upright and not jittering, and the simulation throws hazards at it (slopes, ledges, rubble, shoves) on a curriculum that never ramps above what a capable policy can pass. A 20-million-step training run takes hours on the laptop.

**What comes out** is a small neural network exported to a file under 1 MB (ONNX) plus a sidecar with its settings. On G2 it runs on the Pi at 80 Hz, reading the IMU and the last joint commands, and adding its correction to the scripted walk. It re-decides every few milliseconds from what the body is doing, which is why it corrects balance continuously.

**On the real robot, extra layers sit around it:**

- a closed-loop trim of the front-left foot that holds the starting heading (the front feet steer G2);
- an eased stand-up ramp before any walk, and an eased move into every firmware skill;
- guards for servo heat, jams, falls and battery under load;
- carpet detection from the IMU, since carpet changes how he slips.

**What it can and cannot do.** It makes constant small corrections: good balance, straight tracking, small obstacles and light shoves. It cannot make dramatic saves or get up after tipping over; the robot physically lacks the joints. The sensors are also coarse (a 5 Hz IMU, no fast joint feedback), so the policy cannot anticipate hazards, only react to them.

**Vision and walking stay separate.** Putting vision inside the walking policy was tried across several campaigns and closed: a policy that could see ahead learned to plow through obstacles instead of bracing. Vision instead acts above the gait, choosing a scripted skill or slowing the speed command. Details: [`archive/rl/vision-in-gait.md`](archive/rl/vision-in-gait.md), [`rl/walking-policy.md`](rl/walking-policy.md), [`guides/gait-deployment.md`](guides/gait-deployment.md).

---

## Voice

**The goal:** talk to G2 and have him talk back, powered by Claude, with the robot able to move in response.

**One conversation turn, start to finish:**

1. **Wake word.** G2 listens locally for his name ("gee two"). Nothing else happens until he hears it, so he is not constantly recording or calling the network. After a reply the microphone stays open for a short follow-up window so you do not repeat the name every turn; a question opens a longer one. "Let's talk" starts a conversation mode that listens without the wake word until a quiet gap.
2. **Listen.** What you say is transcribed on the Pi (Vosk).
3. **Local commands first.** A set of spoken commands never reach Claude: stop and emergency stop, sleep and shut down, "the floor is tile", "walk for ten seconds", and more. They are fast, free and work offline. [`guides/voice-commands.md`](guides/voice-commands.md)
4. **Think.** Anything else goes to Claude through the API, together with relevant memory. Claude replies with words and may call a tool to move.
5. **Speak.** The reply is turned into speech on the Pi (Piper), run through a robot-voice effect, and played on the speaker. The next sentence is synthesised while the previous one plays.
6. **Act.** If Claude called `perform_skill` (sit, wave, walk), the command goes out over the link.

Only step 4 uses the cloud, and API calls are used sparingly. G2 also plays short sounds (a chime at the wake word, cues when the gait switches or a picture is taken) so you can tell what he is doing without looking.

**Where it runs:** on the Pi, started at boot as a service. On a laptop the same code runs in text mode with mock hardware.

---

## Memory

**The problem:** Claude has no memory between calls. Every API request starts blank.

**The fix:** a small local database (SQLite) on the Pi holding the full log of every exchange and a short list of durable facts worth keeping ("their name is Sam," "they have a cat named Biscuit").

**How it is used:** before each message to Claude, the memory system assembles a short context block: a pinned core of the most important facts, the highest-ranked other facts (importance and recency), and any older conversations that look related to what you just said (a keyword relevance search over the log). It is prepended to the prompt, so Claude seems to remember without the whole history being resent.

**How facts are created:** Claude decides. When you say something durable, it calls the `remember` tool, with no extra API call.

**Keeping it tidy:** when G2 has been idle a while (or is told to go to sleep), one consolidation call merges duplicate facts and drops trivial ones, with every change logged. A command-line tool (`python -m pi_pipeline.memory …`) lets you view, search, add, pin or prune what G2 knows. Memory is not coupled to movement or vision.

---

## Vision

**The hardware:** a small camera module that runs object detection on itself, not on the Pi. It sends the Pi a running list of what it sees (labels and bounding boxes) over USB serial. For a picture, the Pi asks for one small frame.

**What is done with it:**

1. **Awareness and avoidance.** A fast local reflex watches the detections and, with a wall-distance estimate from pictures, turns G2 away from a near wall. No Claude, no network.
2. **"What do you see."** On request, one picture goes to Claude along with the detector's labels, and G2 describes the scene aloud.
3. **Exploration pictures.** During exploration G2 stops at times to take pictures of things worth a look. A review page lets you name them, and named things are what recognition builds on.

**Recognition is by instance, not category.** The detector knows a handful of specific things. For everything else there is a second system that fingerprints a photo crop and compares it with a library of earlier ones: a close match means "the same thing again," nothing close means "something new," which joins the library unnamed until someone names it. It runs only in moments G2 is already standing still, caps its disk use, and never uploads anything. The pieces exist and are tested; wiring them into exploration is not finished.

The camera's firmware is frozen, which constrains which detection models can run: [`vision/custom-model-recipe.md`](vision/custom-model-recipe.md). Index: [`vision/README.md`](vision/README.md).

---

## Behavior

**The goal:** G2 does things on his own, not only when asked.

A single function, `BehaviorDriver.tick()`, reads the current inputs (detections, IMU, voice commands, battery) and returns an ordered list of effects (move, chirp, speak, take a picture). It never touches hardware itself; a binding layer turns effects into real actions. That keeps all of the autonomy testable with no robot.

Composed into that one tick:

- **Exploration**, in two tiers: an always-on stationary "attentive" tier (look at things, react, scan) and a voice-armed "roam" tier that walks, with wall avoidance, a hit detector from the IMU, and picture stops;
- **idle posture** (sit, then lie down, with small signs of life) and **sleep mode**;
- a **thermal governor** that backs off when servos run hot;
- **emergency stop**, which outranks everything.

**Personality** is a set of composable traits (curiosity, mood, bonds and others) that each shape both the prompt Claude sees and the behavior parameters. Guide to exploration: [`guides/exploration-mode.md`](guides/exploration-mode.md).

---

## Link

**What it is:** the plumbing between the Pi and the robot's control board (the BiBoard, running Petoi's OpenCat firmware). They talk over a serial cable using short text commands: `kwkF` is walk forward, `ksit` is sit, `d` is lie down and relax.

**Why it is its own module:** voice, behavior and the gait loop all send commands, so there is one shared link instead of each reinventing serial handling.

**What it handles:** opening the connection and reconnecting after the cable is unplugged without crashing the caller; building command strings; refusing dangerous commands (calibration, factory reset); and logging every command to a replayable trace. Diagnostic tools list ports, ping the board and exercise each skill: [`hardware/petoi-firmware-reference.md`](hardware/petoi-firmware-reference.md).

---

## How they fit together

- **Memory to Voice:** one function pair. The voice loop asks memory for context before each Claude turn and hands it the result afterward.
- **Vision to Voice and Behavior:** vision produces detections and plain-text scene summaries; it calls an injected "ask Claude" function and never imports voice code.
- **Voice, Behavior and the gait loop to Link:** all send commands through the one shared serial link.
- **Walking** stands slightly apart: trained on a separate machine, deployed as one exported file, and run on the Pi as a loop that streams joint commands through the same link.
- **Diagnostics** cut across all of it: a per-session event log with a black-box ring buffer, so a hardware failure leaves enough context to debug afterward.
