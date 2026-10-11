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

**The vendor's rules for tools (their MCP access-point guide, the precautions section)**
- Name tools and parameters so the model knows what they do (no abbreviations; for a search tool the parameter is `keywords`), and put the guidance for when to use a tool in its description.
- A tool's return value is usually a string or JSON and is **limited, typically to 1024 bytes**; our server cuts results at 1000 bytes.
- The tool list text is limited too (counted in tokens), so keep the list short.
- Each access point has an upper limit on connections: run one connector only.
- The console's "MCP access point" dialog shows the connection status (online) and the **names of the registered tools**, a quick way to check that our server is connected.
- The vendor's own example tool evaluates a Python expression from the model (`eval`); we do not do that.

**Flashing without a toolchain (from the vendor's firmware flashing guide, a Feishu page, updated 2026-01-27)**
- A prebuilt upstream image exists for the head's board: board type `BOARD_TYPE_LICHUANG_C3`, firmware file `vx.x.x_lichuang-c3-dev.zip` (the S3 board is a different row), from the official firmware list.
- It is flashed as a single `merged-binary.bin` written at address 0x0 (the whole flash), either with Espressif's Flash Download Tool 3.9.7 in UART mode (Windows-oriented; the path must not contain Chinese characters) or with esptool; the guide also mentions a browser-based method (not seen).
- The guide gives three ways: Espressif's Flash Download Tool 3.9.7 (Windows, UART mode, address 0x0, no Chinese characters in any path); a third-party web flasher (needs Edge and a login; skipped); and **ESP-Launchpad**, Espressif's own browser flasher (`espressif.github.io/esp-launchpad`, Chrome or Edge: DIY page, Connect, pick `merged-binary.bin`, address 0x0, Program, then Reset Device). esptool, which we already have, does the same write.
- **Forcing download mode** if a board will not respond: hold BOOT, tap RST, release BOOT. The head's C3 has native USB, so none of the guide's serial-chip drivers (CH340/CH343) are needed.
- **Restoring the backup is the same operation:** the backup is a full 16 MB image from address 0x0, the same shape as `merged-binary.bin`, so writing it back at 0x0 restores Petoi's firmware and its saved settings. (A generic prebuilt image overwrites the settings partition too.)
- So stock upstream firmware could be tried on the head **without building anything**. It would replace Petoi's additions (face tools, the BiBoard serial link, the robot tool), and the read-only backup is the way back. Nothing has been flashed; this is not a decision to fork.

**The device protocol (the vendor's WebSocket page, modified 2025-07-26; it matches upstream `docs/websocket.md`, `docs/mqtt-udp.md` and `docs/mcp-protocol.md`)**
- WebSocket, protocol version 1. The device connects with `Authorization: Bearer <token>`, `Protocol-Version`, `Device-Id` (its MAC address) and `Client-Id` (a UUID), then sends `hello` (features `mcp: true`; audio Opus, 16 kHz, mono, 60 ms frames); the server answers `hello` (audio at 24 kHz; no session id). Our head uses **MQTT with UDP audio** instead (its log: "no protocol specified in the OTA config, using MQTT"); the message types are the same.
- Device to server: `hello`, `listen` (`start` with a mode auto, manual or realtime; `stop`; `detect` for a wake word), `abort`, `mcp`. Server to device: `hello`, `stt` (what it heard), `llm` (an `emotion`, which drives the **screen face**), `tts` (`start`, `stop`, `sentence_start` with the sentence text), `mcp` (JSON-RPC 2.0), `system` (`reboot`), `alert` (status, message, emotion and a sound), `custom` (only if built in), and **binary Opus audio frames** (dropped while the device is listening). Audio goes up as Opus after optional echo cancellation, noise reduction and gain control.
- Device states: starting, Wi-Fi configuring, activating, idle, connecting, listening, speaking, upgrading; in manual mode a button press toggles listening, in auto mode the server's voice detection ends it.
- **What this means for pushing speech:** the audio channel opens when a conversation starts (the device connects, or opens it on a wake), so a server cannot simply start speaking to an idle head over the conversation channel; that gap is what the newer `notify` message fills. A server we run could send `alert` and, with an open channel, `tts` plus audio frames; this is the stage 8 work.

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

### Removing the Pi's own microphone and speaker (a long-term goal of the owner)

The first draft of the staged plan assumed they stay. What depends on them today (microphone: Vosk wake word, speech recognition and the local stop words; speaker: Piper speech and every sound):

| Behavior | Needs today | Mic and speaker removed, stock firmware (stage 4) | Mic and speaker removed, with the head as the Pi's audio peripheral (stage 7b) |
|---|---|---|---|
| Conversation | Pi mic and speaker | Works through the head (button, stock cloud voice) | Works, in G2's voice, local |
| Hands-free wake word "G2" | Pi mic (Vosk) | **Lost** (button only) | Works (Vosk on the audio the head sends) |
| Emergency stop by voice ("emergency stop", "freeze", "halt") | Pi mic, local, never the cloud | **Lost** unless another path exists | Works, plus an independent path (the head link is Wi-Fi) |
| Exploration voice control ("go ahead and look around", "that's enough", "tell me what you see", naming an object) | Pi mic | **Lost** while G2 is away from the button (some could become tools, but only after a button press) | Works |
| Spoken narration and alarms | Pi speaker | **Lost** (silent) | Works |
| Sounds (horn, "oof", chirps, ta-da) | Pi speaker | **Lost**, except the BiBoard's own buzzer beeps | Works (audio sent to the head) |
| Sleep and wake by wake word | Pi mic | Button only | Works |

**Order, decided by the owner (2026-10-11): the Pi's microphone and speaker stay installed until the head's own microphone and speaker can do their job.** Nothing in the table above is lost along the way, because they are removed only after stage 7b is proven. Until then every stage, including stage 4, runs with them in place.

**Gate before anything is unplugged (all of these, on the real G2):**
1. The wake word "G2" wakes him from across a room using the head's microphone, and false wake-ups are no worse than today.
2. The voice emergency stop works from the head's audio, and an independent stop path (not the head's Wi-Fi link alone) exists and was tested.
3. Exploration commands work by voice while he is walking away from the button.
4. Speech, narration, alarms and every sound play on the head's speaker at a usable level, with no clipping and no echo into the microphone.
5. The head's audio link survives the things that go wrong: Wi-Fi dropping and returning, the Pi restarting, the head rebooting, an hour of use.
6. The Pi's load and the delay from speech to reply are no worse than today (the Pi already runs some control ticks late during exploration).
7. Power: the head's added current on the Grove supply fits the battery budget, and the Pi's saved current is measured.
8. A way back: the removed mic and speaker (and their wiring notes in `blueprints/`) are kept so they can be reinstalled.

So with the stock firmware, if they were removed early, this would cost hands-free control, the voice emergency stop, exploration voice commands, narration and sounds. **Even stage 7 as first described (wake word plus a host-driven speaker) does not cover the microphone side.** What does is **stage 7b** below, which is also what Petoi said the head's firmware could do (stream the microphone out, accept audio to play).

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
| **7b. Head as the Pi's mic and speaker** (firmware) | Everything the Pi voice does today (G2's voice, wake word, voice stop, exploration commands, narration, sounds) from hardware in the head, local; the Pi's own mic and speaker can be removed. | The free cloud brain (the Pi's Claude pipeline keeps talking); a Wi-Fi link between head and Pi that the voice stop must not depend on alone; unproven chip capacity. |
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
- The Pi's microphone and speaker stay installed through this stage (they come out only after stage 7b passes its gate), so the silent stop-word listener keeps working.
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

