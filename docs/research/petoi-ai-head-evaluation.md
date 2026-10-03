# Petoi Bittle AI Head — evaluation plan: replace the Raspberry Pi, sit alongside it, or skip it

Opened 2026-10-02. The head ([product page](https://www.petoi.com/products/bittle-ai-head-upgrade-kit), $39, 42 g) is
**ordered, arriving around 2026-10-10**. What isn't answered by Petoi's documentation we find out **first-hand** with the
steps below. **Keeping the Pi is a fully valid outcome** if it earns its place.

What the head is, as far as known: its own microphone, speaker and camera (the camera can be trained with new
recognition models, per the owner's research); talks over Wi-Fi to the XiaoZhi cloud LLM; wake with "Hi, Jason" or the
Boot button; needs internet and a free account; sends skill codes (`ksit`, `kwkF 3`) to the BiBoard through Grove;
documented for BiBoard V1 / NyBoard V1. Everything else (processor, serial protocol, host interfaces, firmware access,
power draw, offline behavior) is unknown until answered or measured.

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
5. **Connect it to G2 with the Pi still installed.** Which Grove port, which UART; does it collide with the Pi's Serial-2
   (`XS`) link on pins 9/10 or the onboard voice module? After connecting, re-verify the Pi link (`check_serial ping`, IMU
   at 5.0 Hz) and the voice module. Remove it again if anything breaks.
6. **Motion arbitration.** What happens when the Pi and the head both command the BiBoard (the BiBoard keeps only the
   oldest queued command)? Is there a talk-only mode, or a way to turn motion output off or redirect it to the Pi?
7. **Camera.** How models are trained and deployed, class count / input size / frame rate, whether it detects on-device or in
   the cloud (and offline), per-person recognition, and whether a host can read detections or frames at all.
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
