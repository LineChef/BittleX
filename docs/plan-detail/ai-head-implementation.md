# The Petoi AI Head: everything we know and the plan to use it

The one home for facts about the head, the pros and cons of adopting it, what it would take, and a staged path. First hands-on session: 2026-10-11. **Status: exploration. Nothing here is committed yet: adopting the head, forking its firmware and running a backend are all open decisions** (section 8). What is deployed or running right now is in [`../STATUS.md`](../STATUS.md); the original keep-the-Pi-or-not criteria and the behavior inventory stay in [`../research/petoi-ai-head-evaluation.md`](../research/petoi-ai-head-evaluation.md); the vendor's own page is [Petoi AI conversation](https://guide.petoi.com/extensible-modules/ai-conversation).

**The owner's goal for the head (2026-10-10):** offload as much work as possible from Claude to the head, so there are as few API calls as possible. A second, related wish: one voice for G2, not two.

## 1. Where we are

| | State |
|---|---|
| Head | Brought up on the bench, activated on its own account, talking in English. Not mounted on G2. |
| Brain it uses | XiaoZhi's free cloud model ("XiaoZhi Lite", the only choice on the free plan). |
| Tools | Proven: our tool server on the Pi (`python -m pi_pipeline.head`) is called by the head's model through the agent's MCP access point. Two test tools only (`g2_about`, `g2_test_word`). It is started by hand and stops when the Pi reboots. |
| Pi voice service | Stopped by hand on 2026-10-11 (G2 is in pieces); G2's own voice does not work until it is restarted. |
| Firmware | Backed up (read-only copy of the head's whole flash, kept on the Mac outside the repo; it contains the saved Wi-Fi settings, so it is never shared). Not forked, not flashed. |

## 2. What the head is

- **Hardware:** an ESP32-C3 (single core at 160 MHz, no floating-point hardware, Wi-Fi 2.4 GHz and Bluetooth LE), 16 MB flash, mass 42 g (Petoi). By the firmware's board profile `lichuang-c3-dev` (an open-source LCKFB development board): a 320 x 240 color screen, a speaker codec (ES8311), a microphone chip (ES7210) and the button on GPIO 9. Neither Petoi's documentation nor that profile lists a camera. It has a USB-C port (native USB serial) and one Grove cable to the BiBoard.
- **Firmware:** the open-source XiaoZhi firmware (MIT), **version 2.0.4**, built 2026-05-26 with **ESP-IDF 5.4.2**, plus Petoi's additions (below). Petoi has said its head source will be published; it is not yet.
- **Flash layout:** `nvs` (settings, including the saved Wi-Fi: never read), `otadata`, `phy_init`, a 960 KB wake-word `model`, a 7 MB `storage` (assets), and two 4 MB program slots of which only `ota_0` is used. OTA is off by default.
- **Petoi's additions** (not in the upstream project): a `SecondUart` on UART1 (the link to the BiBoard; the pin numbers are constants in the code, not visible as text), a device tool `self.robot.send_command` taking Petoi tokens (`ksit`, `kwkF 3`, `knd` nod, `kwh` shake, `kck` check, `kscrh` scratch), a built-in "Bittle" role text, and an on-screen **face**: tools `self.expression.look` (center, up, down, left, right), `blink`, `set_mouth_width`, `set_mouth_style`, `set_quiet_after_speech`. The firmware also removes tool-call text from speech (`Detected code leak in TTS text`).
- **Transport:** MQTT with UDP audio to XiaoZhi's cloud (as upstream).
- **Wake word:** the on-device model is `wakenet9s` for the Mandarin phrase "你好小智". Petoi's guide says "Hi, Jason". In our tests the **side button** is what reliably wakes it; "Hi, Jason" was not reliable.
- **Source for a fork:** upstream is [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) (MIT). Its tree has the head's board (`main/boards/lckfb/szpi-esp32c3`). A copy of v2.5.0 (commit `ac6deed3…`) and esptool 5.4.0 (hash-verified) sit in `~/g2_head_firmware` on the Mac, outside the repo. v2.5.0 needs a newer toolchain than the head's v2.0.4 base.

## 3. What we learned hands-on (2026-10-11)

**Setup**
1. Power it (USB-C or the Grove cable). With no saved Wi-Fi it opens a hotspot `Xiaozhi-xxxx`; open `http://192.168.4.1`, choose a 2.4 GHz network, enter the password. Once saved it reconnects by itself and no longer shows the hotspot (the Boot button re-enters setup).
2. At the first join it looks up its country from the public IP (a GeoIP lookup), then shows a 6-digit activation code about every 170 seconds.
3. Account at xiaozhi.me (**spelled with "zh"**; a look-alike domain exists): sign-up needs a **phone number** and an SMS code. In the console: **create an agent first, then Add Device** with the code. A new boot gives a new code.
4. The new agent listens and replies in **Mandarin** until its language is set to English in the agent's settings.

**Console settings seen:** a role page (language, voice, the role/introduction text, and at the bottom right the agent's **MCP access point**), Model & Memory (one model on the free plan), a knowledge-base feature (limits not yet checked), Extensions. Speaker Recognition is not on the free plan. The voice list changes only the voice.

**Reading the head:** its USB-C port is a serial log at 115200. **Opening the port reboots it.** The log prints each turn: `>>` what it heard, `<<` what it said, plus network, wake-word and tool messages.

**Conversation quality:** greetings, small talk, simple arithmetic and questions about itself were answered by its own model, about one second to the start of a reply, with no Claude call. The tone comes from the role text and the model (it said "la" and "eh" until prompted otherwise); it also knows the date from the server.

**The device's own robot tool does not work with the free model:** every "sit down", "shake your head" and "say goodbye" made the model write `% self.robot.send_command...` into its speech; the firmware stripped it and no command reached the BiBoard (checked on the BiBoard's USB log and the Pi's serial line). Petoi's recommended role template made no difference.

**MCP works, with the same free model.** A tool server of ours on the Pi (`pi_pipeline/head/mcp_tools.py`, using the `websockets` package already on the Pi) connects out to the access point. The cloud immediately sent `initialize`, `notifications/initialized`, `tools/list` and later `ping`. A made-up answer (`g2_test_word` = "marmalade") was spoken by the head and the Pi's log showed the `tools/call`. So **the head's model can reach G2's abilities through code we control**, with our rules and safety layers.

**Wiring and BiBoard facts**
- The head's serial lines run through the first Grove socket (G1 = UART2, the only UART-capable one), the same UART as the Pi's 5-pin header. G1 is free now; the camera runs over the Pi's USB.
- **The Pi cannot hear the head's commands:** the Pi's receive pin is on the BiBoard's transmit line; the head's transmit is on the BiBoard's receive line. The Pi hears only the BiBoard's own output (the IMU stream). A 2-minute Pi listener with the head plugged in only saw that. To see the head's commands, use its own USB log, the BiBoard's replies, or a USB-serial adapter on the head's transmit line.
- On USB power alone the BiBoard boots, prints `Low power: 2.27V. The robot won't move.` every 10 seconds, and still answers a query from the Pi on its Serial2 (so that path works in that state). In that state G2 cannot move.
- Powering the head from the BiBoard's Grove 5 V and from a Mac at once is two supplies on one rail: avoid. Its current draw on the Grove supply is **not measured yet**.

**What G2 spends on Claude today:** 57 billed calls, about $0.33, in 72 hours (2026-10-07 to 10-10). The saving the head can offer in dollars is small; the reason to use it is the principle of fewer calls, the face, and the placement of the mic and speaker.

**Pushing a message to the head so it speaks (researched 2026-10-11)**
- **The protocol has push messages,** but only the *server* side of the head's connection can send them: the cloud broker that the head's MQTT link goes to. Upstream documents these (`docs/notify.md` and `main/application.cc` in the xiaozhi-esp32 source): `notify` (an https/http URL to a mono Ogg Opus file, plus optional subtitles, played while the head is idle), `alert` (status, message and emotion: shows text and a face emotion and plays a sound), `tts` (the cloud's own speech: start, stop, sentence text; the audio comes over the audio channel) and `custom` (only if the firmware is built with that option).
- **In the head's firmware (v2.0.4):** `alert`, `tts`, `stt`, `llm`, `mcp`, `system` and `iot` message types are present; **`notify` is not** (no `audio_url` or `subtitles` handling; it arrived in a newer release).
- **For us:** no documented public interface on xiaozhi.me for sending these to our own head. Searches in English and Chinese turned up none; the one lead is a community pattern of a platform-run scheduled task that calls an MCP tool and speaks the result (polling, not a push, and unverified on the free plan). Upstream's `xz-mqtt` forwarding is the vendor's internal server tooling.
- **So** without firmware or a backend of our own, the Pi cannot make the head say something on its own. With **our own backend** (stage 8) we would be the server and could send `alert` now and `tts` audio; `notify` would also need a firmware newer than v2.0.4. With a **firmware change** (stage 7) a host-driven speaker is the other route.

## 4. Pros and cons of adopting the head

**Pros**
- A free cloud model handles open-ended chat, small talk and simple questions with no Claude call.
- It can reach G2's abilities and facts through our own tools (proven), so it can answer "what did you do" and "what have you learned" from the Pi without Claude.
- It adds a **screen with an animated face** (look, blink, mouth) that G2 does not have.
- Microphone and speaker sit in the head, a natural place for them, and it is a vendor-supported accessory ($39) with a documented Grove connection.
- The firmware base is open source (MIT) and Petoi has said theirs will be, so a custom wake word, a host-driven speaker or our own backend stay possible later.
- Everything on the Pi (gait, safety, vision, exploration, memory, reflection) is unaffected: the head complements the Pi, as Petoi says.

**Cons**
- **Voice:** through the head G2 speaks with a stock cloud voice, not his Piper robot voice. G2's own lines (narration, alarms, announcements) cannot be spoken through it without a firmware change.
- **Two voices** while the Pi voice stays; one voice means giving up Pi speech or changing firmware.
- **Wake word:** the side button only, in practice. A different wake word needs firmware.
- **Privacy:** every sentence goes to XiaoZhi's cloud; the account needs a phone number; retention terms are unread; tool answers also pass through their cloud.
- **Dependence on a free service** that can change or stop; G2 is silent without Wi-Fi or the service.
- **Personality is thinner:** a small model with a fixed role text, and no mood, traits or memory unless a tool supplies them.
- **Small saving in money** (see section 3).
- **Weight:** 42 g at the front of a robot that is already about 46 percent front-heavy, and the walking policy was trained with an assumed head mass. Not yet checked in simulation.
- **Small chip** (one core, little memory), so the heavy work stays on the Pi.
- **The device's own robot tool is unusable** with the free model, and the head's serial lines stay connected to the BiBoard's input, so it could send motion on its own if its model ever calls the tool.
- **Two sources of truth to maintain:** an agent configured in a web console, plus our tool server.
- **Firmware is not published**, so any change starts from upstream plus a rebuild of Petoi's additions.

## 5. The target

The head is G2's **mouth, ears and face**. The Pi remains the body's brain (gait, safety, vision, exploration, memory, reflection). The head's free model does the everyday talking; our tools give it facts about G2; Claude answers only the turns that need G2's memory and personality, through an "ask the brain" tool. G2 speaks in one voice, and anything he must say on his own (alarms, announcements) has a route.

## 6. What it takes: the full list

| Area | Work |
|---|---|
| Account and agent | Role text (persona, brevity, English, "call tools for facts about G2"); a chosen voice; keep the MCP access point secret in the Pi's `.env` (`XIAOZHI_MCP_ENDPOINT`); read XiaoZhi's terms for data retention; decide on the knowledge base (probably not needed). |
| Pi software | Tool server as a service (start at boot, restart on failure, log each call with a count); real tools: about G2, last-exploration recap, experience notes, persona and mood hint; an **"ask the brain"** tool to Claude with a call log and rate limit; later a skills tool with an allowlist; keep tool answers safe to leave the house. |
| Voice policy | One-voice rules (section 7, stage 4); answers to local commands (battery, floor, recap) become tools; alarms and narration need a non-speech route or a firmware change. **The emergency stop must stay on the Pi** (local stop-word listening, silent): never depend on the cloud to stop G2. |
| Hardware | Measure the head's current on the Grove 5 V; check the center of mass and the walking policy in simulation with the head's mass; mount on the head servo; Grove cable to G1; decide whether the head's transmit line stays connected to the BiBoard; check the camera mount and the head do not collide (Petoi: they do not). |
| Firmware (optional) | Custom wake word; host-driven speaker (text or audio from the Pi, so G2's Piper voice); remove the head's direct robot command; keep Petoi's face tools; toolchain ESP-IDF 5.4.2 and the v2.0.4 source; flash with the backup in hand. |
| Backend (optional) | A server the head connects to: speech-to-text, the brain, Piper with the robot effect, tool handling; point the firmware at it; a machine that is always on. |
| Safety and privacy | Hardware rules (G2 on his feet, hands near; no moving while he is in pieces); no household names, faces or routines in the role text, tools or knowledge base; endpoint and account details never in chat, logs or the repo. |
| Measurement | Before and after: Claude calls per day (`python -m pi_pipeline.voice.api_log`, `python -m pi_pipeline.memory calls`), share of turns the head handled, tool-call success rate, delay, and quality. |

## 7. Staged integration

Each stage ends in something that works on its own, so the project can stop after any of them.

**Stages at a glance: what each one gains and what it costs**

| Stage | What we gain | What we lose or risk |
|---|---|---|
| **0. Bench bring-up** (done) | The head talks in English on its own account; our tool server answers its model; the firmware is backed up. | Nothing from G2's existing setup. The test audio goes to XiaoZhi's cloud, and the account holds a phone number. |
| **1. Talker + read-only tools** | Free chat about G2; "what did you do" and "what have you learned" answered from the Pi with no Claude call; real measurements of the savings. | Nothing existing is removed. There are briefly two voices (the head on the button, the Pi as usual), a small service to keep running, and tool answers pass through the cloud. |
| **2. Personality + escalation** | The head carries G2's mood and traits through a tool; hard questions go to Claude with G2's memory, spoken by the head; Claude is called only then. | Casual chat is flatter than Claude's. A hard question takes two hops, so it is slower. A new rate limit and call log to maintain. |
| **3. Mount on G2** | The head on his body with the face in front; microphone and speaker in the head. | About 27 g more at the nose than the 15 g head the walking policy assumes, which may change the gait; unmeasured current on the Grove supply; a risk that the head's serial line sends commands (default: leave it disconnected). |
| **4. One voice, no firmware change** | A single voice for all conversation, and answers to commands as tools. | **G2's robot voice; spoken narration and alarms** (they become sounds); the Pi's hands-free "G2" wake word (the head is button-only); local, offline speech (all speech now goes to the cloud). The silent stop-word listener stays on the Pi. |
| **5. Motion through the head** | "G2, sit" and similar through the head, with the Pi's eased stand-up and fall guard around it. | A new way for G2 to move: it needs an allowlist, refusal rules and trust in a cloud model that may mishear. |
| **6. The face** | An expressive screen tied to his mood and events. | It depends on whether the cloud model can call the head's own face tools; if not, it waits for stage 7. |
| **7. Firmware fork** (not decided) | A hands-free wake word; the Pi can send text or audio to the head's speaker (self-initiated speech and the robot voice for those lines return); the head's direct robot command removed. | We maintain a fork and no longer get Petoi's updates; a multi-GB toolchain download; a flash (the backup is the way back); Petoi's additions rebuilt unless their source appears. Conversation is still the cloud voice. |
| **8. Our own backend** (optional) | G2's own voice everywhere; no audio to XiaoZhi's cloud; independence from the free plan. | The free brain: Claude calls return (or a weaker local model); a machine that must be on; more moving parts. |

**Stage 0: bench bring-up and the tool proof. Done 2026-10-11.** Gets working: the head talks in English on its own account; our tool server answers its model; the firmware is backed up.

**Stage 1: a talker with read-only tools, beside the Pi voice (no mounting).**
- Work: run the tool server as a service; replace the test tools with `g2_about`, a last-exploration recap and the experience notes; write the role text; choose a voice; log every tool call.
- Gets working: press the head's button and ask what G2 is, what he did, what he has learned; answers come from the Pi with no Claude call. The Pi's own voice is unchanged.
- Measure: tool-call reliability over a set of questions; the delay; how many of G2's usual Claude turns the head can take.
- Stop point: if the model calls tools unreliably, the head stays a toy and nothing else is affected.

**Stage 2: personality and escalation.**
- Work: a persona tool (current mood hint, traits); an **"ask the brain"** tool that sends a hard question through the Pi to Claude with G2's memory and personality, rate-limited and logged.
- Gets working: casual chat is free; hard questions get Claude's answer with G2's memory, spoken in the head's voice. Claude is called only then.
- Measure: Claude calls per day against the baseline; how often the model chooses to escalate.

**Stage 3: mount the head on G2.**
- Work: current measurement; center-of-mass and gait check in simulation with the head's mass; mount; Grove to G1; decide about the head's transmit line (a safe default is to leave it disconnected); standing test, then a short walk, with G2 on his feet and hands near.
- Gets working: the head on G2's body, powered by him, his face in front.
- Risk: weight at the nose; if the policy copes poorly, the mount stops here.

**Stage 4: one voice, no firmware change.**
- Work: turn off the Pi's spoken output; keep its non-voice sounds (horns, "oof", chirps); answers to local commands become tools; narration and alarms become sounds or nothing; the Pi keeps a silent local stop-word listener.
- No route found for the Pi to push speech to the head without firmware or a backend (section 3).
- Gets working: G2 has one voice (the head's, a stock voice) for all conversation. Loses: self-initiated spoken lines, his current robot voice, the hands-free "G2" wake word (the head is button-only), and offline speech.
- Decision gate: if losing the robot voice and the spoken narration is too much, stop at stage 3, or go to stage 7.

**Stage 5: motion through the head, via the Pi.**
- Work: a skills tool with an allowlist (sit, wave, nod and similar), run through the Pi's skill layer with the eased stand-up and the fall guard; refuse while halted, exploring or on low battery; log each use.
- Gets working: "G2, sit" works through the head with the Pi's safety around it.

**Stage 6: the face.**
- Work: find out whether the cloud model can call the head's own face tools; if so, tie expressions to mood and events.
- Gets working: an expressive screen. If those tools are unreachable, this needs firmware (stage 7).

**Stage 7: firmware fork (decision gate; not decided).**
- Work: wake word; host-driven speaker so the Pi plays G2's Piper robot voice through the head; the head's direct robot command removed; Petoi's face tools kept.
- Gets working: a hands-free wake word and G2's own voice for his announcements. Conversation is still the cloud voice unless stage 8.
- Prerequisites: Petoi's source (or a rebuild from upstream v2.0.4); the ESP-IDF 5.4.2 toolchain (a multi-GB download, needs approval); the backup in hand.

**Stage 8: our own backend (optional).**
- Work: a server for the head's audio protocol: speech-to-text, the brain (Claude, or a local model), Piper with the robot effect; the firmware pointed at it; an always-on machine (a Mac works only while it is on and awake; a small always-on computer is roughly $100 to $200, or a rented server a few dollars to about $20 a month; the Pi is already busy).
- Gets working: G2's own voice everywhere and no audio to XiaoZhi's cloud. Costs: the Claude calls come back (the brain is Claude again), so the call savings from the free model are gone.

**Existing community servers (read about, not downloaded; for stage 8).** The firmware README lists several open-source backends that speak the same protocol; the main one is [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) (Python, Java and Vue, MIT). From its README: MQTT+UDP, WebSocket and MCP access-point support; local speech-to-text (FunASR, SherpaASR) and local text-to-speech (FishSpeech, GPT-SoVITS, Index-TTS, PaddleSpeech; **Piper is not listed**); any LLM with an OpenAI-style interface; Docker or source install. Its minimum is 2 cores and 2 to 4 GB of memory, **more than the Pi Zero 2 W has** (512 MB); it calls itself not production-ready and not security-tested. It documents **no** "send text to a device" interface (only MCP commands sent from its console). The head would need to be pointed at its OTA and WebSocket addresses, which is a firmware matter. Our own small server speaking the documented protocol (`docs/websocket.md` and `docs/mqtt-udp.md` in the firmware source) remains the alternative to adopting one of these.

**The trade-off in one line:** the free brain and the cloud voice come together; G2's own voice everywhere comes with our own backend, where we pay for the brain again.

## 8. Decisions waiting on the owner

1. Whether to adopt the head as G2's voice at all, or keep the Pi voice and use the head as a trial.
2. Whether a stock cloud voice is acceptable for G2.
3. Whether to fork the firmware (stage 7) or wait for Petoi's source. Not decided; no fork work has started.
4. Whether a backend is worth running (stage 8), and on what machine.
5. What the head's model may do beyond talking (stage 5), and what may leave the house through tools.

## 9. Still to verify (none of it blocks writing this or stage 1)

- How reliably the free model calls tools (rate over many tries) and how long a tool round trip takes.
- Whether the cloud model can call the head's own face and volume tools.
- Behavior over long sessions and Wi-Fi drops; whether the tool server reconnects cleanly overnight (it reconnects with a growing pause; not yet exercised for hours).
- Whether the console has an interface to update the role text from code (for a live persona).
- The knowledge base's file types, size limit and cost; XiaoZhi's data-retention terms.
- The head's power draw; the exact serial pins; how the head's serial output looks on the wire (needs its transmit line, see section 3).
- The effect of the head's mass on the walking policy (simulation first).
- The custom wake-word process for the chip's speech library.
- Whether the xiaozhi.me console or its documentation has any interface for sending a message to the head (none found in searches or in the one official document read, the MCP access-point guide); ask or look in the console before relying on the answer.

## 10. How-to reference

- **Read the head's log (Mac):** plug the head's USB-C into the Mac, find the new `usbmodem` port, open it at 115200 (this reboots the head). Do not do this while the Grove cable also powers it.
- **Run the tool server (Pi):** `cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.head` (reads `XIAOZHI_MCP_ENDPOINT` from `.env`; logs request names, never the address). Stop with Ctrl-C or `pkill`.
- **Set the access point:** copy it from the console's role page; add it to the Pi's `.env` with a hidden-input command so it never appears on screen or in chat; verify only with a count and the first characters of the line.
- **Backups:** the head's firmware is read with esptool's read-only `read-flash`; the copy and its checksum are on the Mac, outside the repo. Restoring is a write and needs the owner's go.
- **Safety:** G2 does not move while he is in pieces (battery off, or USB power alone so the BiBoard reports low power); never flash anything without a checked backup; never put the access point, account details or the Wi-Fi settings in the repo or in chat.

## 11. Related

[`../research/petoi-ai-head-evaluation.md`](../research/petoi-ai-head-evaluation.md) (the original questions, vendor answers, behavior inventory, scorecard) · [`../research/xiaozhi-esp32-review.md`](../research/xiaozhi-esp32-review.md) · [`../research/firmware-fork-case.md`](../research/firmware-fork-case.md) · [`../guides/swappable-llm.md`](../guides/swappable-llm.md) · [`../guides/settings-switches.md`](../guides/settings-switches.md) · [`reflection-plan.md`](reflection-plan.md)