**Stage 7b: the head as the Pi's microphone and speaker (firmware change; this is the route to removing the external mic and speaker, and only after the gate above is met).**
- Work: firmware that streams the head's microphone audio to the Pi over the local network (not the cloud) and plays audio the Pi sends; the Pi's existing voice pipeline (wake word, speech recognition, stop words, exploration commands, Piper, sounds, the audio gate) runs on that audio unchanged; check echo between the head's speaker and microphone; keep an independent stop path (the head link is Wi-Fi, so it must never be the only way to stop G2); then remove the Pi's microphone and speaker.
- Gets working: everything the Pi voice does today, from hardware in the head: G2's own voice, the hands-free wake word, the voice emergency stop, exploration commands, narration, alarms and all the sounds. Local and private. One set of audio hardware, the screen face on the same unit.
- Loses: the free cloud brain for chat (the Pi's own pipeline keeps using Claude as it does now; the head's cloud model would be off), and a dependence on a reliable Wi-Fi link between the head and the Pi.
- Prerequisites: stage 7's firmware work plus microphone streaming (a prebuilt upstream image for the head's board exists, see section 3, for trying stock upstream first); whether the C3 can stream audio, play audio, run the screen and keep Wi-Fi stable at once is **not yet known**.

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
6. Decided 2026-10-11: the long-term goal is to remove the Pi's own microphone and speaker, but only once the head's microphone and speaker can do their job. The route is stage 7b (a firmware change), with the gate in section 6 first.

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

