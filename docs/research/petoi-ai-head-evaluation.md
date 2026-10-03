# Petoi Bittle AI Head — evaluation plan: replace the Raspberry Pi, sit alongside it, or skip it

Opened 2026-10-02. The head ([product page](https://www.petoi.com/products/bittle-ai-head-upgrade-kit), $39, 42 g) is
**ordered, arriving around 2026-10-10**. What isn't answered by Petoi's documentation we find out **first-hand** with the
steps below. **Keeping the Pi is a fully valid outcome** if it earns its place.

What the head is (Petoi, 2026-10-03): an **ESP32-C3** with a microphone and a speaker and 16 MB of flash, running firmware based on the
ESP32 XiaoZhi project (Espressif ESP-IDF) that Petoi plans to open-source. It talks over Wi-Fi to the XiaoZhi cloud LLM by default,
wakes on "Hi, Jason" or the Boot button, needs internet and a free account, sends Petoi serial-protocol commands (skill codes like
`ksit`, `kwkF 3`) to the BiBoard through a Grove socket (UART2), and is documented for BiBoard V1 / NyBoard V1. **No camera is
mentioned in Petoi's description** — recognition questions were answered by pointing to the separate Petoi AI Vision Module (the
Grove Vision AI V2 we already own). Treat "the head has a camera" as unconfirmed, probably false, until the unit arrives.

## What has to be found out (open questions)

Access: does the head give a host its microphone audio, a way to play audio or text through its speaker, camera detections or
frames, transcripts and tool calls? Can its backend be changed to one we control, and is its motion output switchable to
"talk-only" or redirectable? Protocol and ports: exactly what it sends to and receives from the BiBoard (port, baud, framing,
message list, joint-level moves and rates), which Grove port and UART it uses, and whether it coexists with a Pi on the 5-pin
Serial-2 header and the onboard voice module. Compute and firmware: is the firmware open, how much CPU/RAM/flash is free for our
code, can an 80 Hz loop run on it, which toolchain, can OTA updates be pinned, and what is the recovery path. Robot data: does it
receive the BiBoard's IMU, battery or servo feedback. Failure and power: behavior when Wi-Fi or the cloud is down, an e-stop that
doesn't depend on the cloud, and its current draw and supply. Camera: how models are trained and deployed, on-device vs cloud and
offline, class/input/frame-rate limits, per-person recognition. Voice: microphone performance with servo noise, wake word,
languages, latency, interruptibility. Memory and data: where conversation memory lives and whether it can be read, exported and
deleted; what data leaves the device and for how long; free-tier limits, later cost, terms, and what happens if the service
changes. Mechanics: does the kit drive the head servo, how the camera is mounted and moves, and the mass (42 g vs the ~15 g the
sim assumes for the camera head). BiBoard requirements: firmware version, module flags, and whether installing it changes stored
settings such as Serial-2 (`XS`) mode.

## What Petoi has told us (2026-10-03)

| Topic | Answer | What it means for us |
|---|---|---|
| Hardware | ESP32-C3, microphone, speaker; 16 MB flash, about a third free, with a 4 MB OTA partition; ESP-IDF | single-core, no FPU: little headroom for our code next to Wi-Fi, audio and the LLM client |
| Firmware | to be open-sourced (not released yet); you can modify it and write your own applications | everything below that says "modify the firmware" waits for the source |
| Mic audio to a host | processed internally; could be modified to stream out | custom firmware work |
| Speaker driven by a host | yes — define a protocol so a host sends text or audio playback commands | custom firmware work, but supported by design |
| Own backend instead of the XiaoZhi cloud | yes, by modifying the firmware | a server we control could put Claude, memory and personality behind it |
| Talk-only / motion redirected | yes, by modifying the MCP (motion control) | the Pi can keep sole control of motion |
| Link to the BiBoard | the existing Petoi serial protocol, including joint-level commands; the BiBoard listens on the UART when `XS` is on; rate depends on the implementation | the same protocol the Pi uses |
| Port | UART2 through the first Grove socket. **By default the Pi and the head share the same UART and can conflict.** Petoi has made some BiBoards without the built-in voice control module, so the head gets an independent serial port | our BiBoard has the voice module; see the UART options below |
| IMU / battery / servo feedback | not sent to the head by default; could be added over the serial protocol | closed loops stay on the Pi |
| An 80 Hz custom loop | "potentially" — 12.5 ms per iteration, depends on the cost and on resources shared with other tasks | doubtful on a single-core C3 running Wi-Fi and audio |
| Offline / safety | the default firmware periodically reminds users to reconnect; Petoi recommends keeping the e-stop and watchdog on the BiBoard or another local controller | the Pi's safety layers stay |
| Power | tested while moving, but no idle / speaking / peak figures; check the Grove 5 V and measure under load | we measure it (step 2) |
| Updates and recovery | OTA is off by default; flash or recover over a wired connection | the "pin updates" worry is covered |
| Logs | ESP-IDF serial logging; can add more | use the USB-C serial log to read what it sends |
| Memory and data | memory is managed on xiaozhi.me; by default audio goes to a speech-to-text service, the text to the LLM server, the reply to a text-to-speech service; the provider's policies govern retention; Petoi sees no conversations; your own backend gives you control | privacy gate stands; a self-hosted backend is the privacy fix |
| Camera and models | recognition runs locally on the Petoi AI Vision Module and works offline; forwarding detections to a host needs development; individual identification depends on the model | the camera question is about the Vision Module, which we already have |

**Petoi's own view:** the head could **complement** the Raspberry Pi rather than replace it — the C3 suits lightweight audio and AI
interaction, the Pi carries the learned walking policy, safety layers and behavior runtime. Some of the integrations we described need
custom firmware development and testing.

### From Petoi's AI Conversation guide (read in full 2026-10-03)

Source: [AI conversation](https://guide.petoi.com/extensible-modules/ai-conversation) (raw text at `.md`), with the
[BiBoard V1 guide](https://guide.petoi.com/biboard/biboard-v1-guide) and the
[serial protocol](https://guide.petoi.com/apis/serial-protocol).

- **Setup flow:** swap the stock head for the AI head on the head servo; wire it through Grove (the guide shows three diagrams — BiBoard V1
  **without** the voice module, BiBoard V1 **with** the voice module, NyBoard V1; diagrams only, no text, so read them on the unit). Power on,
  join the `Xiaozhi-…` hotspot, `http://192.168.4.1` opens, pick a **2.4 GHz** network (the module remembers several, retries each five times,
  then tries the others, then says "Please configure the network"; a short **Boot** press re-enters network setup). Then activate at
  [xiaozhi.me](https://xiaozhi.me/): **first-time users must register with a mobile phone number** (a privacy and throwaway-account issue
  for the privacy gate), Console → Add Device → the 6-digit code.
- **What the cloud console configures:** a **Role** tab (voice, introduction/prompt), **Model & Memory**, **Speaker Recognition** (not on the free
  plan) and **Extensions**. The wake word is "Hi, Jason" (or Boot; Boot also stops the current conversation). No wake-word option is documented.
- **How the LLM moves the robot:** through a tool named **`self.robot.send_command`** whose parameters are plain Petoi command codes (`ksit`,
  `kwkF 3`); the prompt forbids descriptions like "sit down(ksit)". Petoi's default prompt makes the dog nod (`knd`), shake its head (`kwh`),
  check (`kck`) or scratch (`kscrh`) when no action is requested, and send `d` (rest) before saying goodbye. The tool is generic, so the
  command string is the LLM's to choose. The founder's reply expanded MCP as "Motion Control Program", but this tool-naming matches XiaoZhi's
  **Model Context Protocol** — so a custom firmware or server could swap in, or add, tools (inference; check when the source is released).
- **Documented UART facts:** BiBoard V1's Grove sockets are **G1 = UART2, G2 = I²C, G3/G4 = analog**, serial baud 115200 (CH343P USB chip).
  G1 is the **only** UART-capable Grove socket, and it is the same UART2 as the 5-pin Pi header. If the camera's Grove cable is plugged into G1
  (the 2026-09-29 build notes say it connects to the Grove socket at the head), the head and the camera would also fight over the socket — and
  the camera now sends detections over USB, so check whether its Grove cable is needed at all, or can move to G2.
- **Not on any of the pages:** the serial protocol's full token list and timing, the BiBoard V1 pin tables, the head's camera (none mentioned),
  the firmware repository, and any list of available actions beyond the examples above.
- **Useful for our own pipeline:** Petoi's role template tells the LLM to keep replies to two sentences and plain text for speech (no
  markdown, asterisks, emoji or decorative punctuation), run several requested actions one by one with a short summary at the end, and pick a
  fitting default reaction (nod, shake, check, scratch) when asked nothing explicit. Our default prompt already says short, spoken, no markdown,
  lists or emoji. The default-reaction idea isn't covered: our voice skills have no explicit nod or shake-head entries (`knd` exists as a gesture),
  so it is a possible small addition, not done.

### Losing the Pi, item by item (2026-10-03)

"Gone" and "moves to the cloud" are different; this table keeps them apart. Assumes the head plus the BiBoard only, no Pi.

| Capability | With the Pi today | Without it | Gone or different |
|---|---|---|---|
| Walking | learned policy (V2.1) at 80 Hz | Petoi's scripted gaits with the firmware's gyro balance | **gone** (the learned gait), replaced |
| Reflexes | ours: fall guard, thermal guard, jam guard, carpet detector, watchdog, e-stop | Petoi's firmware reflexes remain (below), ours are gone | different: we lose the mid-walk catch, the heat estimate and the e-stop |
| "Feels alive" behaviors | behavior runtime (attentive, roam, idle descent, sleep and wake, gestures, mood, enrollment) at ~8 Hz | no deterministic runtime on the head; the LLM can call skills but not run timers and sensor loops | **gone** unless rebuilt as server or tool logic |
| Claude, personality, our memory | Claude API with SQLite memory and traits | XiaoZhi's LLM with its own platform memory; ours only if we host a backend | **different** — memory lives in their cloud (or ours); the design is not ours |
| Speech | local Vosk and Piper, works offline | cloud speech-to-text and text-to-speech; needs Wi-Fi and the internet | different; offline is gone |
| Vision into behavior | detections feed the behavior layer | the camera's stock path on the BiBoard (face detection model; `XC` on, `Xc` off) | different, and costly: enabling the camera mode kills the IMU task in current firmware |
| Dev loop | SSH, Python, logs, rsync, tests | ESP-IDF serial logs on the head, USB on the BiBoard | different, much weaker |

The firmware reflexes that stay (`imu.h`, `reaction.h`; `docs/hardware/petoi-firmware-reference.md`), all with gyro assist on:
flipped (roll > 85° with accel-Z near zero) plays a fall sound and runs the get-up `rc` once, repeating until upright; lifted
(pitch < −50° or > 75°), knocked, freefall and turning are detected; pushed runs a scripted side-step or forward/back corrective
gait then stands, **but only while standing, not while walking**; an off-direction heading error triggers an automatic turn; and the
servos have their own overheat protection and a low-battery cutoff (~7.0 V → rest, servos off).

### Forking (2026-10-03)

- **The head's firmware:** Petoi's source is not released yet. Today the closest public base is the upstream
  [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) project (MIT, very active, "an MCP-based chatbot", ESP32-C3 supported); you would
  also need the head's board definition (pins, audio codec), which only Petoi's release will give. Fork it, or Petoi's repo once public.
- **The BiBoard firmware:** [OpenCatEsp32](https://github.com/PetoiCamp/OpenCatEsp32-Quadruped-Robot) (MIT) is a separate matter; the
  project decision is to stay on stock firmware unless something truly can't be done from the Pi.

### What this does to the decision

- **Replacing the Pi looks unrealistic.** The learned gait, the safety layers, the behavior runtime and the Claude/memory path all run on
  the Pi; the head can't host them (single-core C3, no feedback data, no e-stop that doesn't depend on its software), so outcomes **C**
  (head only with scripted gaits) and **D** (our logic on the head) are now long shots. Outcome **A** (keep the Pi) and **B** (Pi + head)
  are the live ones.
- **If the head is used (B), it is a voice front end for the Pi,** with two ways to connect it:
  1. **Wi-Fi voice peripheral:** the head connects over Wi-Fi to a backend we control (the Pi, a laptop or a server speaking the XiaoZhi
     protocol), which calls Claude with our memory and personality and handles speech recognition and synthesis. The Pi keeps sole control of
     motion; the head's serial motion output is off, so there is no UART conflict (it would take power from a 5 V source, UART lines unused).
     Needs the firmware source, and a backend we write.
  2. **Independent serial port:** a BiBoard without the onboard voice module, so the head has its own UART (Petoi has made a few). Needs a
     different BiBoard, or a way to free the voice-module UART on ours.
- **Versus the I2S microphone and amplifier already ordered:** those work with the existing Pi pipeline with no custom firmware (mic and
  speaker driven by the Pi). The head's advantages would be fewer wires, an integrated look and less loose hardware; its costs are custom
  firmware and a backend before it does anything the Pi can't already do. Keep the I2S parts regardless.
- **Open items for the hands-on tests:** confirm whether it has a camera; the exact UART/pins the Grove socket uses and whether it can sit
  on a different port; whether the shipped firmware's server address can be changed without rebuilding; the power draw; and when the
  source is released.

### What the head buys alongside the Pi, and what a Pi-less G2 can do (2026-10-03)

**Head plus Pi gains little today.**
- With stock firmware the Pi cannot use the head's microphone or speaker (the head talks to its server over Wi-Fi, not to the Pi). Petoi says both can be
  opened to a host by modifying the firmware, and the Wi-Fi route (point the head at a backend on the Pi) avoids the UART entirely — see
  [`xiaozhi-esp32-review.md`](xiaozhi-esp32-review.md). Until that is built, the I2S microphone and amplifier are still needed.
  The head's motion control (LLM tool calls, synchronized nods) needs the UART2 line the Pi uses; sharing one UART between two command
  sources is untested and a hazard. So with the Pi in place the head is, at most, a standalone chat device. Petoi's promised open
  firmware could change this; that is a "watch for the release" item, not a reason to wait.
- Plan: install the microphone and speaker first and bring up the full voice pipeline on the Pi; re-evaluate the head after it arrives.

**Memory with a head-only build.** The default backend (xiaozhi.me) keeps its own memory. Memory stays ours if we host a backend (it can call
Claude and use our SQLite memory), but that backend has to run on some machine — a laptop or cloud host if there is no Pi on G2.

**The head's own conversation.** General chat ("how are you feeling today?") works through XiaoZhi's LLM with a role prompt. "What do you
see?" does not: the head has no camera, and XiaoZhi has no vision input; it would need a custom tool that fetches detections from
something that can read the camera. The stock Bittle head position has been removed, and the camera mounts separately from the head
servo, so there is **no head/camera mounting conflict**; the weight question is unchanged (step 12).

**The camera without the Pi.**
- Petoi's firmware (`camera.h`, OpenCatEsp32 `main`) reads the Grove Vision AI V2 over Grove and tracks the first detection with head
  pan/tilt; with `#define WALK` it also walks toward or away (`wkF`/`wkL`/`wkR`/`bk`). The Grove Vision path treats detections
  generically (no per-class logic), so our classes would need firmware edits.
- **Cost:** entering camera mode deletes the IMU task (`groveVisionSetup()`), with no restore path, and the enabled state persists
  across reboots. No IMU means no gyro balance, no fall/flip detection and none of the firmware reflexes. The 2026-09-28 `Xc` disable did
  not restore it; only an erase + reflash did.
- **Camera only while stationary** would need a small firmware patch (recreate the IMU task when the camera is disabled), i.e. a narrow
  fork. Not supported by stock firmware. With the Pi in the build none of this applies: the camera is on the Pi's USB and the IMU
  streams at 5.0 Hz.
- Unverified (test with the head): whether the head's firmware can read the Grove camera at all, and how `camera.h` behaves on our
  firmware build.

**Exploration with the head alone.** Only a basic version. The camera code gives follow/approach, not roaming; real exploration (leash,
ledges, voice arming, memory) is our Pi-side `explore` code. Ways to build it without the Pi: an LLM calling movement tools through
XiaoZhi MCP (seconds of latency, no sensor feedback unless built), firmware edits, or the firmware's own obstacle modules. Our camera
has only a face model, so any exploration would be blind to obstacles and ledges.

**The firmware's built-in distance modules** (from OpenCatEsp32 `main`, summarized by a fetch tool, not a line-by-line read; check the
source before relying on thresholds). Neither is owned.

| Module | Hardware | Behavior |
|---|---|---|
| Ultrasonic (`XU` on, `Xu` off) | RGB ultrasonic on the first Grove socket (UART2 — the same UART as the Pi header and the head) | A reactive demo, not navigation. By distance: idle > 60 cm; LED colors and gaze/attentive posture 30–60 cm; random `wkL`/`wkR`/sit 15–30 cm; sit and twitch 10–15 cm; meows and servo adjustments 5–10 cm; under 5 cm a random backward step (`bkL`/`bkR`), sniff or sit |
| Dual IR distance | two IR sensors on ANALOG1/ANALOG2 (no UART conflict) | Real avoidance. Walk mode (`IR_WALK_AVOID`): clear path `trF`; under 4 cm turn in place (`vtR`/`vtL`); 4–10 cm back up then turn; uneven readings turn toward the clearer side; detection threshold about 20 cm. Sit mode (`IR_SIT_TRACK`): head-only tracking. The module manager notes bugs in it |

Neither detects a ledge, and neither has a leash, memory, voice arming or camera integration. A Pi-less G2 could get a bumper-style
wander with the IR pair, not our exploration.

**Corrected summary.** Head plus Pi: little gain today. Head instead of the Pi: G2 keeps stock gaits (gyro balance on), cloud chat,
tool-based custom behavior, and a camera that tracks with the head but disables the IMU; it loses the learned gait, our reflexes, the
behavior runtime and our memory design.

## How the decision will be judged

1. **Is the scripted gait about as good as the learned gait?** If it is, an RL policy may not be needed for walking —
   though the owner would prefer to keep it (it is interesting, and its potential isn't fully tapped yet). This is the
   open H1 head-to-head (`docs/rl/real-walk-log.md`): so far V2.1 walks ~0.118 m/s on hard floor, about the scripted
   ~0.12 m/s, and both fail on carpet; no matched, scored comparison yet. Note the real servo/limb issues found on
   2026-10-02 (FL shoulder servo) have to be fixed before a fair comparison.
2. **Can G2 still do most of the behaviors that make it feel alive?** If yes, that is a point for replacing the Pi.
   Inventory below.
3. **The build trade-off** (not a pass/fail, but real): the Pi build means a lot of soldering, wires and mounting, and a
   heavier body with exposed boards and connections (Pi + PiSugar ~61–78 g riding on a printed standoff; mic, amp,
   camera and their wiring still to add) — more vulnerable. A single head module is ~42 g and far more streamlined.
   This was always a learning project and the wiring work has been worthwhile, but robustness and simplicity count.
   Against that, the head may cost capability (below), adds a cloud dependency, and sends audio/camera data off-device.

Other considerations to record, not to lose sight of: privacy (audio and images leaving the house), cost after the free
tier, what happens if the service changes or shuts down, loss of the SSH/Python dev loop that produced all of the
2026-10-01/02 hardware data, and that the BiBoard already has Petoi's own balance, fall and self-right reflexes.

## Behavior inventory — what would need to survive

From `docs/capabilities.md`. "Needs today" is what makes it work now; the last column is what to check on the head.

| Behavior / capability | Needs today | Check on the head |
|---|---|---|
| Learned walking policy (V2.1, 80 Hz) | host reading the IMU, joint commands to the BiBoard at ~27–80 Hz | can anything on the head do joint-level control at that rate? else scripted gaits only |
| Safety layers (fall guard, thermal guard, jam guard, carpet detector, e-stop, watchdogs) | on-robot loop with IMU + joint data | what does the head do if Wi-Fi/cloud drops; is there a local loop; which of these the BiBoard firmware already covers |
| Tier 0 "attentive": turn toward a sound, gaze-follow with head/body then satiate, react to novelty, periodic scan, greet known people | sensors + detections + head/body commands at ~8 Hz | detections reaching something that can act; sound direction; head servo control |
| Tier 1 "roam" (voice-armed walking exploration), "come here" approach, place memory | detections + walking commands; vision gating | same as above, plus walking commands from the head's LLM/skills |
| Idle-posture staged descent (peek, sit, rest, sleep), graceful shutdown, deep-idle sleep with wake on word/tap/loud sound, mood-scaled timing | a behavior state machine with timers and sensor events | can the head's LLM/skills reproduce timed state changes, or is any custom logic possible (own code, MCP/HTTP tools, a server we control) |
| Gestures, emotive chirps (buzzer melodies for recognition, startle, greeting, edge, sleep) | skill tokens + `beep` melodies | tool list the LLM can call; speaker can make non-speech sounds |
| Person enrollment (capture sessions, per-person recognition, bonds) | camera capture pipeline, named classes | how new models are trained/deployed, per-person recognition, exposing identity to a host |
| Claude conversation, tool calls, persistent memory (facts + searchable log), personality traits and mood | Claude API, SQLite memory, prompt composition | which LLM; custom server or BYO key; editable prompt/tools; where memory lives and whether we can read/write it |
| Local offline voice (Vosk wake/STT, Piper TTS), local commands (emergency stop, shut down, come here) | Pi CPU | offline behavior; any local command path; latency |
| Dev and diagnostics (SSH, logs, rsync deploys, black-box ring buffer, tests) | the Pi | logs, debug console, OTA pinning, recovery |

## Hands-on test steps (when the head arrives)

Do these in order; each step ends with notes in this file or the walk log. Stop and re-plan if a step reveals a safety or
privacy problem.

0. **Privacy gate first.** The head sends audio (and probably camera data) to a third-party cloud. Before powering it:
   use a throwaway account, do not enroll household faces or names, keep personal details out of prompts, read the terms and
   data policy, and decide what is acceptable to say near it. (Applies to every step that uses its cloud.)
1. **Unbox and inspect, off the robot.** Photos, weigh it, measure it, list connectors and visible chips, compare with the
   the parts Petoi's documentation describes, and note which open questions below it already answers.
2. **Power it alone and measure.** From a bench USB supply or a USB meter: idle, speaking and peak current. Decide whether
   the BiBoard's Grove 5 V could feed it without sagging the servo pack.
3. **Standalone bring-up on the bench.** Hotspot, Wi-Fi (2.4 GHz), account, activation, a conversation. Time the latency,
   try the wake word, interrupt it while it speaks. Then **cut Wi-Fi** and note exactly what still works (wake word,
   recognition, vision, canned skills), and what it does with the robot connected (idle, continue, reboot).
4. **Listen to its serial output to the BiBoard** with the Pi's UART or a USB-serial adapter as a passive listener, never
   connected as a second driver: baud, framing, message list. Speak commands and record exactly what it emits; look for
   anything beyond named skills (joint-level `i`/`m` moves, rates).
5. **Connect it to G2 with the Pi still installed.** Petoi says it uses UART2 on the first Grove socket, the same UART as the Pi header by default — so first
   try it with the serial lines **unconnected** (power only) and check the Wi-Fi-only path works; read its USB-C serial log. Then which Grove port, which UART; does it collide with the Pi's Serial-2
   (`XS`) link on pins 9/10 or the onboard voice module? After connecting, re-verify the Pi link (`check_serial ping`, IMU
   at 5.0 Hz) and the voice module. Remove it again if anything breaks.
6. **Motion arbitration.** What happens when the Pi and the head both command the BiBoard (the BiBoard keeps only the
   oldest queued command)? Is there a talk-only mode, or a way to turn motion output off or redirect it to the Pi?
7. **Camera.** Also test whether the head's firmware can read the Grove camera at all. First confirm whether the head has one at all (Petoi's answers describe an ESP32-C3 with only a microphone and speaker and refer
   vision questions to the separate Vision Module). If it does: how models are trained and deployed, on-device vs cloud, and whether a host can read
   detections or frames. If it doesn't: skip — the Grove Vision camera stays.
8. **Audio access.** Raw microphone or speaker access from a host (UART, USB, I2S, WebSocket); transcripts out; text-to-speech
   in; whether the server can be changed (Wi-Fi page settings, OTA URL, firmware) so a backend we control — with Claude
   behind it — answers. Only try a self-hosted server if the terms allow it.
9. **Compute and real-time.** Free CPU/RAM/flash, toolchain, shared cores with the audio/Wi-Fi/LLM tasks. If user code is
   possible, try a trivial 80 Hz loop and measure jitter; try loading a small model (our policy is ~0.5 MB).
10. **Safety and recovery.** Kill Wi-Fi mid-motion, pull the power, confirm the e-stop path that doesn't depend on the cloud;
    note the firmware recovery procedure *before* experimenting with it (never flash the only head without a recovery path).
11. **Dev loop and updates.** Logs and debug console, whether OTA can be pinned or disabled, how to record a session for later
    analysis.
12. **Weight and balance.** Mount it where it would sit, weigh the whole build, and update the payload model (backlog H2) for
    the candidate configurations (Pi build, head only, both).

## Scorecard (fill in after the tests)

| Question | Pi build | Head only | Pi + head |
|---|---|---|---|
| Walking: learned gait kept? scripted as good? | | | |
| Fraction of the "feels alive" behaviors preserved | | | |
| Voice / Claude / memory path (and where data lives) | | | |
| Vision (custom detector, per-person) | | | |
| Safety layers and offline behavior | | | |
| Mass, wiring and robustness | | | |
| Privacy, cost, vendor dependence | | | |
| Dev loop (debugging, logs, recovery) | | | |

**Outcomes:** A) keep the Pi, ignore or sell the head; B) keep the Pi and use the head as an audio/vision front end (only if it
exposes them to a host); C) head only, using Petoi's scripted gaits (gives up the learned policy and the custom safety
layers); D) head only, with our own logic moved to a server or onto the head's own processor. Decide only after steps 3–10.

## How to read what we learn

| If we find | Then |
|---|---|
| Raw mic and speaker access, or a configurable server | **Extendable.** The head can be the audio front end, or a self-hosted server can put Claude behind it |
| Talk-only or motion redirected to a host, plus transcripts or an MCP/HTTP tool hook | **Partly extendable.** Voice front end while the Pi keeps control of motion |
| Camera detections or frames reach a host | The head's camera could replace the Grove Vision camera (one part fewer) |
| Open firmware, free compute for user code, real-time loop and IMU access | **It could replace the Pi.** A large rewrite from Python to embedded code, but possible |
| Only fixed skill codes to the BiBoard, closed firmware | **Canned behavior.** It would compete with the Pi, bypass Claude, memory and personality, and give up the learned gait and safety layers |
| Shares UART2/Serial-2 with the Pi header and can't coexist | Don't connect it without a port plan |
| Cloud-only with no offline or safety fallback | Not acceptable as the only controller of a walking robot |