**Documents worth collecting now** (so there is no need to come back for them)
- Public, and I can read them myself: Petoi's BiBoard V1 guide and serial-protocol page; Espressif's speech-recognition (wake word) documentation; the upstream firmware's `xiaozhi-assets-generator` README (custom wake words); the head board's open-source schematic.
- Needs the owner (Feishu pages my tool cannot open; screenshots saved to the Desktop, scrolled to the bottom so everything loads). The vendor's hub is the "XiaoZhi AI Chatbot Encyclopedia" (`xiaozhi.me/docs` redirects to it: `https://ccnphfhqs21z.feishu.cn/wiki/F5krwD16viZoF0kKkvDcrZNYnhb`). Pages in priority order: (1) **通信协议：Websocket 连接** (message types, audio, pushing; the server README links a "小智通信协议" page at `…/wiki/M0XiwldO9iJwHikpXD5cEx71nKh`); (2) **小智AI声音复刻（公测）控制台操作指引** (voice cloning, public beta: a cloned voice could give the head a G2-like voice without firmware); (3) **关于唤醒词更改及配置操作步骤** and **小智AI终端ASR自定义唤醒词简单方案** (wake word); (4) **小智AI固件在线编译功能操作教程文档** (online firmware build, possibly no local toolchain); (5) **小智AI终端开源项目SDK配置AEC支持操作步骤** (echo cancellation, stage 7b); (6) **OTA 接口文档** (how the device finds its server); (7) **通信协议：Emoji 心情显示** (the screen face); (8) **小智知识库使用说明** (knowledge base limits); (9) **小智AI聊天机器人常见问题Q&A【先看】**. Lower: account recovery and unbinding a device, 小智AI 开发者认证 (developer certification), the firmware download pages (v2.0.5, v2.2.4; the head is v2.0.4), changing the built-in prompt sounds (P3 files). Already read: the MCP access-point guide and the flashing guide. Also from the owner: Petoi's three wiring diagrams and the full Role template; console screenshots (Model & Memory, voice list, knowledge base, MCP dialog); xiaozhi.me's plans, terms and privacy policy.

## 10. How-to reference

- **Read the head's log (Mac):** plug the head's USB-C into the Mac, find the new `usbmodem` port, open it at 115200 (this reboots the head). Do not do this while the Grove cable also powers it.
- **Run the tool server (Pi):** `cd ~/bittleX && pi_pipeline/.venv/bin/python -m pi_pipeline.head` (reads `XIAOZHI_MCP_ENDPOINT` from `.env`; logs request names, never the address). Stop with Ctrl-C or `pkill`.
- **Set the access point:** copy it from the console's role page; add it to the Pi's `.env` with a hidden-input command so it never appears on screen or in chat; verify only with a count and the first characters of the line.
- **Backups:** the head's firmware is read with esptool's read-only `read-flash`; the copy and its checksum are on the Mac, outside the repo. Restoring is a write and needs the owner's go.
- **Safety:** G2 does not move while he is in pieces (battery off, or USB power alone so the BiBoard reports low power); never flash anything without a checked backup; never put the access point, account details or the Wi-Fi settings in the repo or in chat.

## 11. Related

[`../research/petoi-ai-head-evaluation.md`](../research/petoi-ai-head-evaluation.md) (the original questions, vendor answers, behavior inventory, scorecard) · [`../research/xiaozhi-esp32-review.md`](../research/xiaozhi-esp32-review.md) · [`../research/firmware-fork-case.md`](../research/firmware-fork-case.md) · [`../guides/swappable-llm.md`](../guides/swappable-llm.md) · [`../guides/settings-switches.md`](../guides/settings-switches.md) · [`reflection-plan.md`](reflection-plan.md)
